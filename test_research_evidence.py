import copy,json,tempfile,unittest
from unittest.mock import patch
from server import demo,extension_histories
from research_evidence import EvidenceStore,digest,engine_manifest


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.end=demo()['bars'][649]['date']
        cls.feeds=extension_histories(['600519','000001','300750','600036','000333','601318'],cls.end,True,minimum=1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=EvidenceStore(self.temp.name)

    def capture(self,feeds=None,end=None,demo=True):
        return self.store.capture(feeds or self.feeds,end or self.end,demo)

    def test_data_identity_cutoff_and_first_observation_metadata(self):
        first=self.capture();changed=copy.deepcopy(self.feeds)
        for h in changed.values():h['fetched_at']='2099-01-01';h['stale']=True
        again=self.capture(changed)
        self.assertEqual(first['id'],again['id']);self.assertTrue(again['reused'])
        self.assertFalse(again['rows'][0]['stale'])
        end=self.feeds['600519']['bars'][-2]['date']
        a=self.capture(end=end)
        b=self.capture({c:{**h,'bars':h['bars'][:-1]} for c,h in self.feeds.items()},end=end)
        self.assertEqual(a['id'],b['id'])

    def test_offline_replay_four_research_profiles(self):
        snap=self.capture()['id']
        profiles={'factor':{},'portfolio':{},'regime':{'code':'600519'},'strategy':{'code':'600519'}}
        for kind,config in profiles.items():
            with self.subTest(kind=kind),patch('requests.sessions.Session.request',side_effect=AssertionError('offline replay must not fetch data')):
                run=self.store.run(snap,kind,config)
                check=self.store.replay(run['run_id'])
                self.assertEqual(check['status'],'matched')
                self.assertEqual(check['actual_sha'],run['result_sha'])
                self.assertTrue(all(r['passed'] for r in check['checks']))
                self.assertEqual(check['original_summary'],check['replayed_summary'])

    def test_environment_change_blocks_recalculation(self):
        snap=self.capture()['id'];run=self.store.run(snap,'factor',{})
        other={**engine_manifest(),'python':'other-python'}
        with patch('research_evidence.engine_manifest',return_value=other),patch('research_evidence.evaluate',side_effect=AssertionError('must not run under changed engine')):
            check=self.store.replay(run['run_id'])
        self.assertEqual(check['status'],'engine_changed')
        self.assertIsNone(check['actual_sha']);self.assertIsNone(check['checks'][-1]['passed'])
        self.assertEqual(self.store.read('runs',run['run_id'])['result_sha'],run['result_sha'])

    def test_source_edits_require_service_restart(self):
        snap=self.capture()['id']
        with patch('research_evidence.disk_sources',return_value={}):
            with self.assertRaisesRegex(ValueError,'重启'):self.store.run(snap,'factor',{})
        self.assertEqual(self.store.inventory()['runs'],[])

    def test_tampering_is_detected_and_excluded_from_inventory(self):
        snap=self.capture()['id'];path=self.store.path('snapshots',snap)
        content=json.loads(path.read_text(encoding='utf-8'))
        content['record']['payload']['feeds']['600519']['bars'][0]['close']+=1
        path.write_text(json.dumps(content),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'校验'):self.store.read('snapshots',snap)
        self.assertEqual(len(self.store.inventory()['warnings']),1)
        content['checksum']=digest(content['record'])
        path.write_text(json.dumps(content),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'内容校验'):self.store.read('snapshots',snap)

    def test_result_mismatch_is_not_reported_as_reproduced(self):
        snap=self.capture()['id'];run=self.store.run(snap,'factor',{})
        altered=copy.deepcopy(run['result']);altered['summary']['mean_ic']=.99
        with patch('research_evidence.evaluate',return_value=altered):check=self.store.replay(run['run_id'])
        self.assertEqual(check['status'],'mismatch')
        self.assertFalse(check['checks'][-1]['passed'])

    def test_version_comparison_distinguishes_additions_and_changes(self):
        earlier=self.feeds['600519']['bars'][-2]['date'];left=self.capture(end=earlier)['id']
        changed=copy.deepcopy(self.feeds)
        changed['600519']['bars'][50]['close']*=1.01
        changed['600519']['bars'][51]['volume']+=100
        right=self.capture(changed)['id'];diff=self.store.compare(left,right)
        target=next(r for r in diff['rows'] if r['code']=='600519')
        self.assertEqual(target['added'],1);self.assertEqual(target['changed'],2)
        self.assertAlmostEqual(diff['changes'][0]['close_revision'],.01)
        self.assertEqual(diff['changes'][1]['fields'],['volume'])
        self.assertEqual(self.store.compare(right,left)['rows'][0]['removed'],1)
        live=self.capture(demo=False)['id']
        with self.assertRaisesRegex(ValueError,'演示'):self.store.compare(left,live)

    def test_bad_data_parameters_and_paths_are_rejected(self):
        for mutation in ('duplicate','nan','ohlc'):
            feeds=copy.deepcopy(self.feeds)
            if mutation=='duplicate':feeds['600519']['bars'].append(feeds['600519']['bars'][-1])
            elif mutation=='nan':feeds['600519']['bars'][1]['close']=float('nan')
            else:feeds['600519']['bars'][1]['raw_low']=1e9
            with self.assertRaises(ValueError):self.capture(feeds)
        with self.assertRaises(ValueError):self.store.read('snapshots','../runs')
        snap=self.capture()['id']
        for kind,config in (('shell',{}),('factor',{'command':'not executable'}),('regime',{'code':'999999'})):
            with self.assertRaises(ValueError):self.store.run(snap,kind,config)


if __name__=='__main__':unittest.main()
