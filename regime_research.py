"""Rolling three-state research. Test HMM inference is causal filtering only."""
import math
from datetime import date
import numpy as np
from scipy.special import logsumexp
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

NAMES = {'markov': '阈值马尔可夫', 'kmeans': 'KMeans 聚类', 'hmm': '高斯 HMM'}
STATES = ['弱动量特征', '中间特征', '强动量特征']


def emission_logpdf(x, means, variances):
    return -.5*np.sum(np.log(2*np.pi*variances)[None,:,:]+(x[:,None,:]-means[None,:,:])**2/variances[None,:,:],axis=2)


def forward(log_emissions, transition, initial):
    """Normalized forward marginals and joint observation log likelihood."""
    log_a=np.log(transition)
    logs=np.empty_like(log_emissions)
    logs[0]=np.log(initial)+log_emissions[0]
    for t in range(1,len(logs)):
        logs[t]=log_emissions[t]+logsumexp(logs[t-1,:,None]+log_a,axis=0)
    norms=logsumexp(logs,axis=1)
    return np.exp(logs-norms[:,None]),float(norms[-1]),logs


def fit_hmm(x,max_iter=60):
    """Three diagonal Gaussian states, EM with disclosed variance/probability floors."""
    x=np.asarray(x,dtype=float)
    if type(max_iter) is not int or not 1<=max_iter<=200:raise ValueError('HMM 迭代次数应为 1–200 的整数')
    if x.ndim!=2 or len(x)<30 or x.shape[1]!=3 or not np.isfinite(x).all() or len(np.unique(x,axis=0))<3:
        raise ValueError('HMM 需要至少 30 行有效三维特征和三个不同观测')
    candidates=[]
    for seed in (17,43):
        init=KMeans(n_clusters=3,n_init=5,random_state=seed).fit(x)
        means=init.cluster_centers_.copy()
        variances=np.array([np.maximum(np.var(x[init.labels_==s],axis=0),.01) for s in range(3)])
        transition=np.full((3,3),.5)
        for a,b in zip(init.labels_,init.labels_[1:]):transition[a,b]+=1
        transition/=transition.sum(axis=1,keepdims=True)
        initial=np.full(3,1/3)
        previous=None;converged=False;history=[]
        for iteration in range(max_iter):
            emissions=emission_logpdf(x,means,variances)
            _,ll,alpha=forward(emissions,transition,initial)
            history.append(ll)
            beta=np.zeros_like(alpha);log_a=np.log(transition)
            for t in range(len(x)-2,-1,-1):
                beta[t]=logsumexp(log_a+emissions[t+1][None,:]+beta[t+1][None,:],axis=1)
            gamma=np.exp(alpha+beta-ll)
            gamma/=gamma.sum(axis=1,keepdims=True)
            counts=np.maximum(gamma.sum(axis=0),1e-12)
            xi=np.zeros((3,3))
            for t in range(len(x)-1):
                xi+=np.exp(alpha[t,:,None]+log_a+emissions[t+1][None,:]+beta[t+1][None,:]-ll)
            initial=(gamma[0]+.5)/(gamma[0].sum()+1.5)
            transition=(xi+.5)/(xi.sum(axis=1,keepdims=True)+1.5)
            means=(gamma.T@x)/counts[:,None]
            variances=np.maximum((gamma.T@(x*x))/counts[:,None]-means*means,.001)
            if previous is not None and abs(ll-previous)/len(x)<1e-4:
                converged=True
                break
            previous=ll
        # State order is set by training 20-observation momentum, never test returns.
        order=np.argsort(means[:,1],kind='stable')
        model={'means':means[order], 'variances':variances[order],
               'transition':transition[np.ix_(order,order)], 'initial':initial[order]}
        filtered,score,_=forward(emission_logpdf(x,model['means'],model['variances']),model['transition'],model['initial'])
        if np.isfinite(score):
            model.update({'filtered':filtered,'log_likelihood':score,'converged':converged,
                          'iterations':iteration+1,'seed':seed,'likelihood_history':history})
            candidates.append(model)
    if not candidates:raise ValueError('HMM 拟合数值失败，未替换为其他模型')
    return max(candidates,key=lambda m:m['log_likelihood'])


def filter_step(x,model,previous):
    prior=np.asarray(previous)@model['transition']
    logp=np.log(prior)+emission_logpdf(np.asarray(x)[None,:],model['means'],model['variances'])[0]
    return np.exp(logp-logsumexp(logp))


def transition_matrix(states):
    counts=np.full((3,3),.5)
    for a,b in zip(states,states[1:]):counts[a,b]+=1
    return counts/counts.sum(axis=1,keepdims=True)


def metrics(rows):
    valid=[r for r in rows if r['actual'] is not None]
    if not valid:return None
    y=np.array([r['actual'] for r in valid]);up=(y>0).astype(float)
    p=np.array([r['up_probability'] for r in valid])
    b=np.array([r['baseline_up_probability'] for r in valid])
    prediction=np.array([r['prediction'] for r in valid])
    baseline=np.array([r['baseline_prediction'] for r in valid])
    calibration=[]
    for lo in np.arange(0,1,.2):
        indexes=(p>=lo)&(p<(lo+.2) if lo<.79 else p<=1)
        if indexes.any():calibration.append({'lower':float(lo),'count':int(indexes.sum()),
            'predicted':float(p[indexes].mean()),'observed':float(up[indexes].mean())})
    by_state=[]
    for s in range(3):
        selected=[r['actual'] for r in valid if r['state']==s]
        by_state.append({'state':s,'count':len(selected),'mean_next_return':float(np.mean(selected)) if selected else None})
    return {'samples':len(valid),'brier':float(np.mean((p-up)**2)),
            'baseline_brier':float(np.mean((b-up)**2)), 'mae':float(np.mean(abs(prediction-y))),
            'baseline_mae':float(np.mean(abs(baseline-y))),
            'direction_accuracy':float(np.mean((p>=.5)==(up>0))),
            'state_switches':sum(a['state']!=b['state'] for a,b in zip(valid,valid[1:])),
            'calibration':calibration,'by_state':by_state}


def regime_experiment(bars,end,lookback=126,threshold=.05):
    date.fromisoformat(end)
    if type(lookback) is not int or lookback not in (126,252) or not math.isfinite(threshold) or not .001<=threshold<=.5:
        raise ValueError('训练窗口仅支持 126/252 日，阈值应为 0.1%–50%')
    rows=[b for b in bars if b['date']<=end]
    days=[b['date'] for b in rows]
    if days!=sorted(set(days)):raise ValueError('日线日期须递增且不重复')
    for b in rows:
        date.fromisoformat(b['date'])
        if not isinstance(b['close'],(int,float)) or not math.isfinite(b['close']) or b['close']<=0:
            raise ValueError('收盘价须为正有限数')
    if len(rows)<lookback+63:raise ValueError('历史不足：需 20 日特征预热、完整训练窗和至少 42 个已完成样本外标签')
    prices=np.array([b['close'] for b in rows],dtype=float)
    ret=prices[1:]/prices[:-1]-1
    features=np.array([[ret[i-1],prices[i]/prices[i-20]-1,float(np.std(ret[i-20:i],ddof=1))] for i in range(20,len(rows))])
    if not np.isfinite(features).all():raise ValueError('特征换算超出有效数值范围')
    dates=days[20:]
    results={k:[] for k in NAMES};folds=[];warnings=[];latest={}
    # Anchor folds to the first feature date. Appending test rows never refits a prior fold.
    starts=list(range(lookback,len(features),42))[-6:]
    for start in starts:
        stop=min(start+42,len(features));train=features[start-lookback:start]
        if len(np.unique(train,axis=0))<3:raise ValueError('训练特征变化不足，无法区分三个状态')
        scaler=StandardScaler().fit(train);x=scaler.transform(train)
        cluster=KMeans(n_clusters=3,n_init=10,random_state=17).fit(x)
        order=np.argsort(cluster.cluster_centers_[:,1],kind='stable')
        centers=cluster.cluster_centers_[order]
        assignments=np.argmin(((x[:,None,:]-centers[None,:,:])**2).sum(axis=2),axis=1)
        threshold_states=np.where(train[:,1]>threshold,2,np.where(train[:,1]<-threshold,0,1))
        hmm=fit_hmm(x)
        if not hmm['converged']:warnings.append(dates[start]+' HMM 达到迭代上限，未满足似然变化容差')
        probs={'markov':np.eye(3)[threshold_states],'kmeans':np.eye(3)[assignments],'hmm':hmm['filtered']}
        matrices={'markov':transition_matrix(threshold_states),'kmeans':transition_matrix(assignments),'hmm':hmm['transition']}
        training_means={
            'markov':[[float(v) for v in train[threshold_states==s].mean(axis=0)] if np.any(threshold_states==s) else [None]*3 for s in range(3)],
            'kmeans':scaler.inverse_transform(centers).tolist(),
            'hmm':scaler.inverse_transform(hmm['means']).tolist()}
        baseline_mean=float(train[:,0].mean());baseline_up=float(((train[:,0]>0).sum()+1)/(len(train)+2))
        empirical={}
        for k,p in probs.items():
            counts=p.sum(axis=0)
            empirical[k]=((p.T@train[:,0]+10*baseline_mean)/(counts+10),
                          (p.T@(train[:,0]>0)+10*baseline_up)/(counts+10))
        previous=hmm['filtered'][-1]
        fold={'fold':len(folds)+1,'anchor':start,'train_start':dates[start-lookback],
              'train_end':dates[start-1],'test_start':dates[start],'test_end':dates[stop-1],
              'hmm_converged':hmm['converged'],'hmm_iterations':hmm['iterations'],
              'hmm_training_log_likelihood':hmm['log_likelihood'], 'hmm_seed':hmm['seed'],
              'scaler_mean':scaler.mean_.tolist(),'scaler_scale':scaler.scale_.tolist(),
              'training_state_features':training_means}
        fold['model_parameters']={k:{'transition':matrices[k].tolist(),
            'state_return_means':empirical[k][0].tolist(),'state_up_probabilities':empirical[k][1].tolist()} for k in NAMES}
        fold['model_parameters']['hmm'].update({
            'means':hmm['means'].tolist(),'variances':hmm['variances'].tolist(),
            'initial':hmm['initial'].tolist(),'train_end_filtered':hmm['filtered'][-1].tolist()})
        fold['model_parameters']['kmeans']['centers']=centers.tolist()
        for i in range(start,stop):
            value=scaler.transform(features[i:i+1])[0]
            previous=filter_step(value,hmm,previous)
            state_m=2 if features[i,1]>threshold else 0 if features[i,1]<-threshold else 1
            state_k=int(np.argmin(((centers-value)**2).sum(axis=1)))
            current={'markov':np.eye(3)[state_m],'kmeans':np.eye(3)[state_k],'hmm':previous}
            for k,p in current.items():
                next_p=p@matrices[k]
                mu,up=empirical[k]
                actual=float(ret[i+20]) if i+1<len(features) else None
                record={'date':dates[i],'label_end':dates[i+1] if i+1<len(features) else None,
                        'fold':fold['fold'],'anchor':start,'state':int(np.argmax(p)),
                        'current_probabilities':p.tolist(),'next_state_probabilities':next_p.tolist(),
                        'prediction':float(next_p@mu),'up_probability':float(next_p@up),
                        'actual':actual,'baseline_prediction':baseline_mean,'baseline_up_probability':baseline_up,
                        'train_end':fold['train_end']}
                results[k].append(record)
                latest[k]={'date':dates[i],'current_probabilities':p.tolist(),
                    'next_state_probabilities':next_p.tolist(),'transition':matrices[k].tolist(),
                    'up_probability':record['up_probability'],'prediction':record['prediction'],
                    'training_state_features':training_means[k], 'train_end':fold['train_end']}
        fold['metrics']={k:metrics([r for r in results[k] if r['anchor']==start]) for k in NAMES}
        folds.append(fold)
    return {'asof':end,'first_date':days[0],'last_date':days[-1],'lookback':lookback,'threshold':threshold,
            'states':STATES,'names':NAMES,'folds':folds,'warnings':warnings,'latest':latest,
            'results':{k:{'observations':v,'metrics':metrics(v)} for k,v in results.items()},
            'notes':[
                '特征为当日收益、20 个观测日动量与 20 个单期收益样本波动。标准化、聚类和 HMM 参数只在训练窗拟合；每 42 个信号日重训，展示最近最多六折。末折允许不完整。',
                'HMM 为本地实现的三状态对角高斯模型，两种确定初始化按训练似然选择。训练使用前向后向 EM；测试与最新状态仅使用前向过滤，不平滑回写，不使用 Viterbi 回看最优路径。',
                'KMeans / HMM 按训练状态中心的 20 日动量排序；阈值马尔可夫按同一动量的固定阈值划分。标签仅是特征分组，不是经验证的牛熊真值；高波动状态未必对应弱势。',
                '此处阈值马尔可夫在每折训练窗估计并冻结转移矩阵，与上方持续扩展计数的主图口径不同。三种模型只在当前测试特征上更新状态，测试期间不重估参数。',
                '马尔可夫和聚类转移计数各加 0.5 平滑；HMM 的初始和转移计数也加 0.5，对角方差下限为标准化空间 0.001。局部 EM 不保证全局最优，迭代上限及收敛状态逐折披露。',
                '下一日状态分布来自当前状态分布 × 转移矩阵。用训练状态的当日收益均值/上涨频率映射为下一日收益和上涨事件概率，向训练无条件基线收缩 10 个观测权重。它不是直接把状态概率当作涨跌概率，也不保证已校准。',
                '训练上涨基线为 (上涨次数+1)/(训练数+2)。Brier 分数和 MAE 越低越好；可靠性图以样本外预测分箱与实际上涨频率比较。缺少后续收盘的最新一行只作预测，不计评估。',
                '测试逐日标签为下一观测日收盘收益，末折未完成标签保留为空；不合成可交易净值，不计费用或成交约束。状态切换数包含跨折重新拟合造成的切换。',
                '这是单标的时间序列，不代表全市场状态；使用当前修订的复权行情，不是严格 PIT。缺失日线会改变观测间隔；预测和状态稳定不保证未来有效，合成演示不能证明投资价值。']}
