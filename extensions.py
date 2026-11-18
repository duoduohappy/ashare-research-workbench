"""Research modules. Provider results are data, never executable instructions."""
import json,math,re,statistics,html,random
from datetime import datetime,timedelta
import requests
from research import indicators,fee

def get_json(url,params):
    for attempt in range(2):
        try:
            r=requests.get(url,params=params,timeout=20,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status();return r.json()
        except requests.RequestException:
            if attempt:raise

def financial(code,end):
    d=get_json('https://datacenter-web.eastmoney.com/api/data/v1/get',{'reportName':'RPT_LICO_FN_CPD','columns':'ALL',
      'filter':f'(SECURITY_CODE="{code}")(NOTICE_DATE<\'{end}\')','pageSize':20,'sortColumns':'REPORTDATE','sortTypes':'-1'})
    rows=(d.get('result') or {}).get('data') or []
    rows=[r for r in rows if str(r.get('NOTICE_DATE',''))[:10]<end and str(r.get('REPORTDATE',''))[:10]<=end]
    return rows[0] if rows else {}

def factors(series,reports,end,weights):
    labels=['价值(B/P)','质量(ROE)','成长(营收同比)','红利(参考股息率)','动量(20日)','低波(20日)']
    if len(weights)!=6 or any(not math.isfinite(w) or w<0 for w in weights) or sum(weights)<=0:raise ValueError('六项因子权重应非负，且至少一项大于零')
    rows=[]
    for code,bars in series.items():
        past=[b for b in bars if b['date']<=end]
        if len(past)<61:raise ValueError(code+' 历史不足 61 日')
        b=past[-1];ind=indicators(past)[-1];r=reports.get(code,{})
        if not r.get('NOTICE_DATE') or str(r['NOTICE_DATE'])[:10]>=end:r={}
        def num(k):
            v=r.get(k)
            return float(v) if isinstance(v,(int,float)) and math.isfinite(v) else None
        bps=num('BPS');div=num('dividend_yield')
        values=[bps/b['raw_close'] if bps and bps>0 else None,num('WEIGHTAVG_ROE'),num('YSTZ'),div,ind['momentum20'],-ind['volatility20']]
        rows.append({'code':code,'date':b['date'],'report_date':str(r.get('REPORTDATE',''))[:10],
            'published_at':str(r.get('NOTICE_DATE',''))[:10],'values':values,'scores':[None]*6})
    # Only factors available for every candidate are comparable in a composite.
    usable=[j for j in range(6) if weights[j]>0 and all(r['values'][j] is not None for r in rows)]
    if not usable:raise ValueError('候选股票没有共同可用的已加权因子')
    for j in usable:
        vals=[r['values'][j] for r in rows]
        for r in rows:
            v=r['values'][j];r['scores'][j]=100*(sum(x<v for x in vals)+.5*(sum(x==v for x in vals)-1))/max(1,len(vals)-1)
    for r in rows:r['score']=sum(r['scores'][j]*weights[j] for j in usable)/sum(weights[j] for j in usable)
    return {'rows':sorted(rows,key=lambda r:r['score'],reverse=True),'labels':labels,'used':[labels[j] for j in usable],
      'missing':[labels[j] for j in range(6) if weights[j]>0 and j not in usable], 'asof':end,
      'caveat':'仅比较输入股票池，不是全市场选股。价值用最近已披露每股净资产/未复权价格，质量用累计 ROE，成长用累计营收同比；不同报告期可能不可比。财报公告当日保守排除，当前修订数据不等于原始历史版本。红利需有带披露日期的补充数据；缺失因子不参与所有候选的综合排名，剩余权重归一化。无行业中性化，不代表未来收益。'}

def features(bars,end):
    bars=[b for b in bars if b['date']<=end];ind=indicators(bars);out=[]
    for i in range(60,len(bars)):
        b=bars[i];v=ind[i];x=[b['close']/bars[i-5]['close']-1,v['momentum20'],b['close']/v['ma20']-1,v['volatility20'],v['volume_ratio'] or 0]
        out.append({'date':b['date'],'x':x,'y':bars[i+5]['close']/b['close']-1 if i+5<len(bars) else None,
                    'label_end':bars[i+5]['date'] if i+5<len(bars) else None})
    return out

def machine_learning(series,end,method):
    import numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestRegressor,HistGradientBoostingRegressor
    if method not in ('ridge','forest','boost'):raise ValueError('不支持的模型')
    def model():
        m=Ridge(alpha=10) if method=='ridge' else RandomForestRegressor(n_estimators=60,max_depth=4,min_samples_leaf=15,random_state=42,n_jobs=1) if method=='forest' else HistGradientBoostingRegressor(max_iter=60,max_leaf_nodes=7,l2_regularization=10,random_state=42)
        return make_pipeline(StandardScaler(),m)
    from factor_validation import correlation,mean
    by_code={code:[dict(r,code=code) for r in features(bars,end)] for code,bars in series.items()}
    if any(len(v)<200 for v in by_code.values()):raise ValueError('每只股票至少需要约 260 根已收盘日线')
    pool=[r for vals in by_code.values() for r in vals if r['y'] is not None]
    dates=sorted(set(r['date'] for r in pool));dates=dates[-312:]
    validation=[];folds=[]
    for offset in (60,40,20):
        test_dates=dates[-offset:][:20];start=test_dates[0]
        train=[r for r in pool if r['label_end']<start and r['date']>=dates[max(0,len(dates)-offset-252)]]
        test=[r for r in pool if r['date'] in test_dates]
        if len(train)<100:raise ValueError('隔离未来标签后训练样本不足')
        m=model();m.fit([r['x'] for r in train],[r['y'] for r in train]);pred=m.predict([r['x'] for r in test]);base=statistics.mean(r['y'] for r in train)
        fold_rows=[{'code':r['code'],'fold':len(folds)+1,'date':r['date'],'label_end':r['label_end'],'actual':r['y'],'prediction':float(p),'baseline':base,'train_label_end':max(t['label_end'] for t in train)} for r,p in zip(test,pred)]
        validation.extend(fold_rows)
        day_ic=[]
        for day in test_dates:
            cross=[r for r in fold_rows if r['date']==day]
            day_ic.append({'date':day,'rank_ic':correlation([r['prediction'] for r in cross],[r['actual'] for r in cross],True),'count':len(cross)})
        folds.append({'fold':len(folds)+1,'train_start':min(r['date'] for r in train),'train_end':max(r['date'] for r in train),
            'train_label_end':max(r['label_end'] for r in train),'test_start':test_dates[0],'test_end':test_dates[-1],
            'test_label_end':max(r['label_end'] for r in test),'train_samples':len(train),'test_samples':len(test),
            'mae':mean([abs(r['prediction']-r['actual']) for r in fold_rows]),'baseline_mae':mean([abs(r['baseline']-r['actual']) for r in fold_rows]),
            'mean_rank_ic':mean([r['rank_ic'] for r in day_ic]),'daily_rank_ic':day_ic})
    train=[r for r in pool if r['date']>=dates[-min(252,len(dates))]]
    m=model();m.fit([r['x'] for r in train],[r['y'] for r in train])
    ranks=[]
    for code,rows in by_code.items():
        r=rows[-1];ranks.append({'code':code,'date':r['date'],'prediction':float(m.predict([r['x']])[0])})
    actual=np.array([r['actual'] for r in validation]);pred=np.array([r['prediction'] for r in validation])
    corr=float(np.corrcoef(actual,pred)[0,1]) if actual.std()>1e-10 and pred.std()>1e-10 else None
    return {'asof':end,'method':method,'ranks':sorted(ranks,key=lambda r:r['prediction'],reverse=True),'train_samples':len(train),
        'validation_samples':len(validation),'mae':float(np.mean(abs(actual-pred))),
        'baseline_mae':statistics.mean(abs(r['actual']-r['baseline']) for r in validation),
        'direction_accuracy':float(np.mean((actual>0)==(pred>0))),'correlation':corr,'validation':validation,'folds':folds,
        'caveat':'预测目标为未来 5 个观测日收益，非概率。仅用价格、动量、波动、成交量等 5 项特征；最近 60 个有标签日期分三段滚动验证，每段训练前隔离跨界收益标签，训练窗口最多 252 个日期。预测时用当时已知标签重新训练。相邻标签重叠，样本非独立；固定候选池、有幸存者偏差，无费用收益回测。模型可能不及均值基线，不保证预测有效。'}

def minute_data(code,end,demo=False):
    if demo:
        rng=random.Random(int(code));price=20;rows=[]
        for day in ((datetime.fromisoformat(end)-timedelta(days=1)).date().isoformat(),end):
            for hour,mins in [(9,range(30,60)),(10,range(60)),(11,range(30)),(13,range(60)),(14,range(60))]:
                for minute in mins:
                    opening=price;price*=1+rng.gauss(0,.001)
                    rows.append({'time':f'{day} {hour:02}:{minute:02}','open':opening,'close':price,'volume':rng.randint(100,2000)*100})
        return rows
    secid=('1.' if code.startswith('6') else '0.')+code
    beg=(datetime.fromisoformat(end)-timedelta(days=7)).strftime('%Y%m%d')
    try:
        d=get_json('https://push2his.eastmoney.com/api/qt/stock/kline/get',{'secid':secid,'klt':1,'fqt':0,'beg':beg+'000000','end':end.replace('-','')+'235959','lmt':1000,'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58'})
    except requests.RequestException:
        d={}
    rows=[]
    for line in (d.get('data') or {}).get('klines') or []:
        p=line.split(',')
        if p[0][:10]<=end:rows.append({'time':p[0],'open':float(p[1]),'close':float(p[2]),'volume':float(p[5])*100})
    if not any(r['time'][:10]==end for r in rows):
        symbol=('sh' if code.startswith('6') else 'sz')+code
        d=get_json('https://ifzq.gtimg.cn/appstock/app/kline/mkline',{'param':f'{symbol},m1,,640'})
        rows=[]
        for p in d.get('data',{}).get(symbol,{}).get('m1',[]):
            stamp=datetime.strptime(p[0],'%Y%m%d%H%M').strftime('%Y-%m-%d %H:%M')
            if stamp[:10]<=end:rows.append({'time':stamp,'open':float(p[1]),'close':float(p[2]),'volume':float(p[5])*100})
    if not any(r['time'][:10]==end for r in rows):raise ValueError('数据源没有该日分钟线（公共接口通常仅覆盖近期）。可切换演示，或导入分钟 CSV')
    return rows

def execute(rows,method,quantity,side,participation,slippage,lot=100):
    if method not in ('twap','vwap','pov','iceberg') or side not in ('buy','sell'):raise ValueError('执行方法或方向无效')
    if not 0<quantity<=10000000 or quantity%lot or not .001<=participation<=.5 or not 0<=slippage<=.03:raise ValueError('数量须为最小单位的整数倍，参与率 0.1%–50%，滑点 0–3%')
    if not 2<=len(rows)<=1000:raise ValueError('至少需要两根、最多 1000 根分钟线')
    rows=sorted(rows,key=lambda r:r['time']);day=rows[-1]['time'][:10];current=[r for r in rows if r['time'][:10]==day];prior=[r for r in rows if r['time'][:10]<day]
    if method=='vwap' and not prior:raise ValueError('VWAP 排程需要前一交易日分钟成交量；请导入含前一日的分钟数据，或选择其他算法')
    profile={r['time'][11:16]:r['volume'] for r in prior};profile_total=sum(profile.get(r['time'][11:16],0) for r in current)
    if method=='vwap' and profile_total<=0:raise ValueError('前一日对应时段无有效成交量分布')
    if method=='vwap' and any(r['time'][11:16] not in profile for r in current):raise ValueError('前一日分钟线覆盖不完整，请导入完整两日数据后使用 VWAP')
    remaining=quantity;orders=[];scheduled=0;filled=0;cost=0;fees=0
    for i,r in enumerate(current):
        if method=='twap':scheduled=quantity*(i+1)/len(current)
        elif method=='vwap':scheduled+=quantity*profile.get(r['time'][11:16],0)/profile_total
        desired=scheduled-filled if method in ('twap','vwap') else r['volume']*participation if method=='pov' else min(quantity*.05,remaining)
        capacity=math.floor(r['volume']*participation/lot)*lot
        size=min(remaining,math.floor(max(0,desired)/lot)*lot,capacity)
        if size:
            price=r['open']*(1+slippage if side=='buy' else 1-slippage);value=size*price;f=fee(value,day,side=='sell',.0003,5)
            filled+=size;remaining-=size;cost+=value;fees+=f;orders.append({'time':r['time'],'quantity':size,'price':price,'fees':f})
    totalvol=sum(r['volume'] for r in current);benchmark=sum(r['close']*r['volume'] for r in current)/totalvol if totalvol else None
    average=cost/filled if filled else None;arrival=current[0]['open']
    return {'method':method,'side':side,'date':day,'orders':orders,'filled':filled,'remaining':remaining,'fees':fees,
        'average':average,'benchmark':benchmark,'arrival':arrival,'slippage_bps':(average/arrival-1)*(1 if side=='buy' else -1)*10000 if average else None,
        'caveat':'离线分钟级拆单模拟，不下真实订单。TWAP 均匀排程；VWAP 只用前一日成交量安排，当前日 VWAP 仅作事后基准；POV 用当分钟成交量作容量上限，冰山每次最多目标量的 5%。四种方法都受参与率和申报单位限制，允许未完成。分钟总量及开盘模拟成交无法刻画真实盘口、排队和涨跌停，POV 不是实时可执行保证。卖出假定已有足额可卖持仓。费用按示例佣金万三最低五元及日期税费估计。'}

POS=['增长','增持','回购','盈利','中标','突破','改善','上调','创新高','分红']
NEG=['亏损','减持','处罚','下滑','下降','违约','诉讼','立案','风险','终止','下调']
def clean(s):return html.unescape(re.sub('<[^>]*>','',str(s))).strip()
def text_analysis(text):
    if not 10<=len(text)<=50000:raise ValueError('请输入 10–50000 字文本')
    text=clean(text);sentences=[s.strip() for s in re.split('[。！？\n]',text) if len(s.strip())>5]
    hits=[]
    for word,sign in [(w,1) for w in POS]+[(w,-1) for w in NEG]:
        for m in re.finditer(word,text):
            before=text[max(0,m.start()-3):m.start()];negated=bool(re.search('不|未|无',before))
            hits.append({'word':word,'polarity':-sign if negated else sign,'negated':negated})
    score=sum(h['polarity'] for h in hits)/max(1,len(hits))
    ranked=sorted(enumerate(sentences),key=lambda p:sum(w in p[1] for w in POS+NEG)+bool(re.search(r'\d',p[1])),reverse=True)[:3]
    summary='。'.join(s for _,s in sorted(ranked))[:1200]
    return {'summary':summary,'sentiment':'偏正面' if score>.15 else '偏负面' if score<-.15 else '中性/混合','score':score,
        'hits':hits[:100],'numbers':re.findall(r'[-+]?\d+(?:\.\d+)?\s*(?:%|亿元|万元|元|万股|亿股|股)',text)[:30],
        'caveat':'默认使用本地词典、简单否定识别与原文摘句，未调用大模型。情绪不是股价预测，可能误解语境和主体；摘要仅来自输入文本。'}

def search_news(code,end):
    param={'uid':'','keyword':code,'type':['cmsArticleWebOld'],'client':'web','clientType':'web','clientVersion':'curr','param':{'cmsArticleWebOld':{'searchScope':'default','sort':'default','pageIndex':1,'pageSize':30,'preTag':'','postTag':''}}}
    r=requests.get('https://search-api-web.eastmoney.com/search/jsonp',params={'cb':'callback','param':json.dumps(param)},timeout=20);r.raise_for_status()
    raw=r.text;payload=json.loads(raw[raw.index('(')+1:raw.rindex(')')]);rows=payload.get('result',{}).get('cmsArticleWebOld',[])
    if 'cmsArticleWebOld' not in payload.get('result',{}):raise ValueError('新闻搜索接口返回格式已变化')
    return [{'title':clean(x.get('title','')),'text':clean(x.get('content','')),'published_at':x.get('date',''),
        'source':clean(x.get('mediaName','')),'url':'https://finance.eastmoney.com/a/'+str(x.get('code',''))+'.html'} for x in rows if str(x.get('date',''))[:10] and str(x['date'])[:10]<=end]

def news(code,end):
    try:
        rows=search_news(code,end)
        if rows:return rows
    except (requests.RequestException,ValueError,KeyError):pass
    d=get_json('https://np-anotice-stock.eastmoney.com/api/security/ann',{'sr':-1,'page_size':30,'page_index':1,'ann_type':'A','client_source':'web','stock_list':code})
    return [{'title':clean(r['title']),'text':'公告标题。点击可读取公告正文。','published_at':r['notice_date'],'source':'东方财富公告（新闻源不可用或无匹配时备用）',
        'art_code':r['art_code'],'url':f'https://data.eastmoney.com/notices/detail/{code}/{r["art_code"]}.html'} for r in (d.get('data') or {}).get('list',[]) if str(r.get('notice_date',''))[:10] and r['notice_date'][:10]<=end]

def article(art_code,end):
    if not re.fullmatch(r'AN\d{18}',art_code):raise ValueError('公告编号格式无效')
    d=get_json('https://np-cnotice-stock.eastmoney.com/api/content/ann',{'art_code':art_code,'client_source':'web'}).get('data') or {}
    day=str(d.get('notice_date',''))[:10]
    if not day or day>end:raise ValueError('公告日期缺失或晚于查看日期')
    text=clean(d.get('notice_content',''))[:50000]
    if not text:raise ValueError('该公告无可提取正文，请打开来源查看 PDF')
    return {'text':text,'published_at':day,'title':clean(d.get('notice_title',''))}
