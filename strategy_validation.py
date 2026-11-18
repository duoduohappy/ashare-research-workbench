"""Rolling independent-account strategy validation with frozen train selection."""
import math
from datetime import date
import numpy as np
from model import analyze
from research import backtest


def paired_returns(equity,initial):
    values=np.array([initial,*[p['value'] for p in equity]],dtype=float)
    return values[1:]/values[:-1]-1


def block_bootstrap(fold_differences,block=5,replicates=500,seed=42):
    if type(block) is not int or not 1<=block<=20 or type(replicates) is not int or not 100<=replicates<=2000:
        raise ValueError('重采样区块或次数无效')
    arrays=[np.asarray(v,dtype=float) for v in fold_differences]
    if not arrays or any(a.ndim!=1 or len(a)<block or not np.isfinite(a).all() for a in arrays):
        raise ValueError('每折须有足够且有效的配对收益差')
    rng=np.random.default_rng(seed);samples=[]
    for _ in range(replicates):
        total=0.;count=0
        for a in arrays:
            starts=rng.integers(0,len(a)-block+1,size=math.ceil(len(a)/block))
            resampled=np.concatenate([a[s:s+block] for s in starts])[:len(a)]
            total+=float(resampled.sum());count+=len(a)
        samples.append(total/count)
    counts,edges=np.histogram(samples,bins=15)
    return {'block_length':block,'replicates':replicates,'seed':seed,
            'mean_daily_excess':float(np.concatenate(arrays).mean()),
            'interval':np.quantile(samples,[.025,.5,.975]).tolist(),
            'samples':samples,'histogram':{'counts':counts.tolist(),'edges':edges.tolist()}}


def strategy_validation(bars,end,code,window=20,threshold=.05,lookback=126,periods=None,momenta=None,capital=300000.,filtered=True,limit=.1):
    date.fromisoformat(end)
    if type(lookback) is not int or lookback not in (126,252):raise ValueError('训练窗口仅支持 126 或 252 个观测日')
    if type(window) is not int or not 5<=window<=120 or not math.isfinite(threshold) or not .001<=threshold<=.5:
        raise ValueError('状态参数无效')
    if not isinstance(filtered,bool):raise ValueError('状态过滤标记须为布尔值')
    if not math.isfinite(capital) or not 1000<=capital<=1e9 or limit not in (.05,.1,.2):raise ValueError('资金或涨跌幅假设无效')
    periods=[20,60,120] if periods is None else periods
    momenta=[10,20,60] if momenta is None else momenta
    for values in (periods,momenta):
        if (not isinstance(values,list) or not values or any(type(v) is not int or v not in (10,20,30,60,90,120) for v in values)
                or len(values)!=len(set(values))):raise ValueError('均线/动量限不重复的 10/20/30/60/90/120')
    if len(periods)*len(momenta)>9:raise ValueError('候选参数组合最多九个')
    rows=[b for b in bars if b['date']<=end]
    days=[b['date'] for b in rows]
    if days!=sorted(set(days)):raise ValueError('日线日期须递增且不重复')
    for b in rows:
        date.fromisoformat(b['date'])
        for k in ('close','raw_open','raw_close','raw_high','raw_low','volume'):
            v=b.get(k)
            if not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or (k!='volume' and v==0):
                raise ValueError('日线缺少有效复权价格、原始 OHLC 或成交量')
    warmup=max(window+253,max(periods)+1,max(momenta)+1)
    first=warmup+lookback;test_size=63
    starts=list(range(first,len(rows)-test_size+1,test_size))[-4:]
    if len(starts)<2:raise ValueError(f'至少需要 {first+126} 根日线，包含预热、训练和两折各 63 日测试')
    frames=analyze(rows,window,threshold);strategy='filtered' if filtered else 'trend'
    pairs=sorted((ma,mom) for ma in periods for mom in momenta)
    folds=[];diffs=[]
    stress_keys=[(commission,slip) for commission in (3,6) for slip in (0,10,30)]
    for anchor in starts:
        train_start=anchor-lookback;test_end=anchor+test_size-1
        def run(ma,mom,start,stop,commission=3,slip=10,lag=1):
            return backtest(rows[:stop+1],frames[:stop+1],code,window,
                start=days[start],end=days[stop],capital=capital,commission=commission/10000,
                min_fee=5,slippage=slip/10000,limit=limit,trend_period=ma,momentum_period=mom,signal_lag=lag)
        cells=[]
        for ma,mom in pairs:
            r=run(ma,mom,train_start,anchor-1)['results'][strategy]
            score=r['metrics']['return']+.5*r['metrics']['max_drawdown']
            cells.append({'ma':ma,'momentum':mom,'return':r['metrics']['return'],
                'drawdown':r['metrics']['max_drawdown'],'score':score,'trades':len(r['trades'])})
        # Sorted iteration is the explicit, deterministic tie break; never inspect test ranking.
        chosen=max(cells,key=lambda c:c['score']);ma,mom=chosen['ma'],chosen['momentum']
        test=run(ma,mom,anchor,test_end)
        selected=test['results'][strategy];hold=test['results']['hold']
        differences=paired_returns(selected['equity'],capital)-paired_returns(hold['equity'],capital)
        diffs.append(differences)
        stress=[]
        for commission,slip in stress_keys:
            r=test if (commission,slip)==(3,10) else run(ma,mom,anchor,test_end,commission,slip)
            sr=r['results'][strategy];hr=r['results']['hold']
            stress.append({'commission_bps':commission,'slippage_bps':slip,
                'return':sr['metrics']['return'],'hold_return':hr['metrics']['return'],
                'drawdown':sr['metrics']['max_drawdown'],'trades':len(sr['trades']),'fees':sr['fees']})
        delayed=run(ma,mom,anchor,test_end,lag=2)
        folds.append({'fold':len(folds)+1,'anchor':anchor,'train_start':days[train_start],'train_end':days[anchor-1],
            'test_start':days[anchor],'test_end':days[test_end],'cells':cells,'selected':chosen,
            'test':test,'stress':stress,'delayed':delayed,'paired_daily_excess':differences.tolist()})
    stress_summary=[]
    for commission,slip in stress_keys:
        samples=[next(r for r in f['stress'] if r['commission_bps']==commission and r['slippage_bps']==slip) for f in folds]
        stress_summary.append({'commission_bps':commission,'slippage_bps':slip,
            'mean_fold_return':float(np.mean([r['return'] for r in samples])),
            'mean_fold_excess':float(np.mean([r['return']-r['hold_return'] for r in samples]))})
    chosen_returns=[f['test']['results'][strategy]['metrics']['return'] for f in folds]
    return {'asof':end,'code':code,'strategy':strategy,'lookback':lookback,'test_size':test_size,
        'window':window,'threshold':threshold,'capital':capital,'limit':limit,'periods':sorted(periods),'momenta':sorted(momenta),
        'folds':folds,'stress_summary':stress_summary,'bootstrap':block_bootstrap(diffs),
        'summary':{'folds':len(folds),'test_observations':len(folds)*test_size,
            'mean_fold_return':float(np.mean(chosen_returns)),'median_fold_return':float(np.median(chosen_returns)),
            'worst_fold_return':min(chosen_returns),
            'selection_counts':[{'ma':ma,'momentum':mom,'count':sum(f['selected']['ma']==ma and f['selected']['momentum']==mom for f in folds)} for ma,mom in pairs]},
        'evaluated_start':folds[0]['test_start'],'evaluated_end':folds[-1]['test_end'],
        'tail_observations':len(rows)-(starts[-1]+test_size),
        'notes':[
            '每折以训练收益 + 0.5 × 最大回撤（负数）选参数；分数并列按较小 MA、再较小动量周期选择。样本外只评估训练所选参数，不展示测试期参数排行榜。',
            '训练窗 126/252 个观测日，测试窗固定 63 日，锚定到固定预热起点；只展示最近最多四个完整测试窗，至少两折。尾部不足 63 日不纳入评估。',
            '各训练及测试账户分别从初始资金开始，测试末持仓不强平。单折净值可比较，折间不拼接为连续账户，也不复合单折收益。统计为单折均值/中位数，不是组合年化收益。',
            '基础成本固定佣金每侧 3 bp、最低五元、滑点每侧 10 bp，另计既有引擎按日期估计的税费。压力网格只改变佣金与滑点，参数保持训练选择不变，不重新选优。',
            '信号延迟压力使用两日前收盘形成的均线、动量和状态信号，代替基础的一日前信号；执行日、涨跌停参考价、费用仍取当日数据。它是操作延迟情景，不是更真实成交保证。',
            '配对收益为各独立测试账户的每日策略收益减买入持有收益，首日包含建仓成本。每折内部做长度 5 的非循环移动区块重采样，各折不互相跨接，固定种子 42、500 次。',
            '95% 重采样区间仅描述固定已选策略和已有时期的平均单期超额收益不确定性，不重训、不修正候选选择或多重检验，不证明存在稳定 alpha。区间含零时不能据此确认优于持有；即使不含零也不能保证未来有效。',
            '参数稳定图仅来自训练窗，所选频次仅四折以内，不能当作参数普适性证据。参数、股票和观察时期被反复人工选择仍会污染样本外。',
            '复用已有整手、T+1、开盘涨跌停保守阻断及日期费用近似；未补齐历史 ST/IPO、盘口排队、容量、真实公司行动和分红税。当前修订行情不等于严格 PIT；合成数据只验证程序路径。']}
