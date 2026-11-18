"""Local, checksummed research records. Never execute stored source or user code."""
import hashlib,json,math,os,platform,re,threading,uuid
from datetime import date,datetime,timezone,timedelta
from pathlib import Path
import numpy as np
import scipy,sklearn
from threadpoolctl import threadpool_limits
from factor_validation import factor_validation
from portfolio_optimization import portfolio_experiment
from regime_research import regime_experiment
from strategy_validation import strategy_validation

ROOT=Path(__file__).resolve().parent
SOURCE_FILES=('research_evidence.py','factor_validation.py','portfolio_optimization.py','regime_research.py','strategy_validation.py','model.py','research.py')
LOCK=threading.RLock()
KINDS={'factor':'因子验证','portfolio':'组合算法实验','regime':'状态算法对照','strategy':'策略稳健性验收'}

def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(packed(value).encode('utf-8')).hexdigest()
def stamp():return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
def disk_sources():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES}

# Keep the fingerprint of sources loaded by this process; reject hot-edited code.
LOADED_SOURCES=disk_sources()

def engine_manifest():
    if disk_sources()!=LOADED_SOURCES:raise ValueError('研究引擎源码在服务启动后已变化，请重启 Python 服务再分析或复现')
    return {'files':LOADED_SOURCES.copy(),'python':platform.python_version(),'machine':platform.machine(),
            'numpy':np.__version__,'scipy':scipy.__version__,'scikit_learn':sklearn.__version__}

def normalize_config(kind,config,codes):
    defaults={
        'factor':{'factor':'momentum20','horizon':5},
        'portfolio':{'start':'','lookback':126,'interval':21,'cap':.5,'cost_bps':10.,'capital':300000.,'estimator':'ledoit_wolf'},
        'regime':{'code':codes[0],'lookback':126,'threshold':.05},
        'strategy':{'code':codes[0],'window':20,'threshold':.05,'lookback':126,'periods':[20,60],'momenta':[10,20],'capital':300000.,'filtered':True,'limit':.1}}
    if kind not in defaults or not isinstance(config,dict):raise ValueError('研究类型或参数格式无效')
    if set(config)-set(defaults[kind]):raise ValueError('包含该研究类型不支持的参数')
    result={**defaults[kind],**config}
    if 'code' in result and result['code'] not in codes:raise ValueError('分析标的不在冻结股票池中')
    return json.loads(packed(result))

def evaluate(payload,kind,config):
    series={c:h['bars'] for c,h in payload['feeds'].items()};end=payload['asof']
    if kind=='factor':return factor_validation(series,end,**config)
    if kind=='portfolio':return portfolio_experiment(series,end,**config)
    c={**config};code=c.pop('code')
    if kind=='regime':return regime_experiment(series[code],end,**c)
    if kind=='strategy':return strategy_validation(series[code],end,code,**c)
    raise ValueError('未知研究类型')

def summary(kind,result):
    if kind=='factor':return {'labels':['平均 IC','平均 Rank IC'],'values':[result['summary']['mean_ic'],result['summary']['mean_rank_ic']],'unit':'相关系数'}
    if kind=='portfolio':return {'labels':[v['name'] for v in result['results'].values()],'values':[v['metrics']['return']*100 for v in result['results'].values()],'unit':'收益 %'}
    if kind=='regime':return {'labels':[result['names'][k] for k in result['results']],'values':[v['metrics']['brier'] for v in result['results'].values()],'unit':'Brier'}
    return {'labels':['平均单折收益','中位单折收益','最差单折收益'],'values':[result['summary'][k]*100 for k in ('mean_fold_return','median_fold_return','worst_fold_return')],'unit':'收益 %'}

class EvidenceStore:
    def __init__(self,root):
        self.root=Path(root)/'research_evidence'
        for folder in ('snapshots','runs','checks'):(self.root/folder).mkdir(parents=True,exist_ok=True)

    def path(self,folder,identifier):
        if folder not in ('snapshots','runs','checks') or not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{64}',identifier):raise ValueError('证据编号无效')
        return self.root/folder/(identifier+'.json')

    def read(self,folder,identifier):
        p=self.path(folder,identifier)
        if not p.is_file() or p.stat().st_size>20*1024*1024:raise ValueError('证据不存在或超过大小限制')
        try:record=json.loads(p.read_text(encoding='utf-8'))
        except (OSError,ValueError):raise ValueError('证据文件无法读取') from None
        if not isinstance(record,dict) or set(record)!= {'record','checksum'} or digest(record['record'])!=record['checksum']:
            raise ValueError('证据记录校验失败')
        value=record['record']
        if folder=='snapshots' and digest(value['payload'])!=identifier:raise ValueError('快照数据内容校验失败')
        if folder=='runs' and digest(value['result'])!=value['result_sha']:raise ValueError('研究结果校验失败')
        return value

    def write(self,folder,identifier,record):
        target=self.path(folder,identifier)
        data=packed({'record':record,'checksum':digest(record)}).encode('utf-8')
        if len(data)>20*1024*1024:raise ValueError('证据超过 20 MB 限制')
        temp=target.with_name(identifier+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_bytes(data)
            try:
                # Windows rename is atomic and refuses an existing destination.
                # POSIX rename replaces files, so use create-only link there.
                if os.name=='nt':os.rename(temp,target)
                else:os.link(temp,target)
            except FileExistsError:pass
        finally:
            if temp.exists():temp.unlink()
        return self.read(folder,identifier)

    def capture(self,feeds,asof,demo):
        date.fromisoformat(asof)
        if not isinstance(demo,bool) or not isinstance(feeds,dict) or not 1<=len(feeds)<=8:raise ValueError('快照需要 1–8 个标的及明确的数据模式')
        clean={};observed={}
        for code,h in sorted(feeds.items()):
            if not re.fullmatch(r'\d{6}',code):raise ValueError('股票代码无效')
            bars=[]
            for b in h['bars']:
                if b['date']>asof:continue
                date.fromisoformat(b['date']);row={'date':b['date']}
                for k in ('close','raw_open','raw_close','raw_high','raw_low','volume'):
                    v=b.get(k)
                    if not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) or v<0 or (k!='volume' and v==0):raise ValueError(code+' 缺少有效价格或成交量')
                    row[k]=v
                if not row['raw_low']<=min(row['raw_open'],row['raw_close'])<=max(row['raw_open'],row['raw_close'])<=row['raw_high']:raise ValueError(code+' 原始 OHLC 不一致')
                bars.append(row)
            dates=[b['date'] for b in bars]
            if not 30<=len(bars)<=2000 or dates!=sorted(set(dates)):raise ValueError(code+' 需要 30–2000 根日期递增且不重复的日线')
            clean[code]={'bars':bars,'source':str(h.get('source','未知来源'))[:300]}
            observed[code]={k:h.get(k) for k in ('fetched_at','stale','cached')}
        payload={'schema':1,'asof':asof,'demo':demo,'feeds':clean}
        identifier=digest(payload)
        with LOCK:
            exists=self.path('snapshots',identifier).exists()
            record=self.write('snapshots',identifier,{'payload':payload,'created_at':stamp(),'observed':observed})
        return {'snapshot_id':identifier,'reused':exists,**self.snapshot_view(identifier,record)}

    def snapshot_view(self,identifier,record=None):
        record=record or self.read('snapshots',identifier);p=record['payload']
        days=sorted({b['date'] for h in p['feeds'].values() for b in h['bars']})[-120:]
        rows=[]
        for c,h in p['feeds'].items():
            dates={b['date'] for b in h['bars']}
            rows.append({'code':c,'rows':len(h['bars']),'first':h['bars'][0]['date'],'last':h['bars'][-1]['date'],
                'source':h['source'],'presence':[int(d in dates) for d in days], 'stale':record['observed'][c].get('stale') is True})
        return {'id':identifier,'asof':p['asof'],'demo':p['demo'],'created_at':record['created_at'],'rows':rows,'dates':days}

    def inventory(self):
        snapshots=[];runs=[];checks=[];warnings=[]
        for folder,target in (('snapshots',snapshots),('runs',runs),('checks',checks)):
            for path in sorted((self.root/folder).glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:
                if not re.fullmatch('[a-f0-9]{64}',path.stem):continue
                try:
                    r=self.read(folder,path.stem)
                    if folder=='snapshots':target.append(self.snapshot_view(path.stem,r))
                    elif folder=='runs':target.append({'id':path.stem,'snapshot_id':r['snapshot_id'],'kind':r['kind'],'created_at':r['created_at'],'asof':r['asof'],'demo':r['demo'],'result_sha':r['result_sha']})
                    else:target.append({'id':path.stem,'run_id':r['run_id'],'created_at':r['created_at'],'status':r['status']})
                except (ValueError,KeyError,TypeError):warnings.append(folder+'/'+path.stem[:12]+' 记录无法校验，已从可选列表中排除')
        return {'snapshots':snapshots,'runs':runs,'checks':checks,'warnings':warnings}

    def run(self,snapshot_id,kind,config):
        with LOCK,threadpool_limits(limits=1):
            snap=self.read('snapshots',snapshot_id);p=snap['payload']
            config=normalize_config(kind,config,sorted(p['feeds']))
            engine=engine_manifest();result=evaluate(p,kind,config)
            record={'schema':1,'snapshot_id':snapshot_id,'kind':kind,'config':config,'engine':engine,'engine_sha':digest(engine),
                'asof':p['asof'],'demo':p['demo'],'created_at':stamp(),'result':result,'result_sha':digest(result), 'summary':summary(kind,result)}
            identifier=digest({'nonce':uuid.uuid4().hex,'record':record})
            self.write('runs',identifier,record)
        return {'run_id':identifier,**record}

    def replay(self,run_id):
        with LOCK,threadpool_limits(limits=1):
            original=self.read('runs',run_id);snap=self.read('snapshots',original['snapshot_id'])
            if digest(original['engine'])!=original['engine_sha']:raise ValueError('原计算环境指纹校验失败')
            if original['asof']!=snap['payload']['asof'] or original['demo']!=snap['payload']['demo']:raise ValueError('研究记录与快照模式不一致')
            current=engine_manifest();same=digest(current)==original['engine_sha']
            result=evaluate(snap['payload'],original['kind'],original['config']) if same else None
            actual=digest(result) if same else None
            match=actual==original['result_sha'] if same else None
            check={'run_id':run_id,'created_at':stamp(),'status':('matched' if match else 'mismatch') if same else 'engine_changed',
                'snapshot_id':original['snapshot_id'],'expected_sha':original['result_sha'],'actual_sha':actual,
                'checks':[{'label':'研究记录校验','passed':True},{'label':'冻结数据校验','passed':True},
                          {'label':'计算环境一致','passed':same},{'label':'结果完整哈希一致','passed':match}],
                'original_summary':original['summary'],'replayed_summary':summary(original['kind'],result) if same else None}
            check_id=digest({'nonce':uuid.uuid4().hex,'check':check})
            self.write('checks',check_id,check)
        return {'check_id':check_id,**check}

    def compare(self,left_id,right_id):
        left=self.read('snapshots',left_id)['payload'];right=self.read('snapshots',right_id)['payload']
        if left['demo']!=right['demo']:raise ValueError('演示与真实快照不能做数据修订比较')
        details=[];rows=[]
        for code in sorted(set(left['feeds'])|set(right['feeds'])):
            a={b['date']:b for b in left['feeds'].get(code,{}).get('bars',[])}
            b={r['date']:r for r in right['feeds'].get(code,{}).get('bars',[])}
            added=sorted(set(b)-set(a));removed=sorted(set(a)-set(b));changed=[]
            for day in sorted(set(a)&set(b)):
                fields=[k for k in a[day] if k!='date' and a[day][k]!=b[day][k]]
                if fields:
                    item={'code':code,'date':day,'fields':fields,'close_revision':b[day]['close']/a[day]['close']-1,'left':a[day],'right':b[day]}
                    changed.append(item);details.append(item)
            rows.append({'code':code,'added':len(added),'removed':len(removed),'changed':len(changed),'added_dates':added,'removed_dates':removed})
        return {'left_id':left_id,'right_id':right_id,'left_asof':left['asof'],'right_asof':right['asof'],'demo':left['demo'],'rows':rows,'changes':details,
            'note':'新增/删除可能来自截止日、上市、停牌或缺失；历史复权价改变可能来自公司行动或供应商修订。本图只描述当前规范化版本差异，不将其自动判为数据错误，也不能还原原始历史 PIT。'}
