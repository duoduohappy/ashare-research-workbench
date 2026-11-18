"""Versioned local research and paper operations. Never sends exchange orders."""
import contextlib,hashlib,json,math,os,platform,re,sqlite3,threading,time,uuid,zipfile
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from model import analyze
from research import backtest,fee,rounded_price

# Pin the source that this process actually imported. Reading mutable source
# files at job time could otherwise label old in-memory code as a new engine.
ENGINE_FILES={n:(Path(__file__).parent/n).read_text(encoding='utf-8') for n in ('ops_engine.py','model.py','research.py')}

TZ=timezone(timedelta(hours=8))
def now():return datetime.now(TZ)
def stamp():return now().isoformat(timespec='seconds')
def packed(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(packed(v).encode()).hexdigest()
class Blocked(ValueError):pass

@contextlib.contextmanager
def connect(path):
    c=sqlite3.connect(path,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA busy_timeout=30000');c.execute('PRAGMA foreign_keys=ON')
    try:
        with c:yield c
    finally:c.close()

def gate(feeds,calendar,asof,mode='live',clock=None,secondary=None):
    clock=clock or now();end=date.fromisoformat(asof)
    checks=[]
    def check(name,passed,detail):checks.append({'check':name,'pass':bool(passed),'detail':detail})
    days=calendar.get('days',[])
    check('交易日历覆盖',bool(days) and calendar.get('covered_until','')>=asof,'来源：'+calendar.get('source','未知'))
    try:age=(clock-datetime.fromisoformat(calendar['fetched_at'])).total_seconds();valid_age=0<=age<=7*86400
    except (ValueError,KeyError,TypeError):valid_age=False
    check('交易日历新鲜度',valid_age,'交易日历最多缓存七天')
    if end>clock.date() or (end==clock.date() and asof in days and (clock.hour,clock.minute)<(15,20)):check('日线已收盘',False,'北京时间 15:20 后才接纳当日日线')
    eligible=[d for d in days if d<=asof];expected=max(eligible) if eligible else None
    check('存在已核验交易日',expected is not None,'截止日对应交易日：'+str(expected))
    for code,h in feeds.items():
        bars=h.get('bars',[]);dates=[b.get('date','') for b in bars]
        check(code+' 非过期缓存',not h.get('stale',True),h.get('source','未知'))
        try:age=(clock-datetime.fromisoformat(h['fetched_at'])).total_seconds();fresh=0<=age<=12*3600
        except (ValueError,KeyError,TypeError):fresh=False
        check(code+' 获取时间',fresh,'快照获取距今不得超过十二小时')
        check(code+' 日期顺序及唯一性',dates==sorted(set(dates)),'不能依赖清洗静默修正重复或乱序')
        past=[b for b in bars if b.get('date','')<=asof]
        check(code+' 预热样本',len(past)>=300,'严格研究至少 300 个日线观测')
        check(code+' 最新交易日',bool(past) and past[-1]['date']==expected,'不得以旧收盘价代替最新已核验交易日')
        valid=True
        for b in past:
            try:
                values=[float(b[k]) for k in ('close','raw_open','raw_close','raw_high','raw_low','volume')]
                if not all(math.isfinite(v) for v in values) or min(values[:5])<=0 or values[5]<0:valid=False
                if not b['raw_low']-.005<=min(b['raw_close'],b['raw_open'])<=max(b['raw_close'],b['raw_open'])<=b['raw_high']+.005:valid=False
            except (KeyError,TypeError,ValueError):valid=False
        check(code+' OHLC 与数值',valid,'原始 OHLC、复权收盘和成交量均须有效')
        start=past[0]['date'] if past else asof;actual={b['date'] for b in past};missing=[d for d in days if start<=d<=asof and d not in actual]
        check(code+' 交易日覆盖',not missing,'缺失 '+str(len(missing))+' 日；停牌状态未核验时同样阻断')
        other=(secondary or {}).get(code,{})
        check(code+' 独立来源收盘核对',bool(past) and other.get('date')==expected and isinstance(other.get('close'),(int,float)) and abs(other['close']-past[-1]['raw_close'])<=.02,
              '主源与独立来源的原始收盘价差不得超过 0.02 元')
    if mode=='demo':checks.append({'check':'演示隔离','pass':True,'detail':'合成数据只允许进入演示策略版本，不能转换成真实数据版本'})
    return {'passed':all(c['pass'] for c in checks),'checks':checks,'expected_day':expected,'mode':mode,'asof':asof}

def validate_config(config):
    c={'codes':config.get('codes',[]),'window':int(config.get('window',20)),'threshold':float(config.get('threshold',.05)),
       'ma':int(config.get('ma',60)),'momentum':int(config.get('momentum',20)),'capital':float(config.get('capital',300000)),
       'max_weight':float(config.get('max_weight',.35)),'max_drawdown':float(config.get('max_drawdown',.15)),
       'daily_orders':int(config.get('daily_orders',3)),'commission':float(config.get('commission',.0003)),
       'minimum_fee':float(config.get('minimum_fee',5)),'slippage':float(config.get('slippage',.001)),
       'mode':config.get('mode','live')}
    if not 1<=len(c['codes'])<=8 or len(set(c['codes']))!=len(c['codes']) or any(not re.fullmatch(r'(600|601|603|605|688|000|001|002|003|300|301)\d{3}',s) for s in c['codes']):raise ValueError('版本包含 1–8 个不重复沪深普通股票代码')
    if any(not math.isfinite(v) for v in c.values() if isinstance(v,(float,int))):raise ValueError('配置数值必须有限')
    if not (5<=c['window']<=120 and .001<=c['threshold']<=.5 and 5<=c['ma']<=120 and 5<=c['momentum']<=120):raise ValueError('模型周期或阈值无效')
    if not (1000<=c['capital']<=1e9 and .05<=c['max_weight']<=1 and .01<=c['max_drawdown']<=.8 and 1<=c['daily_orders']<=16):raise ValueError('资金或风险约束无效')
    if not (0<=c['commission']<=.01 and 0<=c['minimum_fee']<=100 and 0<=c['slippage']<=.03) or c['mode'] not in ('live','demo'):raise ValueError('费用或数据模式无效')
    return c

def research_result(snapshot,config):
    result={}
    for code,h in snapshot['feeds'].items():
        bars=h['bars'];frames=analyze(bars,config['window'],config['threshold'])
        split=max(config['window']+253,int(len(bars)*.7))
        if len(bars)-split<30:raise Blocked('样本外观测不足 30 日：'+code)
        bt=backtest(bars,frames,code,config['window'],start=bars[split]['date'],capital=config['capital'],commission=config['commission'],min_fee=config['minimum_fee'],slippage=config['slippage'],
             limit=.2 if code.startswith(('300','301','688')) else .1,trend_period=config['ma'],momentum_period=config['momentum'])
        result[code]={'asof':bars[-1]['date'],'state':frames[-1],'validation':bt,'holdout_start':bars[split]['date']}
    return {'assets':result,'gate':snapshot['gate'],'assumptions':'固定参数，最后约 30% 时间段为验证；单股回测不代表组合表现。验证通过仅代表数据和流程合格，不代表策略盈利；历史数据为当前修订版本。'}

def signal(bars,c):
    if len(bars)<max(300,c['ma']+1,c['momentum']+1):raise Blocked('信号预热不足')
    state=analyze(bars,c['window'],c['threshold'])[-1]
    avg=sum(b['close'] for b in bars[-c['ma']:])/c['ma'];mom=bars[-1]['close']/bars[-1-c['momentum']]['close']-1
    return {'date':bars[-1]['date'],'long':bars[-1]['close']>avg and mom>0 and state['signal']>0,'ma':avg,'momentum':mom,'markov_signal':state['signal']}

def paper_step(account,feeds,day,c):
    # Pure daily transition; the caller atomically commits this result.
    a=json.loads(packed(account));before=a['equity'];start_positions=json.loads(packed(a['positions']));bars={};signals={};decisions=[]
    for code,h in feeds.items():
        rows=h['bars'];i=next((i for i,b in enumerate(rows) if b['date']==day),None)
        if i is None or i==0:raise Blocked('该交易日行情缺失：'+code)
        b=rows[i];prev=rows[i-1];bars[code]=(b,prev);signals[code]=signal(rows[:i],c)
        pos=a['positions'].get(code)
        if pos:
            old=a['marks'].get(code,{})
            if prev['date']!=a['last_day'] or abs(prev['raw_close']-old.get('close',prev['raw_close']))>.02:raise Blocked('持仓历史价格修订或交易日不连续：'+code)
            factor=b['close']/b['raw_close'];prior=prev['close']/prev['raw_close']
            if abs(factor/prior-1)>.0005:raise Blocked('持仓发生公司行动/复权因子变化，需人工核对后建立新版本：'+code)
    equity_open=a['cash']+sum(p['qty']*bars[k][0]['raw_open'] for k,p in a['positions'].items())
    candidates=[]
    for code in c['codes']:
        held=code in a['positions'];target=signals[code]['long']
        if held and not target:candidates.append((code,'sell'))
        elif not held and target:candidates.append((code,'buy'))
        else:decisions.append({'code':code,'side':'hold' if held else 'flat','status':'no_order','reason':'持仓与目标一致','signal':signals[code]})
    candidates.sort(key=lambda p:0 if p[1]=='sell' else 1)
    n_orders=0;daily_fees=0;realized=0;fill_map={}
    for code,side in candidates:
        b,prev=bars[code];order={'code':code,'date':day,'side':side,'signal':signals[code],'status':'rejected','qty':0,'fees':0,'reason':''}
        reason=None
        if n_orders>=c['daily_orders']:reason='单日委托次数上限'
        else:n_orders+=1
        if b['volume']<=0:reason='零成交量或停牌'
        ratio=.2 if code.startswith(('300','301','688')) else .1
        reference=prev['raw_close']*(prev['close']/prev['raw_close'])/(b['close']/b['raw_close'])
        up=rounded_price(reference*(1+ratio));down=rounded_price(reference*(1-ratio))
        if side=='buy' and b['raw_open']>=up-.005:reason='开盘涨停，不假定能够成交'
        if side=='sell' and b['raw_open']<=down+.005:reason='开盘跌停，不假定能够成交'
        if side=='sell' and a['positions'][code]['buy_date']>=day:reason='T+1 可卖数量不足'
        price=min(up,max(down,b['raw_open']*(1+c['slippage'] if side=='buy' else 1-c['slippage'])))
        if not reason:
            if side=='buy':
                budget=min(a['cash'],equity_open*min(c['max_weight'],1/len(c['codes'])))
                minimum,lot=(200,1) if code.startswith('688') else (100,100)
                qty=max(0,math.floor((budget-c['minimum_fee'])/(price*(1+c['commission']+.00002))/lot)*lot)
                while qty>=minimum and qty*price+fee(qty*price,day,False,c['commission'],c['minimum_fee'])>budget:qty-=lot
                if qty<minimum:reason='现金或单股仓位上限不足最小申报数量'
                else:
                    costs=fee(qty*price,day,False,c['commission'],c['minimum_fee']);a['cash']-=qty*price+costs
                    a['positions'][code]={'qty':qty,'buy_date':day,'cost':qty*price+costs}
            else:
                pos=a['positions'][code];qty=pos['qty'];costs=fee(qty*price,day,True,c['commission'],c['minimum_fee']);a['cash']+=qty*price-costs;realized+=qty*price-costs-pos['cost'];del a['positions'][code]
            if not reason:
                order.update(status='filled',qty=qty,price=price,fees=costs,reason='次日开盘离线模拟成交');daily_fees+=costs;fill_map[code]=order
        if reason:order['reason']=reason
        decisions.append(order)
    a['marks']={k:{'date':day,'close':b['raw_close']} for k,(b,_) in bars.items()}
    a['equity']=a['cash']+sum(p['qty']*a['marks'][k]['close'] for k,p in a['positions'].items());a['peak']=max(a['peak'],a['equity']);a['last_day']=day
    contributions={}
    for code,(b,prev) in bars.items():
        initial=start_positions.get(code,{}).get('qty',0);pnl=initial*(b['raw_close']-prev['raw_close']);fill=fill_map.get(code)
        if fill:pnl+=(1 if fill['side']=='buy' else -1)*fill['qty']*(b['raw_close']-fill['price'])-fill['fees']
        contributions[code]=pnl
    delta=a['equity']-before;difference=delta-sum(contributions.values())
    if abs(difference)>.02:raise Blocked('日收益归因与账户净值不一致')
    drawdown=a['equity']/a['peak']-1
    return {'account':a,'day':day,'decisions':decisions,'contributions':contributions,'pnl':delta,'fees':daily_fees,'realized':realized,
            'drawdown':drawdown,'reconciliation_difference':difference,'risk_stop':drawdown<=-c['max_drawdown'],'account_before':account,
            'assumptions':'仅离线模拟。普通主板 10%、创业/科创 20% 限制；开盘封板保守不成交。当前 ST/退市标的禁止启动；公司行动或历史持仓价格修订阻断运行。无盘口、排队、冲击或实际账户成交保证。'}

class Runtime:
    def __init__(self,root,history_loader=None,calendar_loader=None,secondary_loader=None,quote_loader=None):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.db=self.root/'operations.sqlite3';self.store=self.root/'operations_store'
        self.store.mkdir(exist_ok=True);self.history_loader=history_loader;self.calendar_loader=calendar_loader;self.secondary_loader=secondary_loader;self.quote_loader=quote_loader
        self.initialize()
    def initialize(self):
        with connect(self.db) as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.executescript('''
            CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY,name TEXT,version INTEGER,config TEXT,config_hash TEXT,state TEXT,created_at TEXT,reason TEXT,due REAL DEFAULT 0,UNIQUE(name,version));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,strategy TEXT,kind TEXT,status TEXT,started TEXT,finished TEXT,snapshot TEXT,result TEXT,error TEXT,engine TEXT);
            CREATE TABLE IF NOT EXISTS accounts(strategy TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS reports(strategy TEXT,day TEXT,run TEXT,snapshot TEXT,engine TEXT,value TEXT,PRIMARY KEY(strategy,day));
            CREATE TABLE IF NOT EXISTS orders(strategy TEXT,day TEXT,code TEXT,value TEXT,PRIMARY KEY(strategy,day,code));
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,at TEXT,level TEXT,component TEXT,message TEXT);
            CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY,owner TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,strategy TEXT,kind TEXT,asof TEXT,state TEXT,created TEXT,run TEXT,error TEXT);
            ''')
            con.execute("INSERT OR IGNORE INTO settings VALUES('scheduler','true')")
    def log(self,level,component,message):
        with connect(self.db) as con:con.execute('INSERT INTO logs(at,level,component,message) VALUES(?,?,?,?)',(stamp(),level,component,str(message)[:4000]))
    def maintenance(self):
        p=self.root/'.operations-maintenance'
        return p.exists()
    def require_ready(self):
        if self.maintenance():raise Blocked('维护期间不接受写入或任务')
    @contextlib.contextmanager
    def lease(self,name,seconds=90):
        self.require_ready();owner=uuid.uuid4().hex
        with connect(self.db) as con:
            con.execute('BEGIN IMMEDIATE');row=con.execute('SELECT * FROM leases WHERE name=?',(name,)).fetchone()
            self.require_ready()
            if row and row['expires']>time.time():raise Blocked('相同任务已在运行：'+name)
            con.execute('INSERT OR REPLACE INTO leases VALUES(?,?,?)',(name,owner,time.time()+seconds))
        stop=threading.Event()
        def renew():
            while not stop.wait(10):
                try:
                    with connect(self.db) as con:con.execute('UPDATE leases SET expires=? WHERE name=? AND owner=?',(time.time()+seconds,name,owner))
                except Exception:pass
        thread=threading.Thread(target=renew,daemon=True);thread.start()
        try:yield owner
        finally:
            stop.set();thread.join(timeout=2)
            with connect(self.db) as con:con.execute('DELETE FROM leases WHERE name=? AND owner=?',(name,owner))
    def engine(self):
        files=ENGINE_FILES;sha=digest({'files':files,'python':platform.python_version()})
        p=self.store/('engine-'+sha+'.json')
        if not p.exists():
            tmp=p.with_suffix('.'+uuid.uuid4().hex+'.tmp');tmp.write_text(packed({'sha':sha,'files':files,'python':platform.python_version()}),encoding='utf-8');os.replace(tmp,p)
        stored=json.loads(p.read_text(encoding='utf-8'))
        if digest({'files':stored['files'],'python':stored['python']})!=sha:raise Blocked('归档引擎源码校验失败')
        return sha
    def create(self,name,config):
        self.require_ready();c=validate_config(config)
        if not 1<=len(name.strip())<=60:raise ValueError('版本名称 1–60 字')
        with connect(self.db) as con:
            con.execute('BEGIN IMMEDIATE');version=con.execute('SELECT COALESCE(MAX(version),0)+1 FROM strategies WHERE name=?',(name.strip(),)).fetchone()[0]
            sid=uuid.uuid4().hex;con.execute('INSERT INTO strategies VALUES(?,?,?,?,?,?,?,?,?)',(sid,name.strip(),version,packed(c),digest(c),'draft',stamp(),'新版本须先完成研究验证',0))
        self.log('info',sid,'创建不可变策略版本 v'+str(version));return sid
    def strategy(self,sid):
        with connect(self.db) as con:r=con.execute('SELECT * FROM strategies WHERE id=?',(sid,)).fetchone()
        if not r:raise ValueError('策略版本不存在')
        return {**dict(r),'config':json.loads(r['config'])}
    def enqueue(self,sid,kind,asof,request_id=None):
        self.require_ready();s=self.strategy(sid);date.fromisoformat(asof)
        if kind not in ('research','paper'):raise ValueError('任务类型无效')
        if s['state']=='archived' or (kind=='paper' and s['state']!='paper'):raise Blocked('策略状态不允许任务')
        qid=request_id or uuid.uuid4().hex
        if not re.fullmatch('[0-9a-f]{32}',qid):raise ValueError('请求编号无效')
        with connect(self.db) as con:
            existing=con.execute('SELECT * FROM requests WHERE id=?',(qid,)).fetchone()
            if existing:
                if (existing['strategy'],existing['kind'],existing['asof'])!=(sid,kind,asof):raise ValueError('同一请求编号不能用于不同任务')
            else:con.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?)',(qid,sid,kind,asof,'queued',stamp(),None,None))
        return {'request_id':qid,'state':existing['state'] if existing else 'queued','run_id':existing['run'] if existing else None}
    def freeze(self,s,asof):
        from ops_feeds import freeze_feeds
        snapshot=freeze_feeds(self,s['config'],asof)
        sha=digest(snapshot);target=self.store/(sha+'.json');tmp=self.store/(sha+'.'+uuid.uuid4().hex+'.tmp')
        if not target.exists():tmp.write_text(packed(snapshot),encoding='utf-8');os.replace(tmp,target)
        self.snapshot(sha)
        return sha,snapshot
    def snapshot(self,sha):
        if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('快照编号无效')
        v=json.loads((self.store/(sha+'.json')).read_text(encoding='utf-8'))
        if digest(v)!=sha:raise Blocked('数据快照校验失败')
        return v
    def run(self,sid,kind,asof):
        if kind not in ('research','paper'):raise ValueError('未知任务类型')
        date.fromisoformat(asof);rid=uuid.uuid4().hex;engine=self.engine()
        with self.lease('strategy:'+sid):
            s=self.strategy(sid)
            if s['state']=='archived' or (kind=='paper' and s['state']!='paper'):raise Blocked('策略状态不允许此任务')
            with connect(self.db) as con:con.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)',(rid,sid,kind,'running',stamp(),None,None,None,None,engine))
            try:
                sha,snapshot=self.freeze(s,asof)
                with connect(self.db) as con:con.execute('UPDATE runs SET snapshot=? WHERE id=?',(sha,rid))
                if not snapshot['gate']['passed']:raise Blocked('数据质量闸门未通过：'+'；'.join(c['check'] for c in snapshot['gate']['checks'] if not c['pass']))
                if kind=='research':
                    result=research_result(snapshot,s['config'])
                    with connect(self.db) as con:
                        current=con.execute('SELECT state FROM strategies WHERE id=?',(sid,)).fetchone()[0]
                        if current=='draft':con.execute("UPDATE strategies SET state='validated',reason='数据与研究流程验证完成，尚未启动模拟' WHERE id=?",(sid,))
                else:result=self.advance(sid,snapshot,sha,engine,rid)
                with connect(self.db) as con:con.execute('UPDATE runs SET status=?,finished=?,result=? WHERE id=?',('success',stamp(),packed(result),rid))
                self.log('info',sid,kind+' 完成，任务 '+rid)
            except Exception as exc:
                status='blocked' if isinstance(exc,(Blocked,ValueError)) else 'failed'
                with connect(self.db) as con:
                    con.execute('UPDATE runs SET status=?,finished=?,error=? WHERE id=?',(status,stamp(),str(exc)[:4000],rid))
                    con.execute('UPDATE strategies SET due=? WHERE id=?',(time.time()+1800,sid))
                    if kind=='paper':con.execute("UPDATE strategies SET state='paused',reason=? WHERE id=?",('任务阻断，须核对后手工恢复：'+str(exc)[:1000],sid))
                self.log('error',sid,str(exc));return {'run_id':rid,'status':status,'error':str(exc)}
        return {'run_id':rid,'status':'success'}
    def advance(self,sid,snapshot,sha,engine,rid):
        s=self.strategy(sid);c=s['config'];expected=snapshot['gate']['expected_day'];processed=[]
        while True:
            with connect(self.db) as con:
                con.execute('BEGIN IMMEDIATE');current=con.execute('SELECT state FROM strategies WHERE id=?',(sid,)).fetchone()[0]
                if current!='paper':raise Blocked('策略已暂停，停止推进')
                raw=con.execute('SELECT value FROM accounts WHERE strategy=?',(sid,)).fetchone()
                if not raw:raise Blocked('模拟账户未初始化')
                account=json.loads(raw[0]);days=[d for d in snapshot['calendar']['days'] if account['last_day']<d<=expected]
                if account.get('engine')!=engine:raise Blocked('引擎已升级，须重新研究验证并手工恢复模拟')
                if not days:break
                day=min(days);result=paper_step(account,snapshot['feeds'],day,c)
                con.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)',(sid,day,rid,sha,engine,packed(result)))
                for order in result['decisions']:
                    if order['status']!='no_order':con.execute('INSERT INTO orders VALUES(?,?,?,?)',(sid,day,order['code'],packed(order)))
                con.execute('UPDATE accounts SET value=? WHERE strategy=?',(packed(result['account']),sid));processed.append(day)
                if result['risk_stop']:
                    con.execute("UPDATE strategies SET state='paused',reason='触发最大回撤阈值' WHERE id=?",(sid,));break
        with connect(self.db) as con:con.execute('UPDATE strategies SET due=? WHERE id=?',(time.time()+300,sid))
        return {'processed_days':processed,'last_confirmed_day':expected,'idempotency':'策略版本＋交易日＋代码唯一；账户与订单、归因日报同一事务'}
    def transition(self,sid,state):
        self.require_ready()
        if state=='paused':
            with connect(self.db) as con:
                con.execute('BEGIN IMMEDIATE');row=con.execute('SELECT state FROM strategies WHERE id=?',(sid,)).fetchone()
                if not row or row[0]!='paper':raise ValueError('仅运行中的模拟版本可以暂停')
                con.execute("UPDATE strategies SET state='paused',reason='用户暂停；当前日事务完成后不再推进' WHERE id=?",(sid,))
            self.log('warning',sid,'用户暂停策略');return
        with self.lease('strategy:'+sid):
            s=self.strategy(sid)
            allowed={'draft':{'archived'},'validated':{'paper','archived'},'paper':{'paused'},'paused':{'paper','archived'},'archived':set()}
            if state not in allowed[s['state']]:raise ValueError('不允许的状态转换')
            if state=='paper':
                with connect(self.db) as con:r=con.execute("SELECT * FROM runs WHERE strategy=? AND kind='research' AND status='success' ORDER BY started DESC,rowid DESC LIMIT 1",(sid,)).fetchone()
                if not r or r['engine']!=self.engine():raise Blocked('需要在当前引擎上完成研究验证')
                snapshot=self.snapshot(r['snapshot']);c=s['config'];day=snapshot['gate']['expected_day']
                if not snapshot['gate']['passed']:raise Blocked('研究快照不合格')
                check_day=now().date()
                if (now().hour,now().minute)<(15,20):check_day-=timedelta(days=1)
                latest=max(d for d in snapshot['calendar']['days'] if d<=check_day.isoformat())
                age=(now()-datetime.fromisoformat(snapshot['frozen_at'])).total_seconds()
                if day!=latest or not 0<=age<=12*3600:raise Blocked('启动或恢复前须用最近已收盘交易日重新研究验证')
                with connect(self.db) as con:
                    recovery=con.execute("SELECT value FROM settings WHERE key='recovery_at'").fetchone()
                    if recovery and r['started']<=recovery[0]:raise Blocked('恢复副本须重新完成研究验证')
                    account=con.execute('SELECT value FROM accounts WHERE strategy=?',(sid,)).fetchone()
                    if account:
                        a=json.loads(account[0])
                        if a['equity']/a['peak']-1<=-c['max_drawdown']:raise Blocked('此版本已触发最大回撤阈值，不能直接恢复')
                        a['engine']=self.engine();con.execute('UPDATE accounts SET value=? WHERE strategy=?',(packed(a),sid))
                    if not con.execute('SELECT 1 FROM accounts WHERE strategy=?',(sid,)).fetchone():
                        a={'cash':c['capital'],'equity':c['capital'],'peak':c['capital'],'positions':{},'marks':{},'last_day':day,'engine':self.engine()}
                        con.execute('INSERT INTO accounts VALUES(?,?)',(sid,packed(a)))
            with connect(self.db) as con:con.execute('UPDATE strategies SET state=?,reason=?,due=0 WHERE id=?',(state,'用户状态转换：'+state,sid))
        self.log('info',sid,'状态转换：'+state)
    def replay(self,rid):
        with connect(self.db) as con:r=con.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not r or r['status']!='success':raise ValueError('只可重放成功任务')
        if r['engine']!=self.engine():raise Blocked('引擎版本已变化；原引擎源码清单已归档，不能冒充当前复现')
        snapshot=self.snapshot(r['snapshot']);s=self.strategy(r['strategy'])
        if r['kind']=='research':
            output=research_result(snapshot,s['config']);original=json.loads(r['result']);return {'match':digest(output)==digest(original),'result_hash':digest(output),'snapshot_hash':r['snapshot'],'engine_hash':r['engine']}
        with connect(self.db) as con:rows=con.execute('SELECT * FROM reports WHERE run=? ORDER BY day',(rid,)).fetchall()
        matches=[]
        for row in rows:
            saved=json.loads(row['value']);output=paper_step(saved['account_before'],snapshot['feeds'],row['day'],s['config']);matches.append(digest(output)==digest(saved))
        return {'match':all(matches),'days':len(matches),'snapshot_hash':r['snapshot'],'engine_hash':r['engine']}
    def detail(self,rid):
        with connect(self.db) as con:r=con.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not r:raise ValueError('任务不存在')
        out=dict(r)
        if out['result']:out['result']=json.loads(out['result'])
        if out['snapshot']:
            snap=self.snapshot(out['snapshot']);out['gate']=snap['gate'];out['manifest']={'snapshot_hash':out['snapshot'],'config':snap['config'],'sources':{k:{a:v.get(a) for a in ('source','fetched_at','stale')} for k,v in snap['feeds'].items()},'calendar_source':snap['calendar'].get('source','未标注')}
        return out
    def dashboard(self):
        with connect(self.db) as con:
            strategies=[dict(r) for r in con.execute('SELECT * FROM strategies ORDER BY created_at DESC,rowid DESC')]
            for s in strategies:s['config']=json.loads(s['config'])
            runs=[dict(r) for r in con.execute('SELECT id,strategy,kind,status,started,finished,error,snapshot,engine FROM runs ORDER BY rowid DESC LIMIT 60')]
            reports=[{**dict(r),'value':json.loads(r['value'])} for r in con.execute('SELECT * FROM reports ORDER BY day DESC,rowid DESC LIMIT 250')]
            accounts=[{'strategy':r[0],**json.loads(r[1])} for r in con.execute('SELECT * FROM accounts')]
            logs=[dict(r) for r in con.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 80')]
            heartbeat=con.execute("SELECT value FROM settings WHERE key='heartbeat'").fetchone();enabled=con.execute("SELECT value FROM settings WHERE key='scheduler'").fetchone()[0]
            worker_lease=con.execute("SELECT owner,expires FROM leases WHERE name='worker'").fetchone()
            requests=[dict(r) for r in con.execute('SELECT * FROM requests ORDER BY rowid DESC LIMIT 60')]
            dead=con.execute("SELECT COUNT(*) FROM runs WHERE status='running' AND started<?",((now()-timedelta(minutes=30)).isoformat(timespec='seconds'),)).fetchone()[0]
        hb=json.loads(heartbeat[0]) if heartbeat else None
        reconciliation=[]
        for a in accounts:
            calculated=a['cash']+sum(p['qty']*a['marks'].get(code,{}).get('close',0) for code,p in a['positions'].items())
            reconciliation.append({'strategy':a['strategy'],'difference':a['equity']-calculated,'passed':abs(a['equity']-calculated)<=.02})
        return {'strategies':strategies,'runs':runs,'reports':reports,'accounts':accounts,'logs':logs,'requests':requests,'heartbeat':hb,'worker_alive':bool(hb and worker_lease and hb['owner']==worker_lease[0] and worker_lease[1]>time.time() and time.time()-hb['epoch']<45),'scheduler_enabled':enabled=='true','long_running':dead,
                'reconciliation':reconciliation,'maintenance':self.maintenance(),'data_root':str(self.root),'asof':stamp(),'note':'独立本地后台进程需要电脑保持开机、网络可用；不是云端托管。市场数据质量闸门和历史版本快照仅用于本平台新建任务；旧研究页面仍可查看未经此闸门认证的数据。'}
