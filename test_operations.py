import json,tempfile,unittest,zipfile
import subprocess,sys
from pathlib import Path
from datetime import date,timedelta
from unittest.mock import patch
from ops_engine import Runtime,Blocked,gate,validate_config,paper_step,connect,packed,digest,now,stamp
from ops_feeds import demo_history,demo_calendar
from ops_storage import create_backup,restore_drill

def closed_day():
    d=now().date()
    if (now().hour,now().minute)<(15,20):d-=timedelta(days=1)
    while d.weekday()>4:d-=timedelta(days=1)
    return d.isoformat()

def rising():
    rows=[];day=date(2024,1,1);p=10
    while len(rows)<330:
        if day.weekday()<5:
            opening=p;p*=1.001
            rows.append({'date':day.isoformat(),'close':p,'raw_close':p,'raw_open':opening,'raw_high':p*1.01,'raw_low':opening*.99,'volume':100000})
        day+=timedelta(days=1)
    return rows

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.rt=Runtime(self.root)
        self.c=validate_config({'codes':['000001'],'mode':'demo','threshold':.005,'max_weight':1,'max_drawdown':.05})
    def tearDown(self):self.tmp.cleanup()
    def test_gate_stale_and_secondary_disagreement(self):
        end=closed_day();h=demo_history('000001',end);cal=demo_calendar();secondary={'000001':{'date':end,'close':h['bars'][-1]['raw_close']}}
        self.assertTrue(gate({'000001':h},cal,end,secondary=secondary)['passed'])
        self.assertFalse(gate({'000001':dict(h,stale=True)},cal,end,secondary=secondary)['passed'])
        secondary['000001']['close']+=1
        self.assertFalse(gate({'000001':h},cal,end,secondary=secondary)['passed'])
    def test_gate_gap_duplicate_and_calendar_expiry(self):
        end=closed_day();h=demo_history('000001',end);cal=demo_calendar();other={'000001':{'date':end,'close':h['bars'][-1]['raw_close']}}
        h['bars'].pop(-5);self.assertFalse(gate({'000001':h},cal,end,secondary=other)['passed'])
        h=demo_history('000001',end);h['bars'].append(h['bars'][-1]);self.assertFalse(gate({'000001':h},cal,end,secondary=other)['passed'])
        cal['covered_until']='2000-01-01';self.assertFalse(gate({'000001':h},cal,end,secondary=other)['passed'])
    def test_immutable_versions_and_durable_queue(self):
        a=self.rt.create('test',self.c);b=self.rt.create('test',dict(self.c,ma=20))
        self.assertEqual(self.rt.strategy(a)['version'],1);self.assertEqual(self.rt.strategy(b)['version'],2)
        q='a'*32;self.rt.enqueue(a,'research',closed_day(),q);self.rt.enqueue(a,'research',closed_day(),q)
        other=Runtime(self.root);self.assertEqual(len(other.dashboard()['requests']),1)
        with self.assertRaises(ValueError):self.rt.transition(a,'paper')
    def test_research_freeze_replay_and_promotion(self):
        sid=self.rt.create('research',self.c);run=self.rt.run(sid,'research',closed_day())
        self.assertEqual(run['status'],'success');self.assertTrue(self.rt.replay(run['run_id'])['match'])
        self.assertEqual(self.rt.strategy(sid)['state'],'validated');self.rt.transition(sid,'paper')
        self.assertEqual(self.rt.strategy(sid)['state'],'paper');self.rt.transition(sid,'paused')
        self.assertEqual(self.rt.strategy(sid)['state'],'paused')
    def test_bad_gate_cannot_validate(self):
        sid=self.rt.create('bad',self.c)
        with patch.object(self.rt,'freeze',return_value=('a'*64,{'gate':{'passed':False,'checks':[{'pass':False,'check':'bad'}]}})):
            r=self.rt.run(sid,'research',closed_day())
        self.assertEqual(r['status'],'blocked');self.assertEqual(self.rt.strategy(sid)['state'],'draft')
    def test_snapshot_tamper_detected(self):
        sid=self.rt.create('tamper',self.c);sha,snap=self.rt.freeze(self.rt.strategy(sid),closed_day())
        (self.rt.store/(sha+'.json')).write_text('{}')
        with self.assertRaises(Blocked):self.rt.snapshot(sha)
    def test_paper_attribution_risk_stop_and_no_mutation(self):
        bars=rising();prior=bars[-3]['date'];a={'cash':300000,'equity':300000,'peak':300000,'positions':{},'marks':{},'last_day':prior}
        original=packed(a);out=paper_step(a,{'000001':{'bars':bars}},bars[-2]['date'],self.c)
        self.assertEqual(packed(a),original);self.assertTrue(any(o['status']=='filled' for o in out['decisions']))
        self.assertAlmostEqual(out['pnl'],sum(out['contributions'].values()),places=6)
        b=bars[-1];b['raw_open']=bars[-2]['raw_close'];b['raw_close']=b['close']=b['raw_open']*.92;b['raw_low']=b['raw_close']*.99;b['raw_high']=b['raw_open']*1.01
        loss=paper_step(out['account'],{'000001':{'bars':bars}},b['date'],self.c)
        self.assertTrue(loss['risk_stop'])
    def test_corporate_action_blocks_held_position(self):
        bars=rising();a={'cash':300000,'equity':300000,'peak':300000,'positions':{},'marks':{},'last_day':bars[-3]['date']}
        out=paper_step(a,{'000001':{'bars':bars}},bars[-2]['date'],self.c)
        bars[-1]['close']*=1.1
        with self.assertRaises(Blocked):paper_step(out['account'],{'000001':{'bars':bars}},bars[-1]['date'],self.c)
    def test_daily_transaction_idempotency_and_report_replay(self):
        bars=rising();sid=self.rt.create('daily',self.c);a={'cash':300000,'equity':300000,'peak':300000,'positions':{},'marks':{},'last_day':bars[-3]['date']}
        a['engine']=self.rt.engine()
        with connect(self.rt.db) as c:
            c.execute("UPDATE strategies SET state='paper' WHERE id=?",(sid,));c.execute('INSERT INTO accounts VALUES(?,?)',(sid,packed(a)))
        snap={'feeds':{'000001':{'bars':bars}},'calendar':{'days':[r['date'] for r in bars]},'gate':{'passed':True,'expected_day':bars[-1]['date']},'config':self.c}
        sha=digest(snap);(self.rt.store/(sha+'.json')).write_text(packed(snap),encoding='utf-8')
        with patch.object(self.rt,'freeze',return_value=(sha,snap)):
            first=self.rt.run(sid,'paper',bars[-1]['date']);second=self.rt.run(sid,'paper',bars[-1]['date'])
        self.assertEqual(first['status'],'success');self.assertEqual(second['status'],'success')
        self.assertEqual(len(self.rt.dashboard()['reports']),2)
        self.assertTrue(self.rt.replay(first['run_id'])['match'])
        self.assertEqual(self.rt.detail(second['run_id'])['result']['processed_days'],[])
    def test_lease_and_backup_exclusion(self):
        with self.rt.lease('strategy:busy'):
            with self.assertRaises(Blocked):
                with self.rt.lease('strategy:busy'):pass
            with self.assertRaises(Blocked):create_backup(self.rt)
        self.assertFalse(self.rt.maintenance())
    def test_backup_restore_and_corruption(self):
        sid=self.rt.create('backup',self.c);backup=create_backup(self.rt);restored=restore_drill(self.rt,backup['id'])
        self.assertTrue(restored['active_data_unchanged']);self.assertEqual(restored['database_integrity'],'ok')
        self.assertEqual(self.rt.strategy(sid)['state'],'draft');self.assertFalse(Runtime(restored['path']).dashboard()['scheduler_enabled'])
        bad=self.root/'backups'/'backup-20261118T000000-aaaaaaaa.zip'
        with zipfile.ZipFile(self.root/'backups'/backup['id']) as src,zipfile.ZipFile(bad,'w') as dst:
            for name in src.namelist():dst.writestr(name,src.read(name)+(b'bad' if name=='operations.sqlite3' else b''))
        with self.assertRaises(Blocked):restore_drill(self.rt,bad.name)
    def test_worker_graceful_stop(self):
        from ops_service import dispatch
        dispatch({'action':'worker_stop'},self.rt)
        p=subprocess.run([sys.executable,str(Path(__file__).parent/'ops_worker.py'),'--root',str(self.root)],capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0)
        self.assertFalse(self.rt.dashboard()['worker_alive']);self.assertFalse(self.rt.dashboard()['scheduler_enabled'])
    def test_financial_commit_gets_additional_backup(self):
        from ops_worker import daily_backup
        from ops_storage import list_backups
        daily_backup(self.rt);daily_backup(self.rt)
        self.assertEqual(len(list_backups(self.rt)),1)
        daily_backup(self.rt,force=True)
        self.assertEqual(len(list_backups(self.rt)),2)

if __name__=='__main__':unittest.main()
