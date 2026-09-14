import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from plutonium_agent_toolkit.dev import state

class ModuleStateTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.member=self.root/'member';self.member.mkdir();self.decl=self.member/'module.json';self.script=self.member/'x.gsc';self.script.write_text('init() {}')
        self.contract=self.member/'test-contract.json';self.contract.write_text('{"schema":1}')
        self.decl.write_text(json.dumps({'id':'x','tests':'test-contract.json'}))
        self.plan=self.write('plan.json',{'name':'stock_x_test','base':'stock','map':'zm_transit','modules':[{'id':'x','directory':str(self.member),'declaration_sha256':self.sha(self.decl)}]})
        self.package=self.root/'mod.ff';self.package.write_bytes(b'package')
        self.verify=self.write('receipt.json',{'status':'succeeded','ok':True,'command':'module build','inputs':{str(self.decl):self.sha(self.decl),str(self.script):self.sha(self.script)},'outputs':{'mod.ff':self.sha(self.package),'plan.json':self.sha(self.plan)},'result':{'mod_ff':'mod.ff'}})
        self.testplan=self.write('test-plan.json',{'protocol':'pat.test-plan/1','composition':'stock_x_test','base':'stock','map':'zm_transit','members':[{'id':'x','contract_sha256':self.sha(self.contract)}],'conflicts':[]})
        self.run=self.write('run.json',{'verdict':'automated-passed','package':{'sha256':self.sha(self.package)},'test_plan':{'sha256':self.sha(self.testplan),'path':str(self.testplan)}})
        self.verdict=self.write('ACCEPTED.json',{'verdicts':[{'outcome':'accepted','scope':{'map':'zm_transit','base':'stock'},'build':{'mod_ff_sha256':self.sha(self.package)}}]})
    def sha(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def write(self,name,d):p=self.root/name;p.write_text(json.dumps(d));return p
    def args(self,**kw):return SimpleNamespace(composition=str(self.root),plan=str(self.plan),verify=None,test_plan=None,run=None,verdict=None,**kw)
    def test_each_evidence_rung(self):
        a=self.args()
        for expected,key,path in [('composed',None,None),('offline_verified','verify',self.verify),('ready_for_game_testing','test_plan',self.testplan),('game_tested','run',self.run),('player_accepted','verdict',self.verdict)]:
            if key:setattr(a,key,str(path))
            self.assertEqual(state.derive(a)['state'],expected)
    def complete(self):
        a=self.args();a.verify=str(self.verify);a.test_plan=str(self.testplan);a.run=str(self.run);a.verdict=str(self.verdict);return a
    def test_script_and_declaration_changes_revoke_to_composed(self):
        a=self.complete();self.script.write_text('init() { }')
        d=state.derive(a);self.assertEqual(d['state'],'composed');self.assertIn('x.gsc',str(d['reasons']))
        self.decl.write_text(self.decl.read_text()+' ');d=state.derive(a);self.assertEqual(d['state'],'composed');self.assertIn('x',str(d['reasons']));self.assertIn(self.sha(self.decl),str(d['reasons']))
    def test_changed_contract_revokes_readiness(self):
        self.contract.write_text('{}');self.assertEqual(state.derive(self.complete())['state'],'offline_verified')
    def test_failed_run_and_latest_rejection_do_not_accept(self):
        self.write('run.json',{'verdict':'inconclusive'});self.assertEqual(state.derive(self.complete())['state'],'ready_for_game_testing')
    def test_wrong_package_never_promotes(self):
        self.package.write_bytes(b'changed');self.assertEqual(state.derive(self.complete())['state'],'composed')
    def project_verify_receipt(self,**over):
        row={'status':'succeeded','ok':True,'command':'project verify','inputs':{str(self.verify):self.sha(self.verify)},
             'outputs':{},'result':{'build_receipt':str(self.verify),
                                    'outputs':{'verified':True,'changed':[],'missing':[],'count':2},
                                    'verification':'recorded hashes match'}}
        row.update(over);return self.write('verify-receipt.json',row)
    def verify_args(self,receipt):
        a=self.args();a.verify=str(receipt);return a
    def test_project_verify_receipt_resolves_the_package_from_its_build_receipt(self):
        d=state.derive(self.verify_args(self.project_verify_receipt()))
        self.assertEqual(d['state'],'offline_verified',d['reasons'])
        self.assertEqual(Path(d['evidence']['offline_verified']['path']),self.root/'verify-receipt.json')
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
