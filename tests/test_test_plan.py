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
    def test_missing_member_contract_points_at_declaration_index(self):
        self.member('alpha',dependencies=['beta']);self.module('beta')
        comp=self.composition(['alpha','beta']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--output',out,'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_missing',row)
        self.assertEqual(row['details']['field'],'/modules/1/tests')
    def test_invalid_member_contract_points_at_declaration_index(self):
        self.member('alpha',dependencies=['beta'])
        beta=self.module('beta',maps=['zm_transit'],tests='test-contract.json')
        (beta/'test-contract.json').write_text(json.dumps(contract(module='alpha')))
        comp=self.composition(['alpha','beta']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--output',out,'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_invalid',row)
        self.assertEqual(row['details']['field'],'/modules/1/module')
    def test_member_contract_outside_map_points_at_declaration_index(self):
        self.member('alpha',dependencies=['beta'])
        beta=self.module('beta',maps=['*'],tests='test-contract.json')
        (beta/'test-contract.json').write_text(json.dumps(contract(module='beta',maps={'zm_factory':{'preconditions':[]}})))
        comp=self.composition(['alpha','beta']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--output',out,'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_invalid',row)
        self.assertEqual(row['details']['field'],'/modules/1/tests/maps/zm_transit')
    def test_wildcard_declaration_plans_the_concrete_contract_map(self):
        m=self.module('alpha',maps=['*'],tests='test-contract.json')
        (m/'test-contract.json').write_text(json.dumps(contract(module='alpha')))
        comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--output',out,'--json'])
        self.assertEqual(code,0,row)
    def test_mixed_game_member_is_rejected_before_resolving(self):
        self.member('alpha',game='iw5')
        comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--output',out,'--json'])
        self.assertEqual(code,1,row)
        self.assertEqual(row['error_code'],'input_invalid',row)
        self.assertEqual(row['details']['field'],'/modules/0/game')

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
    def test_human_harness_check_conflict_requires_an_owner(self):
        planner,p,cs=self.fixture()
        cs['beta']['steps'][0]['actor']='human';cs['beta']['steps'][0]['prompt']='Do the shared thing.'
        cs['beta']['steps'][0]['check']['equals']='0'
        with self.assertRaises(Failure) as cm:planner.stitch(p,cs,[])
        self.assertEqual(cm.exception.details['conflicts'][0]['collision'],'test:state.playable')
        self.assertEqual(cm.exception.details['conflicts'][0]['modules'],['alpha','beta'])
    def test_excluded_human_step_is_removed_and_not_reused_in_interactions(self):
        planner,p,cs=self.fixture()
        cs['beta']['steps']=[{'id':'conflict','actor':'human','verifier':'agent','prompt':'Do the shared thing.',
                              'action':{'verb':'gum','arg':'load_machine'},
                              'check':{'source':'harness','key':'state.playable','equals':'0'}},
                             {'id':'action2','actor':'agent','verifier':'agent',
                              'action':{'verb':'gum','arg':'load_machine'},'check':{'source':'log','absent':'err'}}]
        cs['beta']['human_only']=[]
        out=planner.stitch(p,cs,[{'collision':'test:state.playable','owner':'alpha','reason':'alpha owns the shared state check'}])
        self.assertIn('beta/conflict',out['excluded_steps'])
        self.assertNotIn('beta/conflict',[s['id'] for s in out['human_steps']])
        pair_ids=[s['id'] for s in out['phases'][2]['steps']]
        self.assertTrue(pair_ids,out['phases'][2])
        self.assertTrue(all('beta/conflict' not in i for i in pair_ids),pair_ids)
    def test_background_refuses_human_preconditions(self):
        planner,p,cs=self.fixture();p['mode']='background'
        with self.assertRaises(Failure) as cm:planner.stitch(p,cs,[])
        self.assertEqual(cm.exception.details['field'],'/preconditions/0/actor')
    def test_missing_map_is_refused(self):
        planner,p,cs=self.fixture();cs['beta']['maps']={}
        with self.assertRaises(Failure) as cm:planner.stitch(p,cs,[])
        self.assertEqual(cm.exception.details['field'],'/modules/1/tests/maps/zm_transit')

class NestedDecisionScopeTests(CompositionFixture):
    def test_scoped_decisions_are_json_safe_sorted_lists(self):
        from plutonium_agent_toolkit.testing import planner
        composition={'decisions':[{'collision':'test:y','owner':'c','reason':'outer'}],
                     'members':[{'composition':{'decisions':[{'collision':'test:x','owner':'a','reason':'inner'}],
                                                'members':[{},{}]}},{}]}
        rows=planner.scoped_decisions(composition,[{'id':'b'},{'id':'a'},{'id':'c'}])
        self.assertEqual([(r['collision'],r['scope']) for r in rows],
                         [('test:y',['a','b','c']),('test:x',['a','b'])])
        self.assertTrue(all(isinstance(r['scope'],list) for r in rows))
    def scoped_member(self,mid,equals='1'):
        m=self.module(mid,maps=['zm_transit'],tests='test-contract.json')
        c=contract(module=mid,maps={'zm_transit':{'preconditions':[]}})
        c['steps'][0]['check']['equals']=equals
        (m/'test-contract.json').write_text(json.dumps(c))
        return m
    def outer(self,name,modules):
        d=self.root/'packs'/name;d.mkdir(parents=True,exist_ok=True)
        (d/'composition.json').write_text(json.dumps({'schema':1,'name':name,'base':'stock','map':'zm_transit','modules':modules}))
        return d/'composition.json'
    def test_nested_decision_does_not_resolve_an_outer_collision(self):
        self.scoped_member('inner_a','1');self.scoped_member('inner_b','0');self.scoped_member('outer_mod','0')
        self.composition(['inner_a','inner_b'],name='stock_inner_test',
                         decisions=[{'collision':'test:state.playable','owner':'inner_a','reason':'inner owns the shared check'}])
        outer=self.outer('stock_outer_test',[{'path':'../stock_inner_test'},{'path':'../../modules/outer_mod'}])
        code,row=invoke(['test','plan','--composition',str(outer),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row)
        self.assertEqual(row['error_code'],'input_invalid',row)
        self.assertEqual(row['details']['field'],'/conflicts')
    def test_nested_decision_resolves_a_nested_only_collision(self):
        self.scoped_member('inner_a','1');self.scoped_member('inner_b','0')
        self.composition(['inner_a','inner_b'],name='stock_inner_test',
                         decisions=[{'collision':'test:state.playable','owner':'inner_a','reason':'inner owns the shared check'}])
        outer=self.outer('stock_outer_test',[{'path':'../stock_inner_test'}])
        code,row=invoke(['test','plan','--composition',str(outer),'--output',self.out(),'--json'])
        self.assertEqual(code,0,row)
class EmittedCompositionTests(CompositionFixture):
    def plan_member(self,mid,**over):
        m=self.module(mid,maps=['zm_transit'],tests='test-contract.json',**over)
        (m/'test-contract.json').write_text(json.dumps(contract(module=mid,maps={'zm_transit':{'preconditions':[]}})))
        return m
    def probe_member(self,mid):
        m=self.plan_member(mid);c=json.loads((m/'test-contract.json').read_text())
        c['maps']['zm_transit']['preconditions']=[{'verb':'power_on','actor':'agent'}]
        (m/'test-contract.json').write_text(json.dumps(c));return m
    def outer(self,name,modules,**extra):
        d=self.root/'packs'/name;d.mkdir(parents=True,exist_ok=True)
        row={'schema':1,'name':name,'base':'stock','map':'zm_transit','modules':modules};row.update(extra)
        (d/'composition.json').write_text(json.dumps(row));return d/'composition.json'
    def test_emitted_probe_composition_roundtrips_roles_pins_and_nested_metadata(self):
        from pathlib import Path
        self.plan_member('base_mod');self.probe_member('needy')
        self.module('inner_a',maps=['zm_transit'],tests='test-contract.json',script_target='scripts/zm/shared.gsc')
        self.module('inner_b',maps=['zm_transit'],tests='test-contract.json',script_target='scripts/zm/shared.gsc')
        (self.root/'modules'/'inner_a'/'test-contract.json').write_text(json.dumps(contract(module='inner_a',maps={'zm_transit':{'preconditions':[]}})))
        (self.root/'modules'/'inner_b'/'test-contract.json').write_text(json.dumps(contract(module='inner_b',maps={'zm_transit':{'preconditions':[]}})))
        self.composition(['inner_a','inner_b'],name='stock_inner_test',
                         decisions=[{'collision':'scripts/zm/shared.gsc','owner':'inner_a','reason':'inner owns the shared file'}],
                         zone_header=['>level.ipak_read,inner_zm'])
        self.plan_member('test_probe',tags=['test-only'])
        (self.root/'packs'/'zones').mkdir(parents=True,exist_ok=True);(self.root/'packs'/'zones'/'extra.ff').write_bytes(b'ff')
        (self.root/'packs'/'listings').mkdir(parents=True,exist_ok=True);(self.root/'packs'/'listings'/'base.csv').write_text('rawfile, shared_asset\n')
        outer=self.outer('stock_outer_test',[{'path':'../stock_inner_test'},
                                             {'path':'../../modules/base_mod','role':'base','name':'example/base_mod','commit':'a'*40},
                                             '../../modules/needy'],
                         zone_header=['>level.ipak_read,outer_zm'],loads=['../zones/extra.ff'],base_owned=['../listings/base.csv'])
        out=self.out();code,row=invoke(['test','plan','--composition',str(outer),'--output',out,'--json']);self.assertEqual(code,0,row)
        emitted=json.loads((Path(out)/'composition.json').read_text())
        base=next(e for e in emitted['modules'] if isinstance(e,dict) and e.get('role')=='base')
        self.assertEqual(base['name'],'example/base_mod');self.assertEqual(base['commit'],'a'*40)
        paths=[e if isinstance(e,str) else e['path'] for e in emitted['modules']]
        self.assertIn('test_probe',[Path(p).name for p in paths])
        self.assertTrue(all('\\' not in p for p in paths))
        reload_out=self.out()
        code,reloaded=invoke(['module','plan',str(Path(out)/'composition.json'),'--output',reload_out,'--json']);self.assertEqual(code,0,reloaded)
        res=reloaded['result'];doc=json.loads((Path(res['output'])/'plan.json').read_text())
        self.assertEqual(res['base_member'],'base_mod')
        self.assertEqual(res['undecided'],[])
        self.assertTrue(any(d['collision']=='scripts/zm/shared.gsc' and d['owner']=='inner_a' for d in res['decisions']))
        self.assertEqual(res['base_owned_names'],1)
        self.assertIn('>level.ipak_read,inner_zm',doc['zone_header']);self.assertIn('>level.ipak_read,outer_zm',doc['zone_header'])
        self.assertTrue(any(str(p).endswith('extra.ff') for p in doc['loads']))
        pinned=next(m for m in doc['modules'] if m['id']=='base_mod')
        self.assertEqual(pinned['role'],'base');self.assertEqual(pinned['reference'],{'name':'example/base_mod','commit':'a'*40})
    def test_emitted_composition_paths_are_posix_even_when_relpath_uses_backslashes(self):
        from pathlib import Path
        from unittest.mock import patch
        from plutonium_agent_toolkit.core.jobs import Job
        from plutonium_agent_toolkit.testing import planner
        source=self.root/'packs'/'stock_pack_test';source.mkdir(parents=True,exist_ok=True)
        (source/'composition.json').write_text(json.dumps({'schema':1,'name':'stock_pack_test','base':'stock','map':'zm_transit','modules':['../../modules/alpha'],'loads':['../z/base.ff'],'base_owned':['../l/base.csv']}))
        job=Job(self.root/'emit-job','test plan',[],timeout=600)
        plan={'source':str(source/'composition.json'),'modules':[{'id':'alpha','directory':str(self.root/'modules'/'alpha')}],'probe':True}
        real=planner.os.path.relpath
        def windows(path,start=None):return real(path,start).replace('/','\\')
        with patch.object(planner.os.path,'relpath',windows):planner.emit_composition(plan,job)
        data=json.loads((job.root/'composition.json').read_text())
        self.assertEqual(data['modules'],['../modules/alpha'])
        self.assertEqual(data['loads'],['../packs/z/base.ff'])
        self.assertEqual(data['base_owned'],['../packs/l/base.csv'])

class ProbePlanning(TestPlanRoute):
    def test_probe_is_added_and_background_soak_is_automated(self):
        m,c=self.member('alpha');c['maps']['zm_transit']['preconditions']=[{'verb':'power_on','actor':'agent'}];(m/'test-contract.json').write_text(json.dumps(c))
        p,pc=self.member('test_probe',tags=['test-only']);pc['soak']['rounds']=0;(p/'test-contract.json').write_text(json.dumps(pc))
        comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp),'--mode','background','--output',out,'--json']);self.assertEqual(code,0,row)
        from pathlib import Path
        plan=json.loads((Path(out)/'test-plan.json').read_text());self.assertTrue(plan['probe']);self.assertIn('test_probe',[m['id'] for m in plan['members']])
        self.assertEqual(plan['phases'][3]['steps'][0]['actor'],'agent')
        self.assertTrue((Path(out)/'composition.json').is_file())
    def test_release_profile_refuses_probe_contract(self):
        m,c=self.member('alpha');c['maps']['zm_transit']['preconditions']=[{'verb':'god','arg':'on','actor':'agent'}];(m/'test-contract.json').write_text(json.dumps(c))
        comp=self.composition(['alpha'],name='stock_x_pack')
        code,row=invoke(['test','plan','--composition',str(comp),'--output',self.out(),'--json']);self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_invalid')
    def test_build_plan_refuses_any_test_only_member_in_release(self):
        self.module('test_probe',tags=['test-only']);comp=self.composition(['test_probe'],name='stock_x_pub')
        code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json']);self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_invalid')
