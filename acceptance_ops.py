"""Isolated end-to-end acceptance; never modifies the user operations DB."""

def main():
    import json,os,socket,sqlite3,subprocess,sys,time,uuid
    from pathlib import Path
    from datetime import timedelta
    import requests

    APP=Path(__file__).resolve().parent
    sys.path.insert(0,str(APP))
    from ops_engine import Runtime,connect,packed,now
    from ops_feeds import demo_calendar
    ROOT=APP/'acceptance_runs'/('run-'+uuid.uuid4().hex[:8]);ROOT.mkdir(parents=True)
    s=requests.Session();s.trust_env=False
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));PORT=sock.getsockname()[1]
    BASE=f'http://127.0.0.1:{PORT}'
    children=[];evidence=[]
    def check(name,value=True):
        if not value:raise AssertionError(name)
        evidence.append(name);print('PASS '+name,flush=True)
    def spawn(script,args):
        log=(ROOT/(script+'.log')).open('ab')
        try:p=subprocess.Popen([sys.executable,str(APP/script),*args],cwd=APP,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        finally:log.close()
        children.append(p);return p
    def api(body):
        r=s.post(BASE+'/api/ops',json=body,timeout=60)
        if not r.ok:raise RuntimeError(r.text)
        return r.json()
    def ready():
        for _ in range(60):
            try:return api({'action':'status'})
            except requests.RequestException:time.sleep(.3)
        raise RuntimeError('Server not ready')
    def wait_request(qid,timeout=90,offline=False):
        until=time.time()+timeout
        while time.time()<until:
            if offline:
                with connect(ROOT/'operations.sqlite3') as c:r=c.execute('SELECT * FROM requests WHERE id=?',(qid,)).fetchone()
                row=dict(r) if r else None
            else:row=next((r for r in api({'action':'status'})['requests'] if r['id']==qid),None)
            if row and row['state'] not in ('queued','executing'):
                if row['state']!='success':raise AssertionError(str(row))
                return row
            time.sleep(1)
        raise TimeoutError('Task did not complete: '+qid)
    try:
        server=spawn('server.py',['--port',str(PORT),'--data-root',str(ROOT),'--no-worker']);ready()
        worker=spawn('ops_worker.py',['--root',str(ROOT)])
        end=now().date()
        if (now().hour,now().minute)<(15,20):end-=timedelta(days=1)
        days=demo_calendar()['days'];end=max(d for d in days if d<=end.isoformat())
        sid=api({'action':'create','name':'自动验收（隔离演示）','config':{'codes':['000001'],'mode':'demo','threshold':.005,'max_weight':1,'max_drawdown':.8}})['strategy_id']
        qid=uuid.uuid4().hex;q=api({'action':'queue','strategy_id':sid,'kind':'research','asof':end,'request_id':qid});r=wait_request(qid)
        check('Durable research queue completed')
        d=api({'action':'detail','run_id':r['run']});check('Data gate and immutable manifest',d['gate']['passed'] and len(d['snapshot'])==64)
        check('Frozen snapshot replay',api({'action':'replay','run_id':r['run']})['match'])
        api({'action':'scheduler','enabled':False});api({'action':'transition','strategy_id':sid,'state':'paper'})
        # A controlled fixture simulates 20 missed trading days. No user account touched.
        anchor=[d for d in days if d<=end][-21]
        with connect(ROOT/'operations.sqlite3') as c:
            raw=json.loads(c.execute('SELECT value FROM accounts WHERE strategy=?',(sid,)).fetchone()[0]);raw['last_day']=anchor
            c.execute('UPDATE accounts SET value=? WHERE strategy=?',(packed(raw),sid))
        api({'action':'scheduler','enabled':True})
        qid=uuid.uuid4().hex;api({'action':'queue','strategy_id':sid,'kind':'paper','asof':end,'request_id':qid})
        server.terminate();server.wait(timeout=10)
        r=wait_request(qid,offline=True)
        check('Independent worker continued after HTTP server stopped',worker.poll() is None)
        server=spawn('server.py',['--port',str(PORT),'--data-root',str(ROOT),'--no-worker']);status=ready()
        reports=[r for r in status['reports'] if r['strategy']==sid];check('Twenty daily transactions recovered',len(reports)==20)
        check('Every daily PnL reconciles',all(abs(r['value']['reconciliation_difference'])<.02 for r in reports))
        check('Paper replay',api({'action':'replay','run_id':r['run']})['match'])
        qid=uuid.uuid4().hex;api({'action':'queue','strategy_id':sid,'kind':'paper','asof':end,'request_id':qid});wait_request(qid)
        check('Duplicate day does not add reports',len(api({'action':'status'})['reports'])==len(reports))
        duplicate=api({'action':'queue','strategy_id':sid,'kind':'paper','asof':end,'request_id':qid});check('Request idempotency',duplicate['state']=='success')
        b=api({'action':'backup'});recovered=api({'action':'restore_drill','backup_id':b['id']})
        check('Backup and isolated recovery verified',recovered['database_integrity']=='ok' and recovered['active_data_unchanged'])
        check('Recovered scheduler disabled',not Runtime(recovered['path']).dashboard()['scheduler_enabled'])
        api({'action':'transition','strategy_id':sid,'state':'paused'});check('Strategy pause persisted',next(v for v in api({'action':'status'})['strategies'] if v['id']==sid)['state']=='paused')
        check('Worker heartbeat online',api({'action':'status'})['worker_alive'])
        out={'completed_at':now().isoformat(),'scope':'isolated synthetic acceptance; not long-term live-market proof','checks':evidence,'paper_days':len(reports),'test_data_root':str(ROOT)}
        (APP/'OPERATIONS_ACCEPTANCE.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        print('ACCEPTANCE COMPLETE',flush=True)
    finally:
        for p in children:
            if p.poll() is None:p.terminate()
        for p in children:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill()

if __name__=="__main__":main()
