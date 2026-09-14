import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
from plutonium_agent_toolkit.dev import state

class ModuleStateTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.member=self.root/'member';self.member.mkdir();self.decl=self.member/'module.json';self.script=self.member/'x.gsc';self.script.write_text('init() {}')
        self.contract=self.member/'test-contract.json';self.contract.write_text('{"schema":1}')
        self.decl.write_text(json.dumps({'id':'x','tests':'test-contract.json'}))
        self.plan=self.write('plan.json',{'schema_version':1,'name':'stock_x_test','base':'stock','map':'zm_transit','modules':[{'id':'x','directory':str(self.member),'declaration_sha256':self.sha(self.decl)}]})
        self.package=self.root/'mod.ff';self.package.write_bytes(b'package')
        self.verify=self.write('receipt.json',{'status':'succeeded','ok':True,'command':'module build','inputs':{str(self.decl):self.sha(self.decl),str(self.script):self.sha(self.script)},'outputs':{'mod.ff':self.sha(self.package),'plan.json':self.sha(self.plan)},'result':{'mod_ff':'mod.ff'}})
        self.testplan=self.write('test-plan.json',{'protocol':'pat.test-plan/1','composition':'stock_x_test','base':'stock','map':'zm_transit','members':[{'id':'x','contract_sha256':self.sha(self.contract)}],'conflicts':[]})
        self.run=self.write('run.json',{'verdict':'automated-passed','package':{'sha256':self.sha(self.package)},'test_plan':{'sha256':self.sha(self.testplan),'path':str(self.testplan)}})
        self.verdict=self.write('ACCEPTED.json',{'verdicts':[{'outcome':'accepted','scope':{'map':'zm_transit','base':'stock'},'build':{'mod_ff_sha256':self.sha(self.package)}}]})
    def sha(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def write(self,name,d):p=self.root/name;p.write_text(json.dumps(d));return p
    def args(self,**kw):return SimpleNamespace(composition=str(self.root),plan=str(self.plan),verify=None,test_plan=None,run=None,verdict=None,**kw)
    def valid_plan(self,**over):
        plan={'schema_version':1,'name':'stock_x_test','base':'stock','map':'zm_transit',
              'modules':[{'id':'x','directory':str(self.member),'declaration_sha256':self.sha(self.decl)}]}
        plan.update(over);return plan
    def derive_plan(self,plan):
        self.write('plan.json',plan);return state.derive(self.args())
    def assert_no_state(self,plan,label=None):
        d=self.derive_plan(plan)
        self.assertIsNone(d['state'],label);self.assertIsNone(d['evidence'].get('composed'),label)
        self.assertTrue(d['reasons'],label);return d
    def test_each_evidence_rung(self):
        a=self.args()
        for expected,key,path in [('composed',None,None),('offline_verified','verify',self.verify),('ready_for_game_testing','test_plan',self.testplan),('game_tested','run',self.run),('player_accepted','verdict',self.verdict)]:
            if key:setattr(a,key,str(path))
            self.assertEqual(state.derive(a)['state'],expected)
    def complete(self):
        a=self.args();a.verify=str(self.verify);a.test_plan=str(self.testplan);a.run=str(self.run);a.verdict=str(self.verdict);return a
    def test_script_change_with_same_declaration_revokes_to_composed(self):
        a=self.complete();self.script.write_text('init() { }')
        d=state.derive(a);self.assertEqual(d['state'],'composed');self.assertIn('x.gsc',str(d['reasons']))
    def test_changed_declaration_claims_no_state(self):
        a=self.complete();self.decl.write_text(self.decl.read_text()+' ')
        d=state.derive(a);self.assertIsNone(d['state']);self.assertIsNone(d['evidence'].get('composed'))
        self.assertIn('x',str(d['reasons']));self.assertIn(self.sha(self.decl),str(d['reasons']))
    def test_changed_contract_revokes_readiness(self):
        self.contract.write_text('{}');self.assertEqual(state.derive(self.complete())['state'],'offline_verified')
    def test_plan_missing_or_malformed_name_base_map_never_claims_composed(self):
        base=self.valid_plan()
        cases=[('missing-name',{k:v for k,v in base.items() if k!='name'}),
               ('missing-base',{k:v for k,v in base.items() if k!='base'}),
               ('missing-map',{k:v for k,v in base.items() if k!='map'}),
               ('empty-name',{**base,'name':''}),
               ('base-not-string',{**base,'base':7}),
               ('map-not-string',{**base,'map':['zm_transit']})]
        for label,plan in cases:
            with self.subTest(label=label):self.assert_no_state(plan,label)
    def test_plan_module_rows_must_be_a_nonempty_list_of_typed_rows(self):
        base=self.valid_plan();row={'id':'x','directory':str(self.member),'declaration_sha256':self.sha(self.decl)}
        cases=[('empty-modules',{**base,'modules':[]}),
               ('non-list-modules',{**base,'modules':'nope'}),
               ('row-not-object',{**base,'modules':['x']}),
               ('missing-id',{**base,'modules':[{k:v for k,v in row.items() if k!='id'}]}),
               ('missing-directory',{**base,'modules':[{k:v for k,v in row.items() if k!='directory'}]}),
               ('missing-hash',{**base,'modules':[{k:v for k,v in row.items() if k!='declaration_sha256'}]}),
               ('id-not-string',{**base,'modules':[{**row,'id':3}]}),
               ('empty-directory',{**base,'modules':[{**row,'directory':''}]}),
               ('hash-not-string',{**base,'modules':[{**row,'declaration_sha256':None}]})]
        for label,plan in cases:
            with self.subTest(label=label):self.assert_no_state(plan,label)
    def test_duplicate_module_ids_never_claim_composed(self):
        row={'id':'x','directory':str(self.member),'declaration_sha256':self.sha(self.decl)}
        d=self.assert_no_state({**self.valid_plan(),'modules':[row,dict(row)]})
        self.assertIn('duplicate',str(d['reasons']).lower())
    def test_undecided_collision_never_claims_composed(self):
        self.assert_no_state({**self.valid_plan(),'undecided':[{'collision':'x','kind':'file','modules':['x']}]})
    def set_plan_unqualified(self,entries):
        plan=json.loads(self.plan.read_text(encoding='utf-8'));plan['unqualified']=entries
        self.plan.write_text(json.dumps(plan),encoding='utf-8')
        receipt=json.loads(self.verify.read_text(encoding='utf-8'))
        receipt['outputs']['plan.json']=self.sha(self.plan)
        self.verify.write_text(json.dumps(receipt),encoding='utf-8')
    def test_nonempty_unqualified_plan_never_advances_past_composed(self):
        self.set_plan_unqualified([{'id':'x','declared_bases':['other_base'],'declared_maps':['zm_transit'],'base':'stock','map':'zm_transit'}])
        d=state.derive(self.complete())
        self.assertEqual(d['state'],'composed')
        self.assertNotIn('offline_verified',d['evidence'])
        self.assertTrue(d['reasons']);self.assertIn('unqualified',str(d['reasons']))
    def test_receipt_result_unqualified_blocks_promotion_even_when_the_plan_omits_it(self):
        receipt=json.loads(self.verify.read_text(encoding='utf-8'))
        receipt['result']['unqualified']=[{'id':'x'}]
        self.verify.write_text(json.dumps(receipt),encoding='utf-8')
        d=state.derive(self.complete())
        self.assertEqual(d['state'],'composed');self.assertTrue(d['reasons'])
    def test_empty_unqualified_plan_still_advances(self):
        self.set_plan_unqualified([])
        self.assertEqual(state.derive(self.complete())['state'],'player_accepted')
    def test_failed_run_and_latest_rejection_do_not_accept(self):
        self.write('run.json',{'verdict':'inconclusive'});self.assertEqual(state.derive(self.complete())['state'],'ready_for_game_testing')
    def test_wrong_package_never_promotes(self):
        self.package.write_bytes(b'changed');self.assertEqual(state.derive(self.complete())['state'],'composed')
    def project_verify_receipt(self,**over):
        row={'status':'succeeded','ok':True,'command':'project verify','inputs':{str(self.verify):self.sha(self.verify)},
             'outputs':{},'result':{'build_receipt':str(self.verify),
                                    'outputs':{'verified':True,'changed':[],'missing':[],'count':2},
                                    'verification':'recorded hashes match'}}
        row.update(over)
        (self.root/'verification').mkdir(exist_ok=True)
        return self.write('verification/receipt.json',row)
    def verify_args(self,receipt):
        a=self.args();a.verify=str(receipt);return a
    def test_project_verify_receipt_resolves_the_package_from_its_build_receipt(self):
        d=state.derive(self.verify_args(self.project_verify_receipt()))
        self.assertEqual(d['state'],'offline_verified',d['reasons'])
        self.assertEqual(Path(d['evidence']['offline_verified']['path']),self.root/'verification'/'receipt.json')
    def test_project_verify_receipt_must_bind_the_build_receipt_it_reports(self):
        self.assertEqual(state.derive(self.verify_args(self.project_verify_receipt(inputs={})))['state'],'composed')
    def test_project_verify_receipt_refuses_a_changed_package(self):
        receipt=self.project_verify_receipt();self.package.write_bytes(b'changed')
        self.assertEqual(state.derive(self.verify_args(receipt))['state'],'composed')
    def test_project_verify_receipt_refuses_a_changed_build_receipt(self):
        receipt=self.project_verify_receipt()
        self.verify.write_text(json.dumps({**json.loads(self.verify.read_text()),'result':{'mod_ff':'somewhere.ff'}}))
        self.assertEqual(state.derive(self.verify_args(receipt))['state'],'composed')
    def test_malformed_outputs_or_result_maps_are_rejected(self):
        for bad in ({'outputs':{'mod.ff':self.sha(self.package)},'result':['nope']},
                    {'outputs':['nope'],'result':{'mod_ff':'mod.ff'}}):
            path=self.write('malformed.json',{'status':'succeeded','ok':True,'command':'module build',**bad})
            d=state.derive(self.verify_args(path))
            self.assertEqual(d['state'],'composed');self.assertTrue(d['reasons'])
    def test_project_verify_rejects_a_malformed_build_receipt(self):
        bad=self.write('bad-build.json',{'status':'succeeded','ok':True,'command':'module build','outputs':['nope'],'result':{'mod_ff':'mod.ff'}})
        receipt=self.project_verify_receipt(inputs={str(bad):self.sha(bad)},
                                            result={'build_receipt':str(bad),'outputs':{'verified':True}})
        self.assertEqual(state.derive(self.verify_args(receipt))['state'],'composed')
    def test_malformed_inputs_map_is_rejected(self):
        path=self.write('bad-inputs.json',{'status':'succeeded','ok':True,'command':'module build','inputs':[],
                                           'outputs':{'mod.ff':self.sha(self.package)},'result':{'mod_ff':'mod.ff'}})
        d=state.derive(self.verify_args(path));self.assertEqual(d['state'],'composed');self.assertTrue(d['reasons'])
    def test_project_verify_rejects_a_malformed_inputs_map(self):
        self.assertEqual(state.derive(self.verify_args(self.project_verify_receipt(inputs=[])))['state'],'composed')
    def test_project_verify_rejects_a_malformed_build_inputs_map(self):
        bad=self.write('bad-build-inputs.json',{'status':'succeeded','ok':True,'command':'module build','inputs':[],
                                                'outputs':{'mod.ff':self.sha(self.package)},'result':{'mod_ff':'mod.ff'}})
        receipt=self.project_verify_receipt(inputs={str(bad):self.sha(bad)},
                                            result={'build_receipt':str(bad),'outputs':{'verified':True}})
        self.assertEqual(state.derive(self.verify_args(receipt))['state'],'composed')
    def test_malformed_verdicts_artifact_returns_reasons_not_a_traceback(self):
        rows=[{'verdicts':'nope'},
              {'verdicts':['nope']},
              {'verdicts':[{'outcome':'accepted','build':['nope'],'scope':{'map':'zm_transit','base':'stock'}}]},
              {'verdicts':[{'outcome':'accepted','build':{'mod_ff_sha256':self.sha(self.package)},'scope':'nope'}]}]
        for row in rows:
            with self.subTest(row=row):
                path=self.write('bad-verdict.json',row)
                a=self.complete();a.verdict=str(path)
                d=state.derive(a)
                self.assertEqual(d['state'],'game_tested');self.assertTrue(d['reasons'])
    def test_malformed_run_package_and_test_plan_maps_are_rejected(self):
        for extra in ({'package':['nope']},{'test_plan':'nope'}):
            with self.subTest(extra=extra):
                row={'verdict':'automated-passed','package':{'sha256':self.sha(self.package)},
                     'test_plan':{'sha256':self.sha(self.testplan),'path':str(self.testplan)}}
                row.update(extra)
                path=self.write('bad-run.json',row)
                a=self.complete();a.run=str(path)
                d=state.derive(a)
                self.assertEqual(d['state'],'ready_for_game_testing');self.assertTrue(d['reasons'])
    def test_malformed_test_plan_conflicts_are_rejected(self):
        for conflicts in ('nope',['nope']):
            with self.subTest(conflicts=conflicts):
                path=self.write('bad-test-plan.json',{'protocol':'pat.test-plan/1','composition':'stock_x_test','base':'stock',
                                                      'map':'zm_transit','members':[{'id':'x','contract_sha256':self.sha(self.contract)}],
                                                      'conflicts':conflicts})
                a=self.complete();a.test_plan=str(path)
                d=state.derive(a)
                self.assertEqual(d['state'],'offline_verified');self.assertTrue(d['reasons'])
    def test_plan_hash_failure_after_a_successful_read_revokes_instead_of_raising(self):
        rows=[('deleted','Missing or linked evidence'),('linked','Missing or linked evidence'),('unreadable','Permission denied')]
        for label,message in rows:
            with self.subTest(label=label):
                a=self.args()
                real_read=state.read
                def fake_read(path,real=real_read):
                    value=real(path)
                    if Path(path)==self.plan:
                        def boom(_path):raise OSError(message)
                        self._sha=state.sha;state.sha=boom
                    return value
                state.read=fake_read
                try:
                    d=state.derive(a)
                finally:
                    state.read=real_read
                    if hasattr(self,'_sha'):state.sha=self._sha;del self._sha
                self.assertIsNone(d['state'],label)
                self.assertEqual(d['evidence'].get('composed'),None,label)
                self.assertTrue(d['reasons'],label)
    def test_deeply_nested_plan_json_is_revoked_with_a_reason(self):
        nested=self.root/'deep-plan.json';nested.write_text('['*20000+']'*20000,encoding='utf-8')
        self.assertLess(nested.stat().st_size,16*1024**2)
        a=self.args();a.plan=str(nested)
        d=state.derive(a)
        self.assertIsNone(d['state']);self.assertTrue(d['reasons'])
    def test_deeply_nested_later_evidence_revokes_to_the_last_state(self):
        for label,key,expected in [('verify','verify','composed'),('test_plan','test_plan','offline_verified'),
                                   ('run','run','ready_for_game_testing'),('verdict','verdict','game_tested')]:
            with self.subTest(label=label):
                nested=self.root/f'deep-{label}.json';nested.write_text('['*20000+']'*20000,encoding='utf-8')
                self.assertLess(nested.stat().st_size,16*1024**2)
                a=self.complete();setattr(a,key,str(nested))
                d=state.derive(a)
                self.assertEqual(d['state'],expected,label)
                self.assertTrue(d['reasons'],label)
    def test_contract_path_symlink_cycle_is_revoked_with_a_reason(self):
        real=Path.resolve
        def loop(self,*args,**kwargs):
            if self.name=='test-contract.json':raise RuntimeError('Symlink loop from %r'%str(self))
            return real(self,*args,**kwargs)
        with mock.patch.object(Path,'resolve',loop):
            d=state.derive(self.complete())
        self.assertEqual(d['state'],'offline_verified');self.assertTrue(d['reasons'])
        self.assertIn('Invalid contract path for x',str(d['reasons']))
    def test_evidence_reads_utf8_under_an_ascii_locale(self):
        import locale
        path=self.root/'unicode-receipt.json'
        path.write_text(json.dumps({'note':'café'},ensure_ascii=False),encoding='utf-8')
        previous=locale.setlocale(locale.LC_CTYPE)
        self.addCleanup(locale.setlocale,locale.LC_CTYPE,previous)
        locale.setlocale(locale.LC_CTYPE,'C')
        self.assertEqual(state.read(path),{'note':'café'})
