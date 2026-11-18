"""Past-only indicators and daily, long-only research execution simulator."""
import math
import statistics
from decimal import Decimal, ROUND_HALF_UP

def indicators(bars):
    peak=0
    result=[]
    for i,b in enumerate(bars):
        c=b['close'];peak=max(peak,c)
        rets=[bars[j]['close']/bars[j-1]['close']-1 for j in range(max(1,i-19),i+1)]
        vols=[x.get('volume',0) for x in bars[max(0,i-20):i]]
        base=statistics.mean(vols) if len(vols)==20 else 0
        trail=[x['close'] for x in bars[max(0,i-19):i+1]]
        sd=statistics.stdev(trail) if len(trail)==20 else None
        prior=[x['close'] for x in bars[max(0,i-20):i]]
        result.append({'ma20':statistics.mean(x['close'] for x in bars[i-19:i+1]) if i>=19 else None,
            'zscore20':(c-statistics.mean(trail))/sd if sd and sd>0 else None,
            'breakout20':(1 if c>max(prior) else -1 if c<min(prior) else 0) if len(prior)==20 else None,
            'ma60':statistics.mean(x['close'] for x in bars[i-59:i+1]) if i>=59 else None,
            'momentum20':c/bars[i-20]['close']-1 if i>=20 else None,
            'volatility20':statistics.stdev(rets)*math.sqrt(252) if len(rets)==20 else None,
            'drawdown':c/peak-1,
            'volume_ratio':b.get('volume',0)/base if base>0 else None,
            'turnover':b.get('raw_close',c)*b.get('volume',0)*100})
    return result

def stamp_rate(day):
    return .0005 if day>='2023-08-28' else .001

def transfer_rate(day):
    return .00001 if day>='2022-04-29' else .00002

def fee(value,day,sell,commission,min_fee):
    return max(min_fee,value*commission)+value*transfer_rate(day)+(value*stamp_rate(day) if sell else 0)

def rounded_price(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def metrics(equity,initial):
    peak=initial;dd=0;rets=[];prev=initial
    for point in equity:
        val=point['value'];peak=max(peak,val);dd=min(dd,val/peak-1)
        rets.append(val/prev-1);prev=val
    if equity and 'date' in equity[0]:
        from datetime import date
        years=((date.fromisoformat(equity[-1]['date'])-date.fromisoformat(equity[0]['date'])).days+1)/365.25
    else:
        years=len(equity)/252
    vol=statistics.stdev(rets)*math.sqrt(252) if len(rets)>1 else None
    return {'return':prev/initial-1,'annual_return':(prev/initial)**(1/years)-1 if years else None,
            'max_drawdown':dd,'volatility':vol,
            'sharpe':statistics.mean(rets)*252/vol if vol and vol>0 else None}

def backtest(bars,frames,code,window=20,start='',end='',capital=100000,commission=.0003,min_fee=5,slippage=.001,limit=.1,trend_period=60,momentum_period=20,signal_lag=1):
    if type(signal_lag) is not int or signal_lag not in (1,2):raise ValueError('信号滞后仅支持 1 或 2 个观测日')
    if not 5<=trend_period<=120 or not 5<=momentum_period<=120:raise ValueError('均线和动量周期应在 5–120 之间')
    for v in (capital,commission,min_fee,slippage,limit):
        if not math.isfinite(v):raise ValueError('回测参数必须为有限数字')
    if not 1000<=capital<=1e9 or not 0<=commission<=.01 or not 0<=min_fee<=100 or not 0<=slippage<=.03 or limit not in (.05,.1,.2):
        raise ValueError('回测资金或费用参数超出范围')
    if start and end and start>end:raise ValueError('回测起点不能晚于终点')
    first=max(window+252+signal_lag,trend_period+signal_lag,momentum_period+signal_lag)
    selected=[i for i in range(first,len(bars)) if (not start or bars[i]['date']>=start) and (not end or bars[i]['date']<=end)]
    if len(selected)<2:raise ValueError('回测区间不足：需要至少 252 个历史转移样本及两个回测交易日')
    if any(not all(k in bars[i] for k in ('raw_open','raw_close','raw_high','raw_low','volume')) for i in range(selected[0]-1,selected[-1]+1)):
        raise ValueError('缓存缺少原始 OHLC 和成交量，请重新加载真实行情后回测')
    minimum,step=(200,1) if code.startswith('688') else (100,100)
    results={}
    for strategy in ('hold','trend','filtered'):
        cash=capital;units=0;buy_day='';eq=[];trades=[];blocked=[];corporate=0
        for i in selected:
            b=bars[i];prev=bars[i-1];day=b['date'];factor=b['close']/b['raw_close'];oldfactor=prev['close']/prev['raw_close']
            changed=abs(factor/oldfactor-1)>.0005
            if changed:corporate+=1
            # Economic units are held in the adjusted price basis. Corporate
            # actions imply reinvestment, not an exact cash-dividend ledger.
            rawshares=units*factor
            signal_index=i-signal_lag;signal_bar=bars[signal_index]
            f=frames[signal_index];average=statistics.mean(x['close'] for x in bars[signal_index-trend_period+1:signal_index+1]);momentum=signal_bar['close']/bars[signal_index-momentum_period]['close']-1
            trend=signal_bar['close']>average and momentum>0
            target=True if strategy=='hold' else trend and (strategy!='filtered' or f['signal']>0)
            action='buy' if target and not units else 'sell' if not target and units else None
            if action:
                reason=None
                if b['volume']<=0:reason='停牌或零成交量'
                # Re-reference ex-right days using adjacent adjustment factors.
                reference=prev['raw_close']*oldfactor/factor
                upper=rounded_price(reference*(1+limit));lower=rounded_price(reference*(1-limit))
                if action=='buy' and b['raw_open']>=upper-.005:reason='开盘涨停：保守不买入'
                if action=='sell' and b['raw_open']<=lower+.005:reason='开盘跌停：保守不卖出'
                if action=='sell' and day<=buy_day:reason='T+1：当日买入不可卖出'
                execution=b['raw_open']*(1+slippage if action=='buy' else 1-slippage)
                execution=min(upper,max(lower,execution))
                if reason:blocked.append({'date':day,'side':action,'reason':reason})
                elif action=='buy':
                    n=math.floor((cash-min_fee)/(execution*(1+commission+transfer_rate(day))))
                    n=(n//step)*step
                    while n>=minimum and n*execution+fee(n*execution,day,False,commission,min_fee)>cash:n-=step
                    if n>=minimum:
                        cost=n*execution;fees=fee(cost,day,False,commission,min_fee)
                        cash-=cost+fees;units=n/factor;buy_day=day
                        trades.append({'date':day,'signal_date':signal_bar['date'],'side':'买入','quantity':n,'price':execution,'fees':fees})
                    else:blocked.append({'date':day,'side':action,'reason':'资金不足最小买入数量'})
                else:
                    value=rawshares*execution;fees=fee(value,day,True,commission,min_fee)
                    cash+=value-fees;units=0
                    trades.append({'date':day,'signal_date':signal_bar['date'],'side':'卖出','quantity':rawshares,'price':execution,'fees':fees})
            eq.append({'date':day,'value':cash+units*b['close']})
        results[strategy]={'equity':eq,'metrics':metrics(eq,capital),'trades':trades,'blocked':blocked,'corporate_events':corporate,
                           'fees':sum(t['fees'] for t in trades),'open_position':units>0}
    return {'results':results,'start':bars[selected[0]]['date'],'end':bars[selected[-1]]['date'],
            'params':{'capital':capital,'commission':commission,'min_fee':min_fee,'slippage':slippage,'limit':limit,'minimum':minimum,'step':step,'signal_lag':signal_lag},
            'caveat':f'研究回测：使用 {signal_lag} 个观测日前的收盘信号、当日开盘成交，只做多或空仓。涨跌停按所选固定比例近似，缺少历史 ST/IPO 特别规则；开盘封板保守跳过。停牌缺行期间不成交，波动和夏普按可得日线 252 年化，长停牌会影响可比性；年化收益按自然日计算。复权隐含红利再投资及等价持股，未逐笔处理分红税和公司行动，不是账户对账收益。期末持仓按收盘估值，不强制卖出。'}
