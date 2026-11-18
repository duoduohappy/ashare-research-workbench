"""Checksummed backups and non-destructive recovery drills."""
import contextlib,hashlib,json,os,re,sqlite3,time,uuid,zipfile
from pathlib import Path,PurePosixPath
from ops_engine import Blocked,connect,packed,stamp

@contextlib.contextmanager
def maintenance(rt):
    flag=rt.root/'.operations-maintenance';owner=uuid.uuid4().hex
    try:fd=os.open(flag,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise Blocked('已有维护任务；若曾断电，请核验进程后处理维护标记，不能强行覆盖')
    with os.fdopen(fd,'w') as f:f.write(owner)
    try:
        with connect(rt.db) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM leases WHERE name LIKE 'strategy:%' AND expires>?",(time.time(),)).fetchone():raise Blocked('策略任务运行中，请等待完成后备份')
        yield
    finally:
        if flag.exists() and flag.read_text()==owner:flag.unlink()

def list_backups(rt):
    folder=rt.root/'backups';folder.mkdir(exist_ok=True)
    return [{'id':p.name,'bytes':p.stat().st_size} for p in sorted(folder.glob('backup-*.zip'),reverse=True)]

def backup_path(rt,identifier):
    if not re.fullmatch(r'backup-[0-9]{8}T[0-9]{6}-[0-9a-f]{8}\.zip',identifier):raise ValueError('备份编号无效')
    p=(rt.root/'backups'/identifier).resolve()
    if p.parent!=(rt.root/'backups').resolve() or not p.is_file():raise ValueError('备份不存在')
    return p

def create_backup(rt):
    with maintenance(rt):
        folder=rt.root/'backups';folder.mkdir(exist_ok=True);work=folder/('staging-'+uuid.uuid4().hex);work.mkdir()
        items={}
        for name in ('operations.sqlite3','workspace.sqlite3'):
            source=rt.root/name
            if not source.exists():continue
            target=work/name
            with contextlib.closing(sqlite3.connect(source)) as src,contextlib.closing(sqlite3.connect(target)) as dst:src.backup(dst);dst.commit()
            items[name]=target.read_bytes()
        for p in rt.store.glob('*.json'):items['operations_store/'+p.name]=p.read_bytes()
        manifest={'created_at':stamp(),'version':1,'files':{name:hashlib.sha256(value).hexdigest() for name,value in items.items()},'scope':'独立运营数据库、手工模拟账本及不可变快照/引擎清单；不含可重建行情缓存'}
        from ops_engine import now
        identifier='backup-'+now().strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.zip';target=folder/identifier
        partial=target.with_suffix('.partial')
        with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as z:
            for name,value in items.items():z.writestr(name,value)
            z.writestr('manifest.json',packed(manifest))
        with zipfile.ZipFile(partial) as z:
            if z.testzip():raise Blocked('备份压缩包校验失败')
        os.replace(partial,target)
        # Only known files in this newly-created staging folder are removed.
        for p in work.iterdir():p.unlink()
        work.rmdir()
    rt.log('info','backup','创建备份 '+identifier);return {'id':identifier,'bytes':target.stat().st_size,'manifest':manifest}

def restore_drill(rt,identifier):
    source=backup_path(rt,identifier)
    with zipfile.ZipFile(source) as z:
        if len(z.namelist())!=len(set(z.namelist())):raise Blocked('备份存在重复成员')
        if sum(i.file_size for i in z.infolist())>500*1024*1024:raise Blocked('备份超过当前恢复上限 500 MB')
        manifest=json.loads(z.read('manifest.json'));names=manifest.get('files',{})
        if set(z.namelist())!=set(names)|{'manifest.json'}:raise Blocked('备份清单与成员不一致')
        verified={}
        for name,sha in names.items():
            p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:raise Blocked('不安全备份路径')
            if name not in ('operations.sqlite3','workspace.sqlite3') and not re.fullmatch(r'operations_store/(?:engine-)?[a-f0-9]{64}\.json|operations_store/calendar\.json',name):raise Blocked('不支持的备份文件')
            value=z.read(name)
            if hashlib.sha256(value).hexdigest()!=sha:raise Blocked('备份校验失败：'+name)
            verified[name]=value
    if 'operations.sqlite3' not in verified:raise Blocked('缺少运营数据库')
    recovered=rt.root/'recovered'/uuid.uuid4().hex;recovered.mkdir(parents=True)
    for name,value in verified.items():
        path=recovered/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
    for name in ('operations.sqlite3','workspace.sqlite3'):
        p=recovered/name
        if p.exists():
            with contextlib.closing(sqlite3.connect(p)) as c:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise Blocked('恢复副本数据库完整性检查失败')
    with connect(recovered/'operations.sqlite3') as c:
        original_strategies=c.execute('SELECT COUNT(*) FROM strategies').fetchone()[0]
        c.execute("UPDATE strategies SET state='paused',reason='恢复副本：必须核对并重新验证后才能启动' WHERE state='paper'")
        c.execute("UPDATE requests SET state='failed',error='恢复副本不自动重复任务' WHERE state IN ('queued','executing')")
        c.execute('DELETE FROM leases');c.execute("DELETE FROM settings WHERE key='heartbeat'");c.execute("INSERT OR REPLACE INTO settings VALUES('scheduler','false')")
        c.execute("INSERT OR REPLACE INTO settings VALUES('recovery_at',?)",(stamp(),))
    result={'path':str(recovered),'database_integrity':'ok','strategies':original_strategies,'files':len(verified),
            'active_data_unchanged':True,'instructions':'副本已恢复且调度关闭。停止原服务后，可用 python server.py --data-root "'+str(recovered)+'" 启动恢复副本；先核对数据与账户，再重新研究验证、手工启用调度。'}
    rt.log('info','recovery','恢复演练通过：'+str(recovered));return result
