import json,os,subprocess,sys,time
from pathlib import Path
from ops_engine import Runtime,Blocked,connect
from ops_storage import create_backup,restore_drill,list_backups

def start_worker(rt):
    rt.require_ready()
    with connect(rt.db) as c:c.execute("INSERT OR REPLACE INTO settings VALUES('stop_worker','false')")
    state=rt.dashboard()
    if state['worker_alive']:return {'started':False,'message':'后台进程已在线'}
    log=rt.root/'worker-runtime.log'
    with log.open('ab') as out:
        process=subprocess.Popen([sys.executable,str(Path(__file__).parent/'ops_worker.py'),'--root',str(rt.root)],cwd=Path(__file__).parent,stdin=subprocess.DEVNULL,stdout=out,stderr=out,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
    return {'started':True,'pid':process.pid,'message':'已启动独立后台进程；请稍后检查心跳'}

def dispatch(body,rt):
    action=body.get('action','status')
    if action=='status':return {**rt.dashboard(),'backups':list_backups(rt)}
    if action=='create':return {'strategy_id':rt.create(str(body.get('name','')),body.get('config',{}))}
    if action=='queue':return rt.enqueue(body.get('strategy_id',''),body.get('kind','research'),body.get('asof',''),body.get('request_id'))
    if action=='transition':rt.transition(body.get('strategy_id',''),body.get('state',''));return {'ok':True}
    if action=='detail':
        result=rt.detail(body.get('run_id',''))
        if result['kind']=='paper':
            with connect(rt.db) as c:result['daily_reports']=[{**dict(r),'value':json.loads(r['value'])} for r in c.execute('SELECT * FROM reports WHERE run=? ORDER BY day',(result['id'],))]
        return result
    if action=='replay':return rt.replay(body.get('run_id',''))
    if action=='worker_start':return start_worker(rt)
    if action=='worker_stop':
        with connect(rt.db) as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES('stop_worker','true')");c.execute("INSERT OR REPLACE INTO settings VALUES('scheduler','false')")
        rt.log('warning','worker','用户请求停止后台进程，调度已暂停');return {'message':'调度已暂停；当前任务完成后后台进程退出。'}
    if action=='scheduler':
        rt.require_ready()
        with connect(rt.db) as c:c.execute("INSERT OR REPLACE INTO settings VALUES('scheduler',?)",('true' if body.get('enabled') is True else 'false',))
        rt.log('info','scheduler','用户切换后台调度：'+str(body.get('enabled')));return {'ok':True}
    if action=='backup':return create_backup(rt)
    if action=='restore_drill':return restore_drill(rt,body.get('backup_id',''))
    raise ValueError('未知运营操作')
