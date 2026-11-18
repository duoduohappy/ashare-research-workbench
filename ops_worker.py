"""Independent local worker; heartbeat and DB lease avoid duplicate workers."""
import argparse,json,os,threading,time,uuid
from pathlib import Path
from ops_engine import Runtime,Blocked,connect,packed,stamp,now

def make_runtime(root):
    from server import quote
    return Runtime(root,quote_loader=quote)

def tick(rt):
    if rt.maintenance():return
    with connect(rt.db) as c:
        enabled=c.execute("SELECT value FROM settings WHERE key='scheduler'").fetchone()[0]
        rows=c.execute("SELECT id,config FROM strategies WHERE state='paper' AND due<=?",(time.time(),)).fetchall()
    if enabled!='true':return
    with connect(rt.db) as c:
        c.execute('BEGIN IMMEDIATE');queued=c.execute("SELECT * FROM requests WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
        if queued:c.execute("UPDATE requests SET state='executing' WHERE id=?",(queued['id'],))
    if queued:
        try:
            result=rt.run(queued['strategy'],queued['kind'],queued['asof'])
            with connect(rt.db) as c:c.execute('UPDATE requests SET state=?,run=?,error=? WHERE id=?',(result['status'],result.get('run_id'),result.get('error'),queued['id']))
            committed=has_reports(rt,result.get('run_id'))
            if result['status']=='success' or committed:daily_backup(rt,force=committed)
        except Exception as exc:
            with connect(rt.db) as c:c.execute("UPDATE requests SET state='failed',error=? WHERE id=?",(str(exc)[:4000],queued['id']))
        return
    for row in rows:
        config=json.loads(row['config']);asof=now().date().isoformat()
        # Before the daily close buffer, use the preceding calendar day.
        if (now().hour,now().minute)<(15,20):
            from datetime import timedelta
            asof=(now().date()-timedelta(days=1)).isoformat()
        try:
            from ops_feeds import calendar,demo_calendar
            cal=demo_calendar() if config['mode']=='demo' else calendar(rt)
            expected=max(d for d in cal['days'] if d<=asof)
            with connect(rt.db) as c:a=c.execute('SELECT value FROM accounts WHERE strategy=?',(row['id'],)).fetchone()
            if a and json.loads(a[0])['last_day']>=expected:
                with connect(rt.db) as c:c.execute('UPDATE strategies SET due=? WHERE id=?',(time.time()+300,row['id']))
                continue
            outcome=rt.run(row['id'],'paper',asof)
            committed=has_reports(rt,outcome.get('run_id'))
            if outcome['status']=='success' or committed:daily_backup(rt,force=committed)
        except Exception as exc:
            rt.log('error','scheduler',str(exc))
            with connect(rt.db) as c:c.execute('UPDATE strategies SET due=? WHERE id=?',(time.time()+1800,row['id']))

def has_reports(rt,rid):
    if not rid:return False
    with connect(rt.db) as c:return c.execute('SELECT 1 FROM reports WHERE run=? LIMIT 1',(rid,)).fetchone() is not None

def daily_backup(rt,force=False):
    try:
        with connect(rt.db) as c:last=c.execute("SELECT value FROM settings WHERE key='last_backup_day'").fetchone()
        today=now().date().isoformat()
        if last and last[0]==today and not force:return
        from ops_storage import create_backup
        create_backup(rt)
        with connect(rt.db) as c:c.execute("INSERT OR REPLACE INTO settings VALUES('last_backup_day',?)",(today,))
    except Exception as exc:rt.log('error','backup','自动备份失败：'+str(exc))

def run_worker(root,once=False):
    rt=make_runtime(root)
    try:
        with rt.lease('worker',90) as owner:
            stop=threading.Event()
            def beat():
                while not stop.is_set():
                    try:
                        with connect(rt.db) as c:c.execute("INSERT OR REPLACE INTO settings VALUES('heartbeat',?)",(packed({'at':stamp(),'epoch':time.time(),'pid':os.getpid(),'owner':owner}),))
                    except Exception:pass
                    stop.wait(10)
            t=threading.Thread(target=beat,daemon=True);t.start()
            rt.log('info','worker','后台进程启动；不连接任何实盘账户')
            # Recover tasks abandoned by a terminated process, only after lease expiry.
            with connect(rt.db) as c:
                c.execute("UPDATE requests SET state='queued',error='上一工作进程中断，已重新排队' WHERE state='executing'")
                abandoned=c.execute("SELECT id,strategy FROM runs WHERE status='running'").fetchall()
                for r in abandoned:
                    lease=c.execute('SELECT expires FROM leases WHERE name=?',('strategy:'+r['strategy'],)).fetchone()
                    if not lease or lease[0]<time.time():c.execute("UPDATE runs SET status='failed',finished=?,error='上次进程中断；已提交的日事务仍保留，可从账户游标恢复' WHERE id=?",(stamp(),r['id']))
            try:
                while True:
                    with connect(rt.db) as c:requested=c.execute("SELECT value FROM settings WHERE key='stop_worker'").fetchone()
                    if requested and requested[0]=='true':break
                    try:tick(rt)
                    except Exception as exc:rt.log('error','worker',str(exc))
                    if once:break
                    time.sleep(15)
            finally:stop.set();t.join(timeout=2)
    except Blocked as exc:
        print(str(exc),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(Path(__file__).parent));p.add_argument('--once',action='store_true');a=p.parse_args();run_worker(Path(a.root),a.once)
