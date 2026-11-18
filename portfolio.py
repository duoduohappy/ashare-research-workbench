"""Descriptive buy-and-hold basket analysis; no trading simulation."""
import math
import statistics
from research import metrics

def portfolio(histories,weights,start='',end=''):
    if not 2<=len(histories)<=8 or len(weights)!=len(histories):raise ValueError('请配置 2–8 只股票及对应权重')
    if any(not math.isfinite(w) or w<=0 or w>1 for w in weights) or sum(weights)>1.00000001:raise ValueError('各权重必须大于零，合计不能超过 100%，剩余为现金')
    if start and end and start>end:raise ValueError('组合起点不能晚于当前查看日期')
    maps=[{b['date']:b['close'] for b in rows if (not start or b['date']>=start) and (not end or b['date']<=end)} for rows in histories]
    days=sorted(set.intersection(*(set(m) for m in maps)))
    if len(days)<22:raise ValueError('截至所选日期，共同日线不足 22 个交易日，请提前起点或选择更晚的查看日期')
    prices=[[m[d] for d in days] for m in maps]
    cash=max(0,1-sum(weights))
    equity=[{'date':d,'value':cash+sum(w*p[i]/p[0] for w,p in zip(weights,prices))} for i,d in enumerate(days)]
    values=[w*p[-1]/p[0] for w,p in zip(weights,prices)]
    current=[v/equity[-1]['value'] for v in values]
    returns=[[p[i]/p[i-1]-1 for i in range(max(1,len(days)-60),len(days))] for p in prices]
    cov=[[statistics.covariance(a,b)*252 for b in returns] for a in returns]
    vols=[math.sqrt(max(0,cov[i][i])) for i in range(len(weights))]
    variance=sum(current[i]*current[j]*cov[i][j] for i in range(len(weights)) for j in range(len(weights)))
    corr=[[cov[i][j]/(vols[i]*vols[j]) if vols[i]*vols[j]>1e-12 else None for j in range(len(weights))] for i in range(len(weights))]
    contrib=[current[i]*sum(cov[i][j]*current[j] for j in range(len(weights)))/variance if variance>1e-12 else None for i in range(len(weights))]
    inv=[1/v if v>1e-9 else 0 for v in vols]
    refs=[v/sum(inv) for v in inv] if sum(inv)>0 else [None]*len(weights)
    return {'start':days[0],'end':days[-1],'rows':len(days),'equity':equity,'metrics':metrics(equity,1),
            'cash_weight':cash/equity[-1]['value'],'current_weights':current,'target_weights':weights,
            'asset_returns':[p[-1]/p[0]-1 for p in prices], 'volatility':math.sqrt(max(0,variance)),
            'asset_volatility':vols,'correlation':corr,'risk_contributions':contrib,'inverse_volatility_weights':refs,
            'caveat':'组合研究：在共同日线起点按输入权重一次配置，此后不再平衡，剩余权重为无息现金。后复权收益近似，未计费用、整手、涨跌停和分红税，不是成交回测。仅使用截至所选日期的数据；相关性、当前权重风险贡献及波动倒数参考基于最近最多 60 个共同收益观测。缺失日线采用共同日期交集，不前向补值；停牌会影响样本与年化指标。风险贡献可能为负，不代表负的损失风险。'}
