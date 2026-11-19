"""Imported point-in-time histories and an isolated auditable daily portfolio.

Source timestamps are assertions supplied by the data producer, not certified PIT.
Never fills gaps with today's constituents, financial reports or inferred prices.
"""
import hashlib
import json
import math
import random
import re
import platform
import threading
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from ashare_rules import board_for, daily_rule, execution_quote, RULE_VERSION, SOURCES
from research import fee, metrics

TZ=timezone(timedelta(hours=8))
LOCK=threading.RLock()
ENGINE_ROOT=Path(__file__).resolve().parent
LOADED_SOURCES={n:hashlib.sha256((ENGINE_ROOT/n).read_bytes()).hexdigest() for n in ('point_in_time.py','ashare_rules.py','research.py')}

def engine_manifest():
    current={n:hashlib.sha256((ENGINE_ROOT/n).read_bytes()).hexdigest() for n in LOADED_SOURCES}
    if current!=LOADED_SOURCES:raise ValueError('历史研究引擎在服务启动后已修改，请重启服务')
    return {'sources':current,'python':platform.python_version()}

def packed(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def fingerprint(x):return hashlib.sha256(packed(x).encode()).hexdigest()
def day(value):
    if not isinstance(value,str) or len(value)!=10:raise ValueError('日期须为 YYYY-MM-DD')
    date.fromisoformat(value);return value

def known_time(value):
    if not isinstance(value,str):raise ValueError('披露与可用时间必须提供字符串')
    if len(value)==10:
        # Date-only notices cannot be used on the publication date.
        return datetime.combine(date.fromisoformat(value)+timedelta(days=1),datetime.min.time(),TZ)
    dt=datetime.fromisoformat(value)
    if dt.tzinfo is None:raise ValueError('精确时间必须包含时区，例如 +08:00')
    return dt.astimezone(TZ)

def financial_asof(records,code,cutoff):
    at=known_time(cutoff) if len(cutoff)>10 else datetime.fromisoformat(day(cutoff)+'T15:00:00+08:00')
    usable=[r for r in records if r['code']==code and r['report_date']<=at.date().isoformat()
            and max(known_time(r['published_at']),known_time(r['available_at']))<=at]
    if not usable:return None
    return max(usable,key=lambda r:(r['report_date'],known_time(r['available_at']),known_time(r['published_at'])))

class HistoryDataset:
    def __init__(self,payload):
        if not isinstance(payload,dict) or payload.get('schema')!=1:raise ValueError('历史数据包 schema 必须为 1')
        if set(payload)-{'schema','provenance','calendar','securities','daily','financials','settlements'}:raise ValueError('数据包含未知字段')
        self.payload=json.loads(packed(payload));p=self.payload
        provenance=p.get('provenance',{})
        if provenance.get('mode') not in ('demo','imported') or not provenance.get('source'):
            raise ValueError('必须声明 provenance.mode 和 source')
        known_time(provenance.get('retrieved_at'))
        if type(provenance.get('universe_complete')) is not bool:raise ValueError('须声明 universe_complete；声明不等于已核验')
        self.calendar=p.get('calendar',[])
        if not 30<=len(self.calendar)<=2500 or self.calendar!=sorted(set(self.calendar)):raise ValueError('交易日历需有 30–2500 个递增且不重复日期')
        for d in self.calendar:day(d)
        calendar=set(self.calendar);self.master={}
        for s in p.get('securities',[]):
            c=s['code'];board_for(c);day(s['listed_on'])
            if c in self.master:raise ValueError('股票主表代码重复，不支持代码复用')
            for key in ('last_trading_day','delisted_on'):
                if s.get(key):day(s[key])
            if bool(s.get('last_trading_day'))!=bool(s.get('delisted_on')):raise ValueError('退市样本必须同时提供最后交易日与摘牌日')
            if s.get('delisted_on') and not s['listed_on']<=s['last_trading_day']<s['delisted_on']:raise ValueError('上市、最后交易与摘牌日期顺序错误')
            if not s.get('source'):raise ValueError('股票主表每行须提供 source')
            self.master[c]=s
        if not 2<=len(self.master)<=30:raise ValueError('当前单次严格研究支持 2–30 只历史股票样本')
        self.daily={};self.prices={c:{} for c in self.master}
        for r in p.get('daily',[]):
            c=r['code'];d=day(r['date']);key=(c,d)
            if c not in self.master or d not in calendar or c not in self.members(d):raise ValueError('日线不在股票存续区间或交易日历内')
            if key in self.daily:raise ValueError('同一股票与日期的状态 / 日线重复')
            if type(r.get('is_st')) is not bool or type(r.get('suspended')) is not bool:raise ValueError('每日必须明确提供 is_st 与 suspended')
            if not r['suspended']:
                vals=[r.get(k) for k in ('close','raw_open','raw_close','raw_high','raw_low','volume_shares')]
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in vals) or min(vals[:5])<=0 or vals[5]<0:raise ValueError('日线价格和股数无效；volume_shares 必须以股为单位')
                if not r['raw_low']<=min(r['raw_open'],r['raw_close'])<=max(r['raw_open'],r['raw_close'])<=r['raw_high']:raise ValueError('OHLC 不一致')
                if 'auction_volume_shares' in r:
                    auction=r['auction_volume_shares']
                    if type(auction) not in (int,float) or not math.isfinite(auction) or not 0<=auction<=r['volume_shares']:raise ValueError('开盘集合竞价股数必须非负且不超过日成交股数')
            self.daily[key]=r
        # A missing row is not treated as a suspension; require a stated status.
        for d in self.calendar:
            for c in self.members(d):
                if (c,d) not in self.daily:raise ValueError(f'{c} {d} 缺少日线或明确停牌记录，停止以防静默删样本')
                r=self.daily[c,d]
                if not r['suspended']:self.prices[c][d]=r
        self.financials=p.get('financials',[]);seen=set()
        for r in self.financials:
            if r['code'] not in self.master:raise ValueError('财报代码不在股票主表')
            day(r['report_date']);pub=known_time(r['published_at']);available=known_time(r['available_at'])
            if pub.date().isoformat()<r['report_date'] or available<pub:raise ValueError('财报可用时间不能早于披露时间，披露不能早于报告期')
            key=(r['code'],r['report_date'],r['available_at'])
            if key in seen:raise ValueError('财报同一可用时点出现重复版本')
            seen.add(key)
            if not r.get('version') or not r.get('source') or not isinstance(r.get('values'),dict):raise ValueError('财报须含 version、source、values')
            for v in r['values'].values():
                if v is not None and (type(v) not in (int,float) or not math.isfinite(v)):raise ValueError('财报数值必须有限或为空')
        self.settlements={}
        for r in p.get('settlements',[]):
            c=r['code'];d=day(r['date']);v=r.get('cash_per_share')
            if c not in self.master or not self.master[c].get('last_trading_day') or d<=self.master[c]['last_trading_day']:raise ValueError('退出处置日期须晚于最后交易日')
            if type(v) not in (int,float) or not math.isfinite(v) or v<0 or r.get('kind') not in ('actual','scenario') or not r.get('source'):raise ValueError('退市处置须明确每股现金、来源和 actual / scenario 性质')
            if c in self.settlements:raise ValueError('每只股票暂支持一次最终退出处置')
            self.settlements[c]=r
        self.identifier=fingerprint(self.payload)

    def members(self,d):
        return sorted(c for c,s in self.master.items() if s['listed_on']<=d and (not s.get('last_trading_day') or d<=s['last_trading_day']))

    def rule(self,c,d):
        s=self.master[c];r=self.daily[c,d];prior=[b for dt,b in self.prices[c].items() if dt<d]
        previous=max(prior,key=lambda b:b['date']) if prior else None
        reference=r.get('reference_price')
        if reference is None and previous:reference=previous['raw_close']
        if reference is None:reference=r.get('raw_open',1)
        if type(reference) not in (int,float) or not math.isfinite(reference) or reference<=0:raise ValueError('涨跌停参考价无效')
        ordinal=sum(s['listed_on']<=dt<=d for dt in self.calendar)
        ordinal=ordinal if s['listed_on']>=self.calendar[0] or ordinal>=6 else None
        return daily_rule(c,d,r,reference,ordinal,s['listed_on'])

    def audit(self,end):
        days=[d for d in self.calendar if d<=day(end)]
        if not days:raise ValueError('截止日期早于数据包日历')
        rows=[]
        for d in days:
            pool=self.members(d);disclosed=[financial_asof(self.financials,c,d) for c in pool]
            rows.append({'date':d,'members':len(pool),'st':sum(self.daily[c,d]['is_st'] for c in pool),
                'suspended':sum(self.daily[c,d]['suspended'] for c in pool),
                'financial_available':sum(r is not None for r in disclosed),
                'historical_delisted':sum(bool(self.master[c].get('last_trading_day') and self.master[c]['last_trading_day']<d) for c in self.master)})
        versions=[]
        for c in sorted(self.master):
            r=financial_asof(self.financials,c,days[-1])
            versions.append({'code':c,'member':c in self.members(days[-1]),'report_date':r['report_date'] if r else None,
                'published_at':r['published_at'] if r else None,'available_at':r['available_at'] if r else None,'version':r['version'] if r else None})
        return {'timeline':rows,'financial_versions':versions,'codes':sorted(self.master),
            'coverage':[[0 if c not in self.members(d) else 1 if self.daily[c,d]['suspended'] else 2 for d in days[-90:]] for c in sorted(self.master)],
            'coverage_dates':days[-90:],'provenance':self.payload['provenance'],'dataset_id':self.identifier,'asof':days[-1]}

def strict_backtest(dataset,end,start='',lookback=20,interval=10,top_k=2,capital=300000.,factor='momentum',participation=.02,slippage=.001,commission=.0003,min_fee=5.):
    if type(lookback) is not int or not 5<=lookback<=120 or type(interval) is not int or not 1<=interval<=63 or type(top_k) is not int or not 1<=top_k<=len(dataset.master):raise ValueError('回看窗口、调仓周期或持股数量无效')
    if factor not in ('momentum','roe'):raise ValueError('严格研究支持动量或时点财报 ROE 排序')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (capital,participation,slippage,commission,min_fee)):raise ValueError('数值参数须有限')
    if not 10000<=capital<=1e8 or not 0<participation<=.1 or not 0<=slippage<=.03 or not 0<=commission<=.01 or not 0<=min_fee<=100:raise ValueError('资金、容量或费用参数超出范围')
    if start:day(start)
    days=[d for d in dataset.calendar if d<=day(end)]
    selected=[i for i in range(lookback+1,len(days)) if not start or days[i]>=start]
    if len(selected)<2:raise ValueError('至少需要回看窗口加三个日历交易日')
    if days[selected[0]]<'2015-08-01':raise ValueError('当前费用日历仅覆盖 2015-08-01 以后，不能静默套用到更早历史')
    cash=capital;positions={};marks={};equity=[];orders=[];selections=[];settled=[];costs=0;target=[]
    for n,i in enumerate(selected):
        d=days[i];signal_day=days[i-1]
        # Explicit terminal cash-out. Never drop a delisted holding from NAV.
        for c in list(positions):
            s=dataset.master[c]
            if s.get('last_trading_day') and d>s['last_trading_day']:
                exit=dataset.settlements.get(c)
                if not exit:raise ValueError(c+' 退市后仍有持仓，缺少退出现金或明确情景处置，拒绝伪造完整净值')
                if d>=exit['date']:
                    amount=positions[c]['qty']*exit['cash_per_share'];cash+=amount
                    settled.append({'code':c,'date':d,'amount':amount,**exit});del positions[c];continue
                # Pending exit is not liquidated at an invented last close.
                raise ValueError(c+' 退市处置尚未发生，缺少期间估值，停止研究')
        candidates=[];excluded={'st':0,'suspended':0,'history':0,'financial':0}
        if n%interval==0:
            for c in dataset.members(signal_day):
                r=dataset.daily[c,signal_day]
                if r['is_st']:excluded['st']+=1;continue
                if r['suspended']:excluded['suspended']+=1;continue
                # Require price anchors on calendar dates, not intersection across stocks.
                anchor=dataset.prices[c].get(days[i-1-lookback]);last=dataset.prices[c].get(signal_day)
                if not anchor or not last:excluded['history']+=1;continue
                report=financial_asof(dataset.financials,c,signal_day)
                value=last['close']/anchor['close']-1 if factor=='momentum' else (report or {}).get('values',{}).get('roe')
                if value is None:excluded['financial']+=1;continue
                candidates.append({'code':c,'score':value,'financial_version':report['version'] if report else None})
            candidates.sort(key=lambda r:(-r['score'],r['code']));target=[r['code'] for r in candidates[:top_k]]
            selections.append({'signal_date':signal_day,'execution_date':d,'pool':dataset.members(signal_day),
                'ranked':candidates,'target':target.copy(),'excluded':excluded})
        # Mark holdings at today's open only for sizing, not for ranking signals.
        for c,pos in positions.items():
            r=dataset.daily.get((c,d))
            if r is None:raise ValueError(c+' 持仓缺少行情或停牌记录')
            if not r['suspended']:
                prior=max((r for dt,r in dataset.prices[c].items() if dt<d),key=lambda r:r['date'],default=None)
                if prior and abs((r['close']/r['raw_close'])/(prior['close']/prior['raw_close'])-1)>.00001:
                    raise ValueError(c+' 发生复权因子变化，缺少逐笔公司行动账本，停止严格成交研究')
                marks[c]=r['raw_open']
            elif c not in marks:raise ValueError(c+' 停牌持仓缺少已知估值')
        open_equity=cash+sum(p['qty']*marks[c] for c,p in positions.items())
        if n%interval==0:
            desired={}
            for c in target:
                r=dataset.daily.get((c,d))
                if not r or r['suspended']:desired[c]=positions.get(c,{}).get('qty',0);continue
                rule=dataset.rule(c,d);budget=open_equity/top_k
                # Reserve proportional costs; minimum fees are checked again before fill.
                raw=math.floor(max(0,budget-min_fee)/(r['raw_open']*(1+slippage)*(1+commission+.00002)))
                desired[c]=raw//rule['quantity_step']*rule['quantity_step']
            changes=[(c,desired.get(c,0)-positions.get(c,{}).get('qty',0)) for c in sorted(set(positions)|set(target))]
            for c,delta in sorted(changes,key=lambda x:(x[1]>0,x[0])):
                if not delta:continue
                r=dataset.daily.get((c,d));side='buy' if delta>0 else 'sell';quantity=abs(delta)
                order={'date':d,'signal_date':signal_day,'code':c,'side':side,'requested':quantity,'filled':0}
                if r is None:
                    order['reason']='执行日已退出上市交易范围';orders.append(order);continue
                rule=dataset.rule(c,d)
                available=sum(l['qty'] for l in positions.get(c,{}).get('lots',[]) if l['date']<d)
                if side=='buy':
                    estimate=r.get('raw_open',1)*(1+slippage)
                    affordable=max(0,math.floor((cash-min_fee)/(estimate*(1+commission+.00002))))
                    quantity=min(quantity,affordable)
                    if quantity<=0:order['reason']='可用现金不足';orders.append(order);continue
                fill=({'filled':0,'reason':'执行日 ST，不新增买入'} if side=='buy' and rule['is_st']
                      else execution_quote(c,d,r,rule,side,quantity,available,slippage,participation))
                order.update(fill,rule_version=RULE_VERSION)
                qty=fill['filled']
                if qty:
                    value=qty*fill['price'];fees=fee(value,d,side=='sell',commission,min_fee)
                    if side=='buy':
                        if value+fees>cash+1e-8:raise ValueError('费用后资金预算不足')
                        cash-=value+fees;pos=positions.setdefault(c,{'qty':0,'lots':[]});pos['qty']+=qty;pos['lots'].append({'date':d,'qty':qty})
                    else:
                        cash+=value-fees;pos=positions[c];remaining=qty
                        for lot in pos['lots']:
                            if lot['date']>=d:continue
                            take=min(remaining,lot['qty']);lot['qty']-=take;remaining-=take
                        pos['lots']=[l for l in pos['lots'] if l['qty']];pos['qty']-=qty
                        if not pos['qty']:del positions[c]
                    costs+=fees;order['fees']=fees
                    if qty<order['requested']:order['reason']='部分成交，余单当日撤销'
                orders.append(order)
        for c in positions:
            r=dataset.daily[c,d]
            if not r['suspended']:marks[c]=r['raw_close']
        value=cash+sum(p['qty']*marks[c] for c,p in positions.items())
        if cash < -1e-7 or not math.isfinite(value):raise ValueError('账户资金核对失败')
        equity.append({'date':d,'value':value,'cash':cash,'holdings':len(positions),'fees':costs})
    peak=capital;drawdown=[]
    for r in equity:peak=max(peak,r['value']);drawdown.append({'date':r['date'],'value':r['value']/peak-1})
    return {'equity':equity,'drawdown':drawdown,'orders':orders,'selections':selections,'settlements':settled,
        'metrics':metrics(equity,capital),'fees':costs,'positions':positions,'capital':capital,'factor':factor,
        'assumptions':'前一交易日收盘排序，按历史存续股票池选股；调仓日开盘按等预算买卖，余单当日撤销、不自动追单；容量只用提供的开盘集合竞价成交股数。日线滑点仍是情景近似，不复原竞价队列。',
        'rule_version':RULE_VERSION,'sources':SOURCES,'dataset_id':dataset.identifier,'engine':engine_manifest(),
        'config':{'start':start,'end':days[-1],'lookback':lookback,'interval':interval,'top_k':top_k,'capital':capital,'factor':factor,'participation':participation,'slippage':slippage,'commission':commission,'min_fee':min_fee}}

def demo_dataset():
    rng=random.Random(903);calendar=[];d=date(2025,1,2)
    while len(calendar)<160:
        if d.weekday()<5:calendar.append(d.isoformat())
        d+=timedelta(days=1)
    securities=[];daily=[];financials=[];settlements=[]
    codes=['600001','600002','000001','000002','300001','688001']
    for k,c in enumerate(codes):
        first=35 if k==5 else 0;last=100 if k==0 else 159
        s={'code':c,'listed_on':calendar[first] if first else '2010-01-01','source':'合成主表'}
        if k==0:
            s.update(last_trading_day=calendar[last],delisted_on=calendar[last+1]);settlements.append({'code':c,'date':calendar[last+1],'cash_per_share':1.,'kind':'scenario','source':'演示退出现金情景，非实际退市回收'})
        securities.append(s);price=10+k*3
        for i in range(first,last+1):
            suspended=(k==2 and 70<=i<=74);old=price
            if not suspended:price=max(1,price*(1+(.004 if k==0 and i<75 else .0006)+rng.gauss(0,.012)))
            r={'code':c,'date':calendar[i],'is_st':k==1 and 60<=i<=90,'suspended':suspended}
            if not suspended:r.update(close=price,raw_open=old,raw_close=price,raw_high=max(old,price)*1.003,raw_low=min(old,price)*.997,volume_shares=1000000,auction_volume_shares=200000,reference_price=old)
            daily.append(r)
        financials.append({'code':c,'report_date':'2024-09-30','published_at':'2024-10-30','available_at':'2024-10-31T09:00:00+08:00','version':'original','source':'合成财报','values':{'roe':8+k}})
        financials.append({'code':c,'report_date':'2024-09-30','published_at':calendar[90]+'T18:00:00+08:00','available_at':calendar[91]+'T09:00:00+08:00','version':'correction','source':'合成更正','values':{'roe':9+k*2}})
    return {'schema':1,'provenance':{'mode':'demo','source':'合成演示；工作日日历不是真实交易所日历','retrieved_at':'2026-11-19T09:00:00+08:00','universe_complete':False},'calendar':calendar,'securities':securities,'daily':daily,'financials':financials,'settlements':settlements}

class PITStore:
    def __init__(self,root):self.root=Path(root)/'point_in_time'
    def inventory(self):
        rows=[]
        for p in sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:
            try:
                ds=self.load(p.stem)
                rows.append({'dataset_id':ds.identifier,'source':ds.payload['provenance']['source'],
                    'mode':ds.payload['provenance']['mode'],'start':ds.calendar[0],'end':ds.calendar[-1],'securities':len(ds.master)})
            except (ValueError,KeyError,TypeError):continue
        return rows
    def save(self,payload):
        ds=HistoryDataset(payload);self.root.mkdir(parents=True,exist_ok=True);p=self.root/(ds.identifier+'.json')
        with LOCK:
            content=packed(ds.payload)
            if p.exists():
                if p.read_text(encoding='utf-8')!=content:raise ValueError('内容寻址文件冲突')
            else:
                temporary=self.root/(ds.identifier+'.'+uuid.uuid4().hex+'.tmp')
                try:
                    with temporary.open('x',encoding='utf-8',newline='') as f:
                        f.write(content);f.flush();os.fsync(f.fileno())
                    temporary.replace(p)
                finally:
                    if temporary.exists():temporary.unlink()
        return ds
    def load(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{64}',identifier):raise ValueError('数据包编号无效')
        path=self.root/(identifier+'.json')
        if not path.is_file():raise ValueError('数据包不存在，请先导入或载入演示')
        with LOCK:ds=HistoryDataset(json.loads(path.read_text(encoding='utf-8')))
        if ds.identifier!=identifier:raise ValueError('数据包内容校验失败')
        return ds

def dispatch(body,root):
    store=PITStore(root);action=body.get('action','demo')
    if action=='list':return {'datasets':store.inventory()}
    if action=='demo':ds=store.save(demo_dataset())
    elif action=='import':ds=store.save(body.get('dataset'))
    else:ds=store.load(body.get('dataset_id',''))
    if action=='export':return {'dataset':ds.payload,'dataset_id':ds.identifier}
    end=body.get('end') or ds.calendar[-1]
    result=ds.audit(end)
    if action in ('run','replay'):
        config=body.get('config',{})
        if not isinstance(config,dict) or set(config)-{'start','lookback','interval','top_k','capital','factor','participation','slippage','commission','min_fee'}:raise ValueError('严格研究参数含未知字段')
        result['backtest']=strict_backtest(ds,end,**config)
        result['result_hash']=fingerprint(result['backtest'])
        if action=='replay':
            if not isinstance(body.get('expected_hash'),str):raise ValueError('复算须提供原始结果哈希')
            result['matched']=result['result_hash']==body['expected_hash']
    elif action not in ('demo','import','audit'):raise ValueError('未知历史研究操作')
    result['notice']='本地导入样本；来源、时间与全市场覆盖声明尚未被外部核验。不能仅凭导入成功声称消除幸存者偏差或实现完整 PIT。旧研究模块仍保留原有近似口径。'
    return result
