import unittest
from plutonium_agent_toolkit.core.errors import Failure
import json
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke
from tests.test_testing_contracts import contract

class TestPlanRoute(CompositionFixture):
    def member(self, mid, **over):
        m=self.module(mid,maps=['zm_transit'],tests='test-contract.json',**over)
        c=contract(module=mid,maps={'zm_transit':{'preconditions':[]}})
        (m/'test-contract.json').write_text(json.dumps(c));return m,c
    def test_successful_cli_writes_hashed_plan(self):
        self.member('alpha');comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--output',out,'--json'])
        self.assertEqual(code,0,row)
        from pathlib import Path
        plan=json.loads((Path(out)/'test-plan.json').read_text())
        self.assertEqual(plan['protocol'],'pat.test-plan/1')
        self.assertEqual(plan['members'][0]['id'],'alpha')
        self.assertEqual(len(plan['members'][0]['contract_sha256']),64)
    def test_missing_contract_is_structured_and_receipted(self):
        self.member('alpha');self.module('beta',maps=['zm_transit'])
        comp=self.composition(['alpha','beta']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp.parent),'--output',out,'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_missing',row)
        self.assertEqual(row['details']['field'],'/modules/1/tests')
        self.assertIn('receipt',row)
    def test_wildcard_declaration_plans_the_concrete_contract_map(self):
        m=self.module('alpha',maps=['*'],tests='test-contract.json')
        (m/'test-contract.json').write_text(json.dumps(contract(module='alpha')))
        comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--output',out,'--json'])
        self.assertEqual(code,0,row)

class StitchRules(unittest.TestCase):
    def fixture(self):
        from plutonium_agent_toolkit.testing import planner
        p={'name':'stock_pair_test','base':'stock','map':'zm_transit','mode':'human','order':['alpha','beta'],
           'modules':[{'id':i,'provides':{'gobblegums':[i]}} for i in ['alpha','beta']]}
        cs={i:contract(module=i) for i in p['order']}
        return planner,p,cs
    def test_order_dedupe_pairs_and_determinism(self):
        planner,p,cs=self.fixture();out=planner.stitch(p,cs,[])
        self.assertEqual(out,planner.stitch(p,cs,[]))
        self.assertEqual([m['id'] for m in out['members']],p['order'])
        self.assertEqual(len(out['preconditions']),1)
        self.assertEqual([s['id'] for s in out['phases'][1]['steps']],['alpha/s1','beta/s1'])
        pairs=out['phases'][2]['steps'];self.assertTrue(pairs)
        self.assertTrue(all(s['id'].startswith('pair/alpha+beta/') for s in pairs))
    def test_conflict_refuses_until_an_owner_is_recorded(self):
        planner,p,cs=self.fixture();cs['beta']['steps'][0]['check']['equals']='0'
        with self.assertRaises(Failure) as cm:planner.stitch(p,cs,[])
        self.assertEqual(cm.exception.details['conflicts'][0]['collision'],'test:state.playable')
        out=planner.stitch(p,cs,[{'collision':'test:state.playable','owner':'alpha','reason':'alpha owns the shared state check'}])
        self.assertTrue(all(c['resolution']!='undecided' for c in out['conflicts']))
        self.assertIn('beta/s1',out['excluded_steps'])
    def test_human_steps_remain_human(self):
        planner,p,cs=self.fixture()
        cs['alpha']['steps'].append({'id':'sound','actor':'human','verifier':'human','prompt':'Listen.'})
        cs['alpha']['human_only']=['sound']
        out=planner.stitch(p,cs,[]);self.assertEqual(out['human_steps'][0]['id'],'alpha/sound')
    def test_decision_collision_lookup_is_case_insensitive(self):
        planner,p,cs=self.fixture();cs['beta']['steps'][0]['check']['equals']='0'
        out=planner.stitch(p,cs,[{'collision':'TEST:State.Playable','owner':'alpha','reason':'alpha owns the shared state check'}])
        self.assertTrue(all(c['resolution']!='undecided' for c in out['conflicts']))
        self.assertIn('beta/s1',out['excluded_steps'])
    def test_interactions_prefer_a_step_with_an_action(self):
        planner,p,cs=self.fixture()
        readiness={'id':'readiness','actor':'agent','verifier':'agent','check':{'source':'harness','key':'round','min':1}}
        cs['alpha']['steps'].insert(0,readiness)
        out=planner.stitch(p,cs,[])
        pairs=out['phases'][2]['steps']
        self.assertTrue(pairs)
        self.assertTrue(all(s.get('action') for s in pairs),pairs)
    def test_human_provider_step_still_pairs_with_a_partner(self):
        planner,p,cs=self.fixture()
        cs['alpha']['steps']=[{'id':'listen','actor':'human','verifier':'agent','prompt':'Do the thing.',
                               'action':{'verb':'gum','arg':'x'},'check':{'source':'log','absent':'err'}}]
        cs['alpha']['human_only']=[]
        out=planner.stitch(p,cs,[])
        self.assertTrue(out['phases'][2]['steps'])
        self.assertTrue(any(s['actor']=='human' for s in out['phases'][2]['steps']))
    def test_background_refuses_human_preconditions(self):
        planner,p,cs=self.fixture();p['mode']='background'
        with self.assertRaises(Failure) as cm:planner.stitch(p,cs,[])
        self.assertEqual(cm.exception.details['field'],'/preconditions/0/actor')
    def test_missing_map_is_refused(self):
        planner,p,cs=self.fixture();cs['beta']['maps']={}
        with self.assertRaises(Failure) as cm:planner.stitch(p,cs,[])
        self.assertEqual(cm.exception.details['field'],'/modules/1/tests/maps/zm_transit')
