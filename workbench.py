"""Market, finance, events, screening, experiments, paper ledger and diagnostics."""
import json,math,statistics,random,sqlite3,threading,time
import requests
from contextlib import contextmanager
from datetime import date,datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from extensions import get_json
from research import indicators,backtest,metrics
from model import analyze

DB_LOCK=threading.RLock()
SNAPSHOT={}
@contextmanager
def db(path):
    con=sqlite3.connect(path)
    con.execute('CREATE TABLE IF NOT EXISTS watchlists(name TEXT PRIMARY KEY,codes TEXT,created_at TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS paper(id INTEGER PRIMARY KEY,code TEXT,day TEXT,side TEXT,quantity INTEGER,price REAL,fee REAL,note TEXT)')
    try:
        with con:yield con
    finally:con.close()

def watchlist(path,name=None,codes=None):
    with DB_LOCK,db(path) as con:
        if name is not None:
            if not 1<=len(name.strip())<=40 or not codes or len(codes)>8 or len(set(codes))!=len(codes):raise ValueError('名称 1–40 字，自选池含 1–8 个不重复代码')
            con.execute('INSERT INTO watchlists VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET codes=excluded.codes',
                        (name.strip(),json.dumps(codes),datetime.now().isoformat(timespec='seconds')))
        return [{'name':r[0],'codes':json.loads(r[1]),'created_at':r[2]} for r in con.execute('SELECT * FROM watchlists ORDER BY name')]

def snapshot(is_demo=False):
    if is_demo:
        rng=random.Random(64)
        rows=[{'code':f'{600000+i:06}','name':f'演示 {i+1}','change':rng.gauss(0,3),'amount':rng.uniform(1e7,2e9),'timestamp':None} for i in range(500)]
        total=len(rows);warnings=[];stamp='合成快照 · 非真实市场'
    else:
        if SNAPSHOT.get('value') and time.time()-SNAPSHOT['time']<180:return SNAPSHOT['value']
        params={'pz':100,'po':0,'np':1,'fltt':2,'invt':2,'fid':'f12','fs':'m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23','fields':'f2,f3,f6,f12,f14,f124'}
        def page(n):
            query={'pn':n,'pz':6000,'po':1,'np':1,'fltt':2,'invt':2,'fid':'f12','fs':params['fs'],'fields':'f2,f3,f6,f12,f14,f124,f104,f105'}
            error=None;d={}
            for host in ('82.push2.eastmoney.com','push2.eastmoney.com'):
                try:
                    response=requests.get('https://'+host+'/api/qt/clist/get',params=query,timeout=8)
                    response.raise_for_status();d=response.json().get('data') or {}
                    if isinstance(d.get('diff'),list):break
                except (requests.RequestException,ValueError) as exc:error=exc
            if not d and error:raise ValueError('市场快照源暂不可用：'+type(error).__name__)
            if not isinstance(d.get('diff'),list):raise ValueError('市场快照格式错误')
            return d
        source='东方财富 · 沪深 A 股';page_size=100
        try:first=page(1)
        except (ValueError,requests.RequestException):
            base='https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
            count=requests.get(base+'Market_Center.getHQNodeStockCount',params={'node':'hs_a'},timeout=8);count.raise_for_status();native_total=int(count.json())
            source='新浪备源 · A 股（包含返回的北交所样本）';page_size=80
            def page(n):
                r=requests.get(base+'Market_Center.getHQNodeData',params={'page':n,'num':80,'sort':'symbol','asc':1,'node':'hs_a','symbol':'','_s_r_a':'page'},timeout=8);r.raise_for_status();raw=r.json()
                if not isinstance(raw,list):raise ValueError('新浪快照格式异常')
                mapped=[]
                for x in raw:
                    try:mapped.append({'f12':x.get('code'),'f14':x.get('name'),'f3':float(x['changepercent']),'f6':float(x['amount']),'f124':None})
                    except (ValueError,TypeError,KeyError):continue
                return {'total':native_total,'diff':mapped}
            first=page(1)
        total=int(first.get('total',0))
        if not 1<=total<=15000:raise ValueError('市场数量异常')
        pages=math.ceil(total/page_size);raw=first['diff'];warnings=[];deadline=time.monotonic()+45
        def safe(n):
            if time.monotonic()>deadline:return []
            try:return page(n)['diff']
            except Exception:return []
        with ThreadPoolExecutor(max_workers=4) as ex:
            for result in ex.map(safe,range(2,pages+1)):raw.extend(result)
        unique={str(r.get('f12')):r for r in raw};rows=[]
        for code,r in unique.items():
            if not isinstance(r.get('f3'),(int,float)):continue
            rows.append({'code':code,'name':r.get('f14',code),'change':r['f3'],'amount':r.get('f6') if isinstance(r.get('f6'),(int,float)) else 0,'timestamp':r.get('f124')})
        if len(rows)<total:warnings.append('数据不完整或有无报价证券，涨跌统计仅覆盖返回的有效样本')
        stamps=[r['timestamp'] for r in rows if isinstance(r['timestamp'],(int,float))]
        stamp=datetime.fromtimestamp(max(stamps),timezone(timedelta(hours=8))).isoformat() if stamps else '日期未核验；抓取于 '+datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
        warnings.append('来源：'+source)
        if not stamps:warnings.append('备源仅提供时分秒，未核验行情所属日期；不得当作已确认的当日快照')
    edges=[-100,-10,-5,-2,0,2,5,10,100];counts=[0]*8
    for r in rows:
        for i in range(8):
            if edges[i]<=r['change']<edges[i+1]:counts[i]+=1;break
    result={'rows':sorted(rows,key=lambda r:r['amount'],reverse=True)[:80], 'total':total,'valid':len(rows),
        'breadth':[sum(r['change']>0 for r in rows),sum(r['change']==0 for r in rows),sum(r['change']<0 for r in rows)],
        'distribution':counts,'bins':['<-10%','-10~-5%','-5~-2%','-2~0%','0~2%','2~5%','5~10%','≥10%'],
        'turnover':sum(r['amount'] for r in rows),'timestamp':stamp,'warnings':warnings,'demo':is_demo,
        'note':'独立获取的 A 股快照，不随历史回放日期改变。主源沪深，新浪备源可能含北交所；以来源提示为准。分页可能跨时点，非严格同时快照；按代码去重，仅统计有效涨幅。热力图为成交额靠前的 80 个样本；涨幅区间不等同涨跌停数量。'}
    if not is_demo:SNAPSHOT.update(value=result,time=time.time())
    return result

ETF_CODES=['512480','512800','512010','512660','512690','512170','512980','515790']
def etf_history(code,end):
    if code not in ETF_CODES:raise ValueError('行业代理代码不在预设列表')
    symbol='sh'+code
    d=get_json('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',{'param':f'{symbol},day,{(date.fromisoformat(end)-timedelta(days=730)).isoformat()},,640,hfq'}).get('data',{}).get(symbol,{})
    rows=[{'date':r[0],'close':float(r[2])} for r in d.get('hfqday',[]) if r[0]<=end]
    name=(d.get('qt',{}).get(symbol) or ['',code])[1]
    if len(rows)<80:raise ValueError(code+' 行业 ETF 历史不足')
    return name,rows

def rotation(series,names,end):
    maps={k:{r['date']:r['close'] for r in v if r['date']<=end} for k,v in series.items()}
    days=sorted(set.intersection(*(set(v) for v in maps.values())))
    if len(days)<80:raise ValueError('至少需要 80 个共同日线')
    matrix=[];paths=[]
    prices={k:[m[d] for d in days] for k,m in maps.items()}
    for k,p in prices.items():
        returns=[p[-1]/p[-1-n]-1 for n in (5,20,60)]
        matrix.append({'code':k,'name':names[k],'returns':returns})
        pts=[]
        for i in range(max(25,len(days)-40),len(days)):
            relative=p[i]/p[i-20]-1-statistics.mean(v[i]/v[i-20]-1 for v in prices.values())
            acceleration=(p[i]/p[i-5]-1)-statistics.mean(v[i]/v[i-5]-1 for v in prices.values())
            pts.append({'date':days[i],'x':relative*100,'y':acceleration*100})
        paths.append({'name':names[k],'points':pts})
    equity=[{'name':names[k],'points':[{'date':d,'value':p[i]/p[0]} for i,d in enumerate(days[-120:])]} for k,p0 in prices.items() for p in [p0[-120:]]]
    return {'matrix':matrix,'paths':paths,'lines':equity,'asof':days[-1],
        'note':'使用八只预设行业 ETF 作为行业表现代理，不是纯行业指数或资金流。类别与样本固定选取，存在事后选择和基金存续偏差。轨迹横轴为相对等权代理的 20 日收益，纵轴为相对 5 日收益，非标准 RRG 指标；仅使用截止日以前共同日线。'}

def reports(code,end):
    d=get_json('https://datacenter-web.eastmoney.com/api/data/v1/get',{'reportName':'RPT_LICO_FN_CPD','columns':'ALL','filter':f'(SECURITY_CODE="{code}")(NOTICE_DATE<\'{end}\')','pageSize':60,'sortColumns':'REPORTDATE','sortTypes':'-1'})
    return [r for r in (d.get('result') or {}).get('data',[]) if str(r.get('NOTICE_DATE',''))[:10]<end]

def finance(bars,rows,end):
    rows=[r for r in rows if str(r.get('NOTICE_DATE',''))[:10]<end];periods={str(r['REPORTDATE'])[:10]:r for r in rows}
    def number(r,key):
        v=r.get(key);return float(v) if isinstance(v,(int,float)) and math.isfinite(v) else None
    by_period=sorted(periods.items())[-12:]
    series={'营收（亿元）':[],'净利润（亿元）':[],'每股收益':[],'每股经营现金流':[],'ROE（%）':[]}
    for day,r in by_period:
        for name,key,scale in [('营收（亿元）','TOTAL_OPERATE_INCOME',1e8),('净利润（亿元）','PARENT_NETPROFIT',1e8),('每股收益','BASIC_EPS',1),('每股经营现金流','MGJYXJJE',1),('ROE（%）','WEIGHTAVG_ROE',1)]:
            value=number(r,key)
            if value is not None:series[name].append({'date':day,'value':value/scale})
    valuations=[]
    for b in bars:
        if b['date']>end:continue
        available=[r for r in rows if str(r['NOTICE_DATE'])[:10]<b['date']]
        if not available:continue
        r=max(available,key=lambda r:r['REPORTDATE']);bps=number(r,'BPS');eps=number(r,'BASIC_EPS');period=str(r['REPORTDATE'])[:10]
        ttm=eps if period.endswith('12-31') else None
        if ttm is None and eps is not None:
            year=int(period[:4]);annual=periods.get(f'{year-1}-12-31');prior=periods.get(f'{year-1}{period[4:]}')
            if annual and prior and all(str(v['NOTICE_DATE'])[:10]<b['date'] for v in (annual,prior)):
                a=number(annual,'BASIC_EPS');p=number(prior,'BASIC_EPS')
                if a is not None and p is not None:ttm=a+eps-p
        price=b.get('raw_close',b['close'])
        valuations.append({'date':b['date'],'pb':price/bps if bps and bps>0 else None,'pe':price/ttm if ttm and ttm>0 else None})
    if not by_period:raise ValueError('截止所选日无可用已披露财务报告')
    current=valuations[-1] if valuations else {'pb':None,'pe':None}
    ranks={}
    for k in ('pb','pe'):
        values=[v[k] for v in valuations if v[k] is not None];v=current[k]
        ranks[k]=sum(x<=v for x in values)/len(values) if values and v is not None else None
    return {'series':series,'valuations':valuations[-750:],'current':current,'percentiles':ranks,'asof':end,
        'note':'财报按披露日期过滤，公告当日保守不使用。季度指标多为年初至今累计值，不是单季度值。PE 仅在已披露数据足以构造正的 EPS TTM 时计算；PB 为每股净资产口径。当前修订报告、股本变化与复权差异可能影响历史估值，非严格 PIT；分位仅基于可得有效观测，不能判断必然低估。'}

def screen(series,end,minimum=-1,maximum_vol=1,max_drawdown=-1,trend_only=False):
    rows=[];stages=[len(series),0,0,0,0]
    for code,bars in series.items():
        past=[r for r in bars if r['date']<=end]
        if len(past)<61:continue
        stages[1]+=1;v=indicators(past)[-1];mom=v['momentum20'];vol=v['volatility20'];drawdown=v['drawdown'];trend=past[-1]['close']>v['ma60']
        if mom<minimum:continue
        stages[2]+=1
        if vol>maximum_vol or drawdown<max_drawdown:continue
        stages[3]+=1
        if trend_only and not trend:continue
        stages[4]+=1
        rows.append({'code':code,'momentum':mom,'volatility':vol,'drawdown':drawdown,'trend':trend,'date':past[-1]['date']})
    return {'rows':rows,'stages':stages,'asof':end,'note':'仅筛选当前输入股票池，非全市场无偏选股。阈值基于历史收益和波动描述，回撤起点为已加载历史；保存自选池不会自动下单。'}

def event_calendar(records,manual,end):
    result=[]
    for r in records:
        pub=r.get('published_at','')[:10]
        if not pub or pub>end:continue
        title=r.get('title','');kind='财报' if any(x in title for x in ('季报','季度报告','年报','年度报告','业绩')) else '分红' if any(x in title for x in ('分红','权益分派','利润分配')) else '解禁' if any(x in title for x in ('限售','解禁')) else '公告'
        result.append({'date':pub,'published_at':pub,'kind':kind,'title':title,'url':r.get('url',''),'source':r.get('source','')})
    for r in manual:
        date.fromisoformat(r['date']);date.fromisoformat(r['published_at'])
        if r['published_at']<=end:result.append({**r,'url':'','source':'用户补充（真实性未核验）'})
    counts={}
    for r in result:counts[r['kind']]=counts.get(r['kind'],0)+1
    return {'events':sorted(result,key=lambda r:r['date']),'counts':counts,'asof':end,'note':'自动部分是公告发布日期时间轴，不将发布日期冒充实际除权或解禁日。未来实际事件可由用户补充，只有披露日期不晚于查看日的记录会显示。近期公告接口不是完整历史事件库。'}

def experiments(bars,end,window,threshold,periods,momenta,capital,filtered,code='600519',limit=.1):
    bars=[b for b in bars if b['date']<=end]
    if len(bars)<400:raise ValueError('实验至少需要 400 根日线，预留训练与验证区间')
    if not periods or not momenta or len(periods)*len(momenta)>12 or any(v not in (10,20,30,60,90,120) for v in periods+momenta):raise ValueError('参数限 10/20/30/60/90/120，组合最多 12 个')
    first=max(window+253,121);cut=first+int((len(bars)-first)*.7)
    if len(bars)-cut<30:raise ValueError('样本外区间不足 30 根日线')
    frames=analyze(bars,window,threshold);cells=[];strategy='filtered' if filtered else 'trend';best=None
    for p in periods:
        for m in momenta:
            train=backtest(bars,frames,code,window,end=bars[cut-1]['date'],capital=capital,trend_period=p,momentum_period=m,limit=limit)['results'][strategy]
            score=train['metrics']['return']+.5*train['metrics']['max_drawdown']
            cell={'ma':p,'momentum':m,'train_return':train['metrics']['return'],'train_drawdown':train['metrics']['max_drawdown'],'score':score}
            cells.append(cell)
            if best is None or score>best['score']:best=cell
    # Holdout evaluated only for the training-selected configuration.
    test=backtest(bars,frames,code,window,start=bars[cut]['date'],end=end,capital=capital,trend_period=best['ma'],momentum_period=best['momentum'],limit=limit)
    return {'cells':cells,'best':best,'test':test,'strategy':strategy,'split':bars[cut]['date'],'asof':end,
        'note':'固定 70%/30% 时间切分。仅以训练区间“累计收益＋0.5×最大回撤”选择参数，样本外只评估所选参数。支持均线、动量条件组合及状态过滤。反复查看并调参会污染样本外结果；未进行多重检验校正。交易限制、复权和成本近似与研究回测相同。'}

def audit(histories,end):
    days=sorted(set(b['date'] for h in histories.values() for b in h['bars'] if b['date']<=end));recent=days[-120:];rows=[]
    for code,h in histories.items():
        bars=[b for b in h['bars'] if b['date']<=end];dates=[b['date'] for b in bars];unique=set(dates)
        invalid=sum(not math.isfinite(b['close']) or b['close']<=0 for b in bars)
        bad_ohlc=sum(b.get('raw_low',0)>b.get('raw_high',float('inf')) or not b.get('raw_low',0)<=b.get('raw_close',b['close'])<=b.get('raw_high',float('inf')) for b in bars)
        rows.append({'code':code,'rows':len(bars),'duplicates':len(dates)-len(unique),'invalid':invalid,'ohlc_errors':bad_ohlc,
             'zero_volume':sum(b.get('volume',0)<=0 for b in bars),'last':dates[-1] if dates else None,'source':h.get('source','未知'),
             'fetched_at':h.get('fetched_at'),'stale':h.get('stale',False),'presence':[int(d in unique) for d in recent]})
    return {'rows':rows,'dates':recent,'asof':end,'note':'检查当前规范化数据，不代表已还原供应商原始记录。覆盖图以输入股票日期并集为参照，缺格可能来自停牌、上市时间或缺失，未接入完整交易日历，不直接判为数据错误。历史截止日与最新获取时间分别显示。'}

def ledger(trades,end,capital=300000):
    if not math.isfinite(capital) or capital<=0:raise ValueError('初始资金无效')
    lots={};cash=capital;realized=[];flows=[]
    for t in sorted([t for t in trades if t['day']<=end],key=lambda x:(x['day'],x.get('id',0))):
        qty=t['quantity'];price=t['price'];cost=t['fee'];code=t['code'];day=t['day']
        if not isinstance(qty,int) or qty<=0 or not all(math.isfinite(v) for v in (price,cost)) or price<=0 or cost<0:raise ValueError('模拟交易数值无效')
        if t['side']=='buy':
            minimum=200 if code.startswith('688') else 100
            if qty<minimum or (not code.startswith('688') and qty%100):raise ValueError('买入数量不符合股票最小申报单位')
            value=qty*price+cost
            if value>cash+1e-8:raise ValueError('模拟资金不足')
            cash-=value;lots.setdefault(code,[]).append({'day':day,'qty':qty,'unit_cost':price+cost/qty})
        elif t['side']=='sell':
            eligible=sum(l['qty'] for l in lots.get(code,[]) if l['day']<day)
            if eligible<qty:raise ValueError('T+1 或可卖持仓不足')
            remain=qty;basis=0;holding=0
            for lot in lots.get(code,[]):
                if lot['day']>=day:continue
                n=min(remain,lot['qty']);basis+=n*lot['unit_cost'];holding+=n*(date.fromisoformat(day)-date.fromisoformat(lot['day'])).days;lot['qty']-=n;remain-=n
                if not remain:break
            profit=qty*price-cost-basis;cash+=qty*price-cost
            realized.append({'date':day,'code':code,'profit':profit,'holding_days':holding/qty,'quantity':qty})
        else:raise ValueError('方向应为 buy 或 sell')
        flows.append({'date':day,'cash':cash})
    return {'cash':cash,'positions':{k:sum(l['qty'] for l in v) for k,v in lots.items() if sum(l['qty'] for l in v)>0},'realized':realized,'flows':flows}

def paper(path,end,history_fn,trade=None,capital=300000):
    with DB_LOCK,db(path) as con:
        def records():return [dict(zip(['id','code','day','side','quantity','price','fee','note'],r)) for r in con.execute('SELECT * FROM paper ORDER BY day,id')]
        rows=records()
        if trade:
            date.fromisoformat(trade['day'])
            if trade['day']>end:raise ValueError('不能在当前查看日期之后录入交易')
            bar=next((r for r in history_fn(trade['code'])['bars'] if r['date']==trade['day']),None)
            if bar is None or bar.get('volume',0)<=0:raise ValueError('该股票在所选交易日无有效成交日线，不能录入成交')
            if not bar.get('raw_low',0)-.005<=trade['price']<=bar.get('raw_high',float('inf'))+.005:raise ValueError('成交价格超出该日原始高低价，请核对日期或价格')
            trial={**trade,'id':max([r['id'] for r in rows],default=0)+1}
            ledger(rows+[trial],max([r['day'] for r in rows]+[end]),capital)
            con.execute('INSERT INTO paper(code,day,side,quantity,price,fee,note) VALUES(?,?,?,?,?,?,?)',tuple(trade[k] for k in ('code','day','side','quantity','price','fee','note')))
            rows=records()
        view=[r for r in rows if r['day']<=end];account=ledger(view,end,capital)
        series={code:[b for b in history_fn(code)['bars'] if b['date']<=end] for code in set(t['code'] for t in view)}
        days=sorted(set(b['date'] for v in series.values() for b in v if b['date']>=(view[0]['day'] if view else end)))
        maps={code:{b['date']:b.get('raw_close',b['close']) for b in bars} for code,bars in series.items()};prices={};equity=[];marks=[]
        for day in days:
            state=ledger(view,day,capital)
            for code,m in maps.items():
                if day in m:prices[code]=m[day]
            value=state['cash']+sum(n*prices.get(code,0) for code,n in state['positions'].items());equity.append({'date':day,'value':value})
        for code,qty in account['positions'].items():
            bars=series[code]
            if not bars:raise ValueError(code+' 截止日无估值数据')
            marks.append({'code':code,'quantity':qty,'price':bars[-1].get('raw_close',bars[-1]['close']),'date':bars[-1]['date']})
        return {**account,'trades':view,'equity':equity,'marks':marks,'metrics':metrics(equity,capital) if equity else None,'asof':end,
            'note':'本地手工模拟成交账本，非券商交易。FIFO 计算已卖出委托的已实现盈亏和日历持有天数，限制资金与 T+1；费用由用户录入。估值取不晚于查看日的最近原始收盘价，停牌使用上次价格。未自动处理分红、送转股、税务和外部出入金，遇公司行动需另行核对；初始模拟资金须保持一致。'}
