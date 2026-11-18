"""Explicit adapters for a trading calendar and independent raw close checks."""
import json,math,random,subprocess,sys,os
from datetime import date,timedelta,datetime
import requests
from ops_engine import Blocked,now,stamp,gate

def primary_history(code,refresh=True):
    symbol=('sh' if code.startswith('6') else 'sz')+code
    url='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    payloads=[]
    for adjustment in ('qfq',''):
        r=requests.get(url,params={'param':f'{symbol},day,,,640,{adjustment}'},timeout=15);r.raise_for_status();payloads.append(r.json().get('data',{}).get(symbol,{}))
    adjusted=payloads[0].get('qfqday',[]);raw=payloads[1].get('day',[])
    if not adjusted or not raw:raise Blocked('认证日线缺少前复权或原始价格')
    for rows in (adjusted,raw):
        dates=[r[0] for r in rows]
        if dates!=sorted(set(dates)):raise Blocked('认证源存在重复或乱序日期，拒绝静默清洗')
    prices={r[0]:r for r in raw};bars=[]
    for a in adjusted:
        r=prices.get(a[0])
        if r:bars.append({'date':r[0],'close':float(a[2]),'raw_open':float(r[1]),'raw_close':float(r[2]),'raw_high':float(r[3]),'raw_low':float(r[4]),'volume':float(r[5])})
    return {'bars':bars,'fetched_at':stamp(),'stale':False,'source':'腾讯单区间前复权＋原始日线（最近约 640 日，不做年度拼接）'}

def calendar(runtime):
    path=runtime.store/'calendar.json'
    if path.exists():
        try:
            v=json.loads(path.read_text(encoding='utf-8'));age=(now()-datetime.fromisoformat(v['fetched_at'])).total_seconds()
            if 0<=age<7*86400 and v['covered_until']>=now().date().isoformat():return v
        except (ValueError,KeyError):pass
    try:
        # Run the SDK in a bounded helper: a stalled upstream request must not
        # leave the worker permanently stuck while its heartbeat looks healthy.
        code="import akshare as a,json;print(json.dumps([str(d) for d in a.tool_trade_date_hist_sina()['trade_date']]))"
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,encoding='utf-8',timeout=35,check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        days=sorted(set(json.loads(result.stdout)))
        for d in days:date.fromisoformat(d)
        v={'days':days,'covered_until':max(days),'fetched_at':stamp(),'source':'新浪交易日历 / AKShare（非交易所授权日历）'}
        path.write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8');return v
    except Exception as exc:raise Blocked('交易日历不可用，任务停止：'+type(exc).__name__) from exc

def secondary(code,expected):
    symbol=('sh' if code.startswith('6') else 'sz')+code
    r=requests.get('https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData',params={'symbol':symbol,'scale':240,'ma':'no','datalen':1970},timeout=15)
    r.raise_for_status();rows=r.json()
    if not isinstance(rows,list):raise Blocked('独立来源返回格式异常')
    match=next((v for v in rows if str(v.get('day',''))[:10]==expected),None)
    if not match:raise Blocked('独立来源缺少对应收盘日：'+code)
    value=float(match['close'])
    if not math.isfinite(value) or value<=0:raise Blocked('独立来源价格无效')
    return {'date':expected,'close':value,'source':'新浪日线原始收盘','fetched_at':stamp()}

def demo_calendar():
    start=date(2020,1,1);last=date(now().year+1,12,31);days=[]
    while start<=last:
        if start.weekday()<5:days.append(start.isoformat())
        start+=timedelta(days=1)
    return {'days':days,'covered_until':days[-1],'fetched_at':stamp(),'source':'合成工作日日历（未模拟法定休市，仅演示）'}

def demo_history(code,expected):
    rng=random.Random(int(code));start=date(2020,1,1);end=date.fromisoformat(expected);price=15+int(code)%50;rows=[]
    while start<=end:
        if start.weekday()<5:
            opening=round(price*(1+rng.gauss(0,.002)),3);price=round(max(1,price*(1+rng.gauss(.0004,.012))),3)
            rows.append({'date':start.isoformat(),'close':price,'raw_close':price,'raw_open':opening,'raw_high':round(max(price,opening)*1.01,3),'raw_low':round(min(price,opening)*.99,3),'volume':rng.randint(5000,50000)})
        start+=timedelta(days=1)
    return {'bars':rows,'stale':False,'fetched_at':stamp(),'source':'按代码固定随机种子的合成行情；非真实收益'}

def freeze_feeds(runtime,c,asof):
    mode=c['mode'];cal=demo_calendar() if mode=='demo' else (runtime.calendar_loader or (lambda:calendar(runtime)))()
    eligible=[d for d in cal['days'] if d<=asof]
    if not eligible:raise Blocked('截止日没有已核验交易日')
    expected=max(eligible);feeds={};other={};errors=[]
    for code in c['codes']:
        try:
            h=demo_history(code,expected) if mode=='demo' else (runtime.history_loader or primary_history)(code,True)
            h={**h,'bars':[b for b in h['bars'] if b['date']<=expected]}
            feeds[code]=h
            if mode=='live':
                if runtime.quote_loader is None:raise Blocked('未配置证券状态验证器')
                q=runtime.quote_loader(code)
                h['name']=q['name'];h['quote_timestamp']=q.get('timestamp')
                if any(s in q['name'].upper() for s in ('ST','退')):errors.append(code+' 非受支持的普通证券状态')
                other[code]=(runtime.secondary_loader or secondary)(code,expected)
            else:other[code]={'date':expected,'close':h['bars'][-1]['raw_close'],'source':'合成一致性参考（非独立数据源）'}
            feeds[code]=h
        except Exception as exc:
            errors.append(code+' 数据链路失败：'+str(exc)[:300]);feeds.setdefault(code,{'bars':[],'stale':True,'fetched_at':stamp(),'source':'数据不可用'})
    assessment=gate(feeds,cal,asof,mode,secondary=other)
    for error in errors:assessment['checks'].append({'check':'数据链路或证券状态','pass':False,'detail':error})
    assessment['passed']=all(r['pass'] for r in assessment['checks'])
    return {'feeds':feeds,'calendar':cal,'secondary':other,'gate':assessment,'config':c,'asof':asof,'frozen_at':stamp(),
            'limitation':'冻结当前可得修订版本用于后续复现；不能把今天获取的历史数据宣称为当时未修订的 PIT 数据。'}
