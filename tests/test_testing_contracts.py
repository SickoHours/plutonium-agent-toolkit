import copy
import hashlib
import json
import unittest
from plutonium_agent_toolkit.dev import testing_contracts as tc
from plutonium_agent_toolkit.core.errors import Failure
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke

DECL = {'id': 'gobblegum_machine', 'maps': ['zm_transit']}
def contract(**over):
    d = {'schema': 1, 'module': DECL['id'], 'maps': {'zm_transit': {'preconditions': [{'verb': 'power_on', 'actor': 'human', 'prompt': 'Turn on power.'}]}},
         'steps': [{'id': 's1', 'actor': 'agent', 'verifier': 'agent', 'action': {'verb': 'gobblegum', 'arg': 'load_machine'}, 'check': {'source': 'harness', 'key': 'state.playable', 'equals': '1'}}],
         'soak': {'rounds': 1}, 'human_only': [], 'not_covered': []}
    d.update(over); return d

class ContractTests(unittest.TestCase):
    def bad(self, data, field):
        with self.assertRaises(Failure) as cm: tc.validate_contract(data, declaration=DECL)
        self.assertEqual(cm.exception.details['field'], field)
    def test_valid_contract_normalizes(self):
        self.assertEqual(tc.validate_contract(contract(), declaration=DECL)['steps'][0]['id'], 's1')
    def test_unknown_verb_points_at_step(self):
        d=contract(); d['steps'][0]['action']['verb']='exec'; self.bad(d,'/steps/0/action/verb')
    def test_map_outside_declaration_refused(self):
        self.bad(contract(maps={'zm_factory': {'preconditions': []}}),'/maps/zm_factory')
    def test_human_step_needs_prompt_and_listing(self):
        s={'id':'h1','actor':'human','verifier':'human'}; self.bad(contract(steps=[s]),'/steps/0/prompt')
        s['prompt']='Listen.'; self.bad(contract(steps=[s]),'/human_only')
    def test_unknown_keys_at_every_level(self):
        for path in [(),('maps','zm_transit'),('maps','zm_transit','preconditions',0),('steps',0),('steps',0,'action'),('steps',0,'check'),('soak',)]:
            d=contract(); target=d
            for k in path: target=target[k]
            target['extra']=1; self.bad(d,'/'+ '/'.join(map(str,path+('extra',))))
    def test_probe_requires_human_and_prompt(self):
        d=contract(); p=d['maps']['zm_transit']['preconditions'][0];p.pop('actor');self.bad(d,'/maps/zm_transit/preconditions/0/actor')
        p['actor']='human';p.pop('prompt');self.bad(d,'/maps/zm_transit/preconditions/0/prompt')
    def test_bounds_and_types(self):
        for key,val in [('schema',True),('schema',2),('module','other'),('steps',contract()['steps']*65),('soak',{'rounds':11})]:
            self.bad(contract(**{key:val}),'/soak/rounds' if key=='soak' else '/'+key)
        d=contract();d['steps'][0]['action']['arg']='x;quit';self.bad(d,'/steps/0/action/arg')
        d=contract();d['steps']*=2;self.bad(d,'/steps/1/id')
    def test_checks_are_typed(self):
        for check in [{'source':'log','absent':'['},{'source':'dvar','name':'x;quit','equals':'1'}, {'source':'harness','key':'state.x','min':True}, {'source':'screenshot','equals':1}]:
            with self.assertRaises(Failure):tc.validate_contract(contract(steps=[dict(contract()['steps'][0],check=check)]),declaration=DECL)

class InspectContracts(CompositionFixture):
    def test_inspect_hashes_contract_and_reports_missing(self):
        m=self.module('gobblegum_machine',maps=['zm_transit'],tests='test-contract.json')
        code,row=invoke(['module','inspect',str(m/'module.json'),'--json']);self.assertEqual(code,1,row)
        self.assertEqual(row['details']['inspection']['diagnostics'][0]['field'],'/tests')
        raw=json.dumps(contract()).encode();(m/'test-contract.json').write_bytes(raw)
        code,row=invoke(['module','inspect',str(m/'module.json'),'--json']);self.assertEqual(code,0,row)
        self.assertEqual(row['result']['metadata']['tests'],{'sha256':hashlib.sha256(raw).hexdigest(),'steps':1,'human_steps':0,'maps':['zm_transit'],'requires_probe':False})
    def test_inspect_reports_probe_requirement_instead_of_refusing(self):
        # A module is inspected alone; whether a probe is present is the composition's fact, so
        # agent probe verbs are reported, never refused, here. The planner enforces them.
        m=self.module('gobblegum_machine',maps=['zm_transit'],tests='test-contract.json')
        d=contract(); d['maps']['zm_transit']['preconditions']=[{'verb':'power_on','actor':'agent'}]
        raw=json.dumps(d).encode();(m/'test-contract.json').write_bytes(raw)
        code,row=invoke(['module','inspect',str(m/'module.json'),'--json']);self.assertEqual(code,0,row)
        self.assertEqual(row['result']['validation'],'metadata-valid')
        self.assertTrue(row['result']['metadata']['tests']['requires_probe'])
        self.assertEqual(row['result']['metadata']['tests']['sha256'],hashlib.sha256(raw).hexdigest())
        with self.assertRaises(Failure) as cm: tc.validate_contract(d,declaration=DECL)
        self.assertEqual(cm.exception.details['field'],'/maps/zm_transit/preconditions/0/actor')
    def test_tests_path_cannot_escape(self):
        for path in ['../contract.json','/contract.json','a\\b.json']:
            m=self.module('gobblegum_machine',tests=path)
            code,row=invoke(['module','inspect',str(m/'module.json'),'--json']);self.assertEqual(code,1,row)
