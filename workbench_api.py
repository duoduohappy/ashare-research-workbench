import csv,io,random,math
from datetime import date,timedelta
from concurrent.futures import ThreadPoolExecutor
import workbench as w

def dispatch(body,env):
    kind=body['kind'];end=body['end'];demo=body.get('demo') is True;code=body.get('code','600519');env['symbol'](code)
    codes=body.get('codes',[code]);path=env['root']/'workspace.sqlite3';warnings=[]
    if not isinstance(codes,list) or not 1<=len(codes)<=8 or len(set(codes))!=len(codes):raise ValueError('请输入 1–8 个不重复股票代码')
    for c in codes:env['symbol'](c)
    def hist(c):
        if demo:return {**env['demo'](),'source':'合成演示日线','stale':False,'fetched_at':None}
        return env['history'](c)
    if kind=='market':return w.snapshot(demo)
    if kind=='rotation':
        names={};series={}
        if demo:
            for i,c in enumerate(w.ETF_CODES):
                rng=random.Random(int(c));scale=1;rows=env['demo']()['bars']
                for r in rows:scale*=1+rng.gauss(0,.006);r['close']*=scale
                series[c]=rows;names[c]='演示行业 '+str(i+1)
        else:
            def load(c):
                try:return c,w.etf_history(c,end),None
                except Exception as exc:return c,None,type(exc).__name__
            with ThreadPoolExecutor(max_workers=4) as ex:
                for c,value,error in ex.map(load,w.ETF_CODES):
                    if error:warnings.append(c+' 行业代理不可用：'+error)
                    else:names[c],series[c]=value
            if len(series)<2:raise ValueError('可用行业 ETF 少于两只，请检查网络或切换演示')
        result=w.rotation(series,names,end)
    elif kind=='watch':
        if body.get('action')=='save':return {'watchlists':w.watchlist(path,str(body.get('name','')),codes),'saved':True}
        if body.get('action')=='list':return {'watchlists':w.watchlist(path)}
        series={c:hist(c)['bars'] for c in codes}
        thresholds=[float(body.get(k,d)) for k,d in [('min_momentum',-1),('max_volatility',1),('max_drawdown',-1)]]
        if any(not math.isfinite(v) for v in thresholds) or not -1<=thresholds[0]<=5 or not 0<=thresholds[1]<=5 or not -1<=thresholds[2]<=0:raise ValueError('筛选阈值超出范围')
        result=w.screen(series,end,*thresholds,body.get('trend_only') is True);result['watchlists']=w.watchlist(path)
    elif kind=='finance':
        rows=w.reports(code,end) if not demo else []
        if demo:
            rng=random.Random(71)
            for year in range(2022,2026):
                for month,day in [(3,31),(6,30),(9,30),(12,31)]:
                    period=date(year,month,day);pub=period+timedelta(days=30)
                    if pub.isoformat()<end:rows.append({'REPORTDATE':period.isoformat(),'NOTICE_DATE':pub.isoformat(),'BPS':10+year-2022,'BASIC_EPS':month/12*(1+(year-2022)*.1),'TOTAL_OPERATE_INCOME':1e10*month/12*(1+rng.random()),'PARENT_NETPROFIT':1e9*month/12,'WEIGHTAVG_ROE':month/12*12,'MGJYXJJE':month/12*2})
        result=w.finance(hist(code)['bars'],rows,end)
    elif kind=='events':
        records=[]
        if demo:records=[{'published_at':end,'title':'演示：业绩说明会及季度报告','source':'合成事件'}]
        else:
            try:records=env['news'](code,end)
            except Exception as exc:warnings.append('自动公告获取失败：'+type(exc).__name__)
        manual=list(csv.DictReader(io.StringIO(body.get('event_csv','')))) if body.get('event_csv','').strip() else []
        if len(manual)>200:raise ValueError('补充事件最多 200 条')
        for r in manual:
            if not all(r.get(k) for k in ('date','published_at','kind','title')):raise ValueError('事件须含 date,published_at,kind,title')
        result=w.event_calendar(records,manual,end)
        bars=[b for b in hist(code)['bars'] if b['date']<=end];lookup={b['date']:i for i,b in enumerate(bars)};windows=[]
        for e in result['events']:
            i=next((i for i,b in enumerate(bars) if b['date']>=e['date']),None)
            if i is None or i<5 or i+5>=len(bars):continue
            windows.append({'date':e['date'],'title':e['title'],'points':[{'date':str(j-i),'value':bars[j]['close']/bars[i]['close']} for j in range(i-5,i+6)]})
        result['windows']=windows[:12]
        result['note']+=' 事件前后图只显示已有完整前后各 5 个观测日的事件，归一化到事件对应首个交易日；仅作描述，不代表事件因果效应。'
    elif kind=='lab':
        result=w.experiments(hist(code)['bars'],end,int(body.get('window',20)),float(body.get('threshold',.05)),
            [int(x) for x in body.get('periods',[20,60,120])],[int(x) for x in body.get('momenta',[10,20,60])],float(body.get('capital',300000)),body.get('filtered') is True,code,float(body.get('limit',.1)))
    elif kind=='paper':
        if demo:
            rows=env['demo']()['bars'];past=[b for b in rows if b['date']<=end]
            if len(past)<30:raise ValueError('演示复盘至少需要 30 日数据')
            trades=[{'id':1,'code':code,'day':past[-25]['date'],'side':'buy','quantity':200,'price':past[-25]['raw_close'],'fee':5,'note':'演示买入'},
                    {'id':2,'code':code,'day':past[-10]['date'],'side':'sell','quantity':100,'price':past[-10]['raw_close'],'fee':5,'note':'演示卖出'}]
            account=w.ledger(trades,end);equity=[]
            for b in past[-25:]:
                state=w.ledger(trades,b['date']);equity.append({'date':b['date'],'value':state['cash']+sum(state['positions'].values())*b['raw_close']})
            result={**account,'trades':trades,'equity':equity,'metrics':w.metrics(equity,300000),'note':'合成演示复盘，不保存记录。真实模式使用本地手工成交账本。'}
        else:
            trade=body.get('trade') if body.get('action')=='add' else None
            if trade:
                env['symbol'](trade.get('code',''))
                if float(trade['quantity'])!=int(trade['quantity']):raise ValueError('股数必须为整数')
                if len(str(trade.get('note','')))>500:raise ValueError('备注最多 500 字')
                trade={**trade,'quantity':int(trade['quantity']),'price':float(trade['price']),'fee':float(trade['fee'])}
            result=w.paper(path,end,hist,trade)
    elif kind=='quality':
        histories={}
        for c in codes:
            try:histories[c]=hist(c)
            except Exception as exc:warnings.append(c+' 行情不可用：'+type(exc).__name__)
        if not histories:raise ValueError('所有候选行情均不可用')
        result=w.audit(histories,end)
    else:raise ValueError('未知工作台模块')
    return {**result,'demo':demo,'asof':end,'warnings':warnings}
