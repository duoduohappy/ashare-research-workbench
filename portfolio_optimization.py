"""Past-only allocation experiments with fractional adjusted-price units.

These are research portfolios, not exchange-executable A-share orders.
"""
import math
from datetime import date
import numpy as np
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

METHODS = {'equal': '等权基线', 'inverse_vol': '波动倒数',
           'risk_parity': '风险平价（约束近似）', 'min_variance': '受约束最小方差'}


def estimate_covariance(returns, estimator='ledoit_wolf'):
    x = np.asarray(returns, dtype=float)
    if x.ndim != 2 or x.shape[0] < 20 or not 2 <= x.shape[1] <= 8 or not np.isfinite(x).all():
        raise ValueError('协方差估计需要至少 20 行、2–8 列有效收益')
    if estimator == 'ledoit_wolf':
        model = LedoitWolf().fit(x)
        cov, shrinkage = model.covariance_, float(model.shrinkage_)
    elif estimator == 'sample':
        cov, shrinkage = np.cov(x, rowvar=False, ddof=1), None
    else:
        raise ValueError('不支持的协方差估计方法')
    cov = (cov+cov.T)/2
    scale = float(np.trace(cov)/len(cov))
    if scale < 1e-16:
        raise ValueError('训练区间无足够可估计波动，不能构建风险优化组合')
    # An explicit, reported floor handles singular sample covariance and constants.
    floor = max(scale*1e-8, 1e-16)
    minimum = float(np.linalg.eigvalsh(cov)[0])
    jitter = max(0., floor-minimum)
    cov += np.eye(len(cov))*jitter
    return cov, {'estimator': estimator, 'shrinkage': shrinkage, 'diagonal_jitter': jitter,
                 'condition_number': float(np.linalg.cond(cov)), 'samples': len(x)}


def capped_proportions(values, cap):
    """Allocate proportionally with a cap, without breaking the unit budget."""
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError('比例基准必须是正有限数')
    if not math.isfinite(cap) or cap < 1/len(values)-1e-12 or cap > 1:
        raise ValueError('单股上限不可行：股票数 × 上限必须至少为 100%')
    lo, hi = 0., 1/float(values.min())
    for _ in range(80):
        mid = (lo+hi)/2
        if float(np.minimum(cap, mid*values).sum()) > 1:
            hi = mid
        else:
            lo = mid
    return np.minimum(cap, ((lo+hi)/2)*values)


def solve_weights(covariance, method, cap=1.):
    cov = np.asarray(covariance, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1] or not 2 <= len(cov) <= 8:
        raise ValueError('协方差矩阵维度无效')
    if not np.isfinite(cov).all() or not np.allclose(cov,cov.T,atol=1e-12) or np.linalg.eigvalsh(cov)[0] <= 0:
        raise ValueError('优化需要正定、对称的有限协方差矩阵')
    if method not in METHODS:
        raise ValueError('不支持的组合方法')
    n = len(cov)
    equal = capped_proportions(np.ones(n), cap)
    inverse = capped_proportions(1/np.sqrt(np.diag(cov)), cap)
    q = cov/float(np.trace(cov)/n)
    def risk_error(w):
        marginal = q@w
        variance = float(w@marginal)
        rc = w*marginal/variance
        jacobian = (np.diag(marginal)+w[:,None]*q)/variance - (w*marginal)[:,None]*(2*marginal)[None,:]/variance**2
        return float(np.sum((rc-1/n)**2)), 2*(rc-1/n)@jacobian
    if method in ('equal','inverse_vol') or abs(cap-1/n) < 1e-12:
        w = inverse if method == 'inverse_vol' else equal
        status = 'closed_form' if method in ('equal','inverse_vol') else 'unique_feasible_weights'
    else:
        starts = [equal] if method == 'min_variance' else [equal,inverse]
        candidates = []
        for initial in starts:
            objective = (lambda w:(float(w@q@w),2*q@w)) if method == 'min_variance' else risk_error
            result = minimize(objective, initial, jac=True, method='SLSQP', bounds=[(0.,cap)]*n,
                constraints=[{'type':'eq','fun':lambda w:float(w.sum()-1),'jac':lambda w:np.ones(n)}],
                options={'ftol':1e-12,'maxiter':500})
            if (result.success and np.isfinite(result.x).all() and abs(result.x.sum()-1)<1e-7
                    and result.x.min()>=-1e-9 and result.x.max()<=cap+1e-9):
                candidates.append(result)
        if not candidates:
            raise ValueError('组合优化未收敛；请调整股票池、训练窗口或仓位上限，不会静默替换为其他算法')
        best = min(candidates,key=lambda r:r.fun)
        w = np.maximum(0.,best.x)
        status = 'converged'
    variance = float(w@cov@w)
    contributions = w*(cov@w)/variance
    residual = float(np.max(np.abs(contributions-1/n)))
    return {'weights':w.tolist(),'risk_contributions':contributions.tolist(),
            'forecast_volatility':math.sqrt(variance*252),'risk_parity_residual':residual,
            'equal_risk_achieved':residual<=1e-4, 'solver_status':status,
            'at_cap':[bool(v>=cap-1e-7) for v in w]}


def rebalance(units, cash, prices, target, cost_rate):
    """Self-financing proportional-cost trade; both buys and sells incur costs."""
    units, prices, target = (np.asarray(v,dtype=float) for v in (units,prices,target))
    if (units.ndim!=1 or prices.shape!=units.shape or target.shape!=units.shape
            or not np.isfinite([*units,*prices,*target,cash,cost_rate]).all()
            or np.any(units<0) or np.any(prices<=0) or np.any(target<0)
            or abs(target.sum()-1)>1e-7 or cash < -1e-9 or not 0<=cost_rate<=.01):
        raise ValueError('调仓输入、资金或成本无效')
    held = units*prices
    before = float(held.sum()+cash)
    if before<=0:raise ValueError('调仓前净资产须为正')
    lo, hi = 0.,before
    for _ in range(70):
        after = (lo+hi)/2
        cost = cost_rate*float(np.abs(target*after-held).sum())
        if after+cost>before:hi=after
        else:lo=after
    after=(lo+hi)/2
    traded=float(np.abs(target*after-held).sum())
    cost=traded*cost_rate
    new_units=target*after/prices
    new_cash=before-cost-float((new_units*prices).sum())
    if abs(new_cash)>max(1e-8,before*1e-10):raise ValueError('调仓资金核对失败')
    return new_units,max(0.,new_cash),{'nav_before':before,'nav_after':after,'traded_notional':traded,
        'gross_turnover':traded/before,'cost':cost,'cost_rate':cost_rate}


def portfolio_experiment(series,end,start='',lookback=126,interval=21,cap=.5,cost_bps=10.,capital=300000.,estimator='ledoit_wolf'):
    date.fromisoformat(end)
    if start:date.fromisoformat(start)
    if start and start>end:raise ValueError('样本外起点不能晚于查看日期')
    if type(lookback) is not int or lookback not in (63,126,252) or type(interval) is not int or interval not in (5,21,63):
        raise ValueError('训练窗口仅支持 63/126/252，调仓间隔仅支持 5/21/63 个共同观测日')
    if (not isinstance(series,dict) or not 2<=len(series)<=8 or
            any(not math.isfinite(v) for v in (cap,cost_bps,capital)) or
            not 1/len(series)-1e-12<=cap<=1 or not 0<=cost_bps<=100 or not 1000<=capital<=1e9):
        raise ValueError('请输入 2–8 只股票、可行仓位上限、0–100 bp 成本和 1000–10 亿初始资金')
    codes=sorted(series)
    maps={}
    for c in codes:
        rows=[b for b in series[c] if b['date']<=end]
        days=[b['date'] for b in rows]
        if days!=sorted(set(days)):raise ValueError(c+' 日线日期须递增且不重复')
        for b in rows:
            date.fromisoformat(b['date'])
            for key in ('close','raw_open','raw_close'):
                if not isinstance(b.get(key),(int,float)) or not math.isfinite(b[key]) or b[key]<=0:
                    raise ValueError(c+' 缺少有效复权收盘、原始开盘或原始收盘价')
        maps[c]={b['date']:b for b in rows}
    days=sorted(set.intersection(*(set(m) for m in maps.values())))
    if len(days)<lookback+23:raise ValueError('共同历史不足：需训练窗口 + 至少 22 个样本外观测日 + 1 个基准收盘')
    first=next((i for i,d in enumerate(days) if d>=start),len(days)) if start else lookback+1
    if first<lookback+1:raise ValueError('样本外起点之前没有足够训练历史，请推迟起点或缩短训练窗口')
    if len(days)-first<22:raise ValueError('至少需要 22 个样本外共同观测日')
    close=np.array([[maps[c][d]['close'] for c in codes] for d in days],dtype=float)
    opens=np.array([[maps[c][d]['raw_open']*maps[c][d]['close']/maps[c][d]['raw_close'] for c in codes] for d in days],dtype=float)
    returns=close[1:]/close[:-1]-1
    if not np.isfinite(opens).all() or not np.isfinite(returns).all() or np.any(opens<=0):
        raise ValueError('复权开盘或收益换算超出有效数值范围')
    accounts={m:{'units':np.zeros(len(codes)),'cash':float(capital),'equity':[], 'trades':[], 'costs':0.} for m in METHODS}
    schedule=[]
    for i in range(first,len(days)):
        if (i-first)%interval==0:
            cov,meta=estimate_covariance(returns[i-lookback-1:i-1],estimator)
            fits={m:solve_weights(cov,m,cap) for m in METHODS}
            event={'signal_date':days[i-1],'execution_date':days[i], 'train_start':days[i-lookback-1],
                   'train_end':days[i-1], 'training_returns':lookback, 'covariance':meta,'methods':fits}
            schedule.append(event)
            for m,fit in fits.items():
                a=accounts[m]
                a['units'],a['cash'],trade=rebalance(a['units'],a['cash'],opens[i],fit['weights'],cost_bps/10000)
                a['costs']+=trade['cost']
                a['trades'].append({'date':days[i], 'signal_date':days[i-1], **trade,
                    'target_weights':fit['weights'], 'cumulative_cost':a['costs']})
        for a in accounts.values():
            value=float(a['units']@close[i]+a['cash'])
            a['equity'].append({'date':days[i],'value':value/capital})
    from research import metrics
    results={}
    for m,a in accounts.items():
        # Include a real pre-execution initial value, so first costs count in drawdown.
        equity=[{'date':days[first-1],'value':1.},*a['equity']]
        peak=1.;drawdown=[]
        for p in equity:
            peak=max(peak,p['value'])
            drawdown.append({'date':p['date'],'value':p['value']/peak-1})
        results[m]={'name':METHODS[m],'equity':equity,'drawdown':drawdown,
            'metrics':metrics(equity,1.),'trades':a['trades'],'total_cost':a['costs'],
            'gross_turnover':sum(r['gross_turnover'] for r in a['trades']),
            'current_weights':(a['units']*close[-1]/(equity[-1]['value']*capital)).tolist(),
            'cash_weight':a['cash']/(equity[-1]['value']*capital)}
    cov,meta=estimate_covariance(returns[-lookback:],estimator)
    latest={m:solve_weights(cov,m,cap) for m in METHODS}
    std=np.sqrt(np.diag(cov));corr=cov/np.outer(std,std)
    return {'asof':end,'codes':codes,'common_start':days[0],'common_end':days[-1], 'common_rows':len(days),
        'start':days[first],'end':days[-1],'observations':len(days)-first,
        'config':{'lookback':lookback,'interval':interval,'cap':cap,'cost_bps':cost_bps,'capital':capital,'estimator':estimator},
        'results':results,'schedule':schedule,
        'latest':{'signal_date':days[-1],'train_start':days[-lookback-1],'covariance':meta,
                  'correlation':corr.tolist(),'allocations':latest,'execution_date':None},
        'notes':[
            '四种方法使用同一历史窗口、调仓日期和成本口径。仅训练期估计协方差，不用未来收益选择算法；多次挑选参数仍会引入研究者偏差。',
            '日 t 收盘估计权重，下一共同观测日开盘调仓。开盘价按当日复权因子换算，用连续股数研究，不是可执行 A 股成交回测；未模拟整手、T+1、停牌封板、容量及真实公司行动。',
            '成本是买卖双向按成交额乘指定 bp 的情景假设，包含首次建仓；不是券商收费或税费计算。调仓后预算扣除成本再分配，调仓间持仓自然漂移。',
            '完全投资、只做多、无杠杆；仓位上限仅约束调仓目标，市场波动后实际权重可能超过上限。等权与波动倒数同样受上限约束。',
            '风险平价最小化风险贡献与等分预算的平方偏差，使用完整协方差与两个确定起点的局部优化。约束下未必精确均分，残差和是否达到等风险阈值单独披露，不保证全局最优。',
            'Ledoit–Wolf 向均匀对角目标收缩；样本协方差与收缩估计均披露对角正则、条件数。最小方差使用约束优化，不能保证未来风险最小。',
            '最新目标只使用最后已知收盘，用于下一可用开盘的研究参考，未在本次历史净值中执行。它与历史账户当前漂移权重分别展示。',
            '股票池是手动选定的少量现存股票，有幸存者偏差，无行业分散保证。日线取共同日期交集，不填充缺失；一个观测步可能跨多日，252 日年化存在近似。',
            '公共数据是当前修订版本，不是严格 PIT；净值包含复权经济单位的再投资近似。合成数据只能用于演示和程序验证，不能证明投资有效性。']}
