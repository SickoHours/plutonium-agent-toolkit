import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
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
    def test_wildcard_declaration_accepts_concrete_contract_maps(self):
        maps = {'zm_transit': {'preconditions': []}, 'zm_factory': {'preconditions': []}}
        result = tc.validate_contract(contract(maps=maps), declaration=dict(DECL, maps=['*']))
        self.assertEqual(result['maps'], maps)
    def test_wildcard_declaration_still_rejects_invalid_contract_map_ids(self):
        for mid in ('*', 'invalid map', '../zm_transit'):
            with self.subTest(mid=mid), self.assertRaises(Failure) as cm:
                tc.validate_contract(contract(maps={mid: {'preconditions': []}}), declaration=dict(DECL, maps=['*']))
            self.assertEqual(cm.exception.code, 'input_invalid')
            self.assertEqual(cm.exception.details['field'], '/maps/' + mid.replace('~', '~0').replace('/', '~1'))
    def test_deeply_nested_contract_returns_input_invalid(self):
        nested = []
        for _ in range(sys.getrecursionlimit()):
            nested = [nested]
        with self.assertRaises(Failure) as cm:
            tc.validate_contract(contract(not_covered=nested), declaration=DECL)
        self.assertEqual(cm.exception.code, 'input_invalid')
        self.assertEqual(cm.exception.details['field'], '/')
        self.assertEqual(cm.exception.message, 'Invalid test contract structure')
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
    def test_oversized_bounded_integer_is_rejected_without_overflow(self):
        for value in (10**4000, -(10**4000)):
            with self.subTest(value='huge integer'):
                d=contract();d['steps'][0]['evidence']={'clip_before_s':value}
                with self.assertRaises(Failure) as cm:tc.validate_contract(d,declaration=DECL)
                self.assertEqual(cm.exception.code,'input_invalid')
                self.assertEqual(cm.exception.details['field'],'/steps/0/evidence/clip_before_s')
    def test_oversized_harness_bound_is_rejected_without_overflow(self):
        for key in ('min','max'):
            with self.subTest(key=key):
                d=contract();d['steps'][0]['check']={'source':'harness','key':'state.x',key:10**4000}
                with self.assertRaises(Failure) as cm:tc.validate_contract(d,declaration=DECL)
                self.assertEqual(cm.exception.code,'input_invalid')
                self.assertEqual(cm.exception.details['field'],'/steps/0/check/'+key)
    def test_number_keeps_finite_bounds_and_rejects_non_finite(self):
        for value in (0,60,1.5):
            tc.number(value,'/x',60)
        for value in (float('nan'),float('inf'),float('-inf'),-1,61,True):
            with self.subTest(value=repr(value)), self.assertRaises(Failure):
                tc.number(value,'/x',60)

class InspectContracts(CompositionFixture):
    def test_inspect_accepts_concrete_maps_for_wildcard_module(self):
        m = self.module('gobblegum_machine', maps=['*'], tests='test-contract.json')
        (m / 'test-contract.json').write_text(json.dumps(contract()))
        code, row = invoke(['module', 'inspect', str(m / 'module.json'), '--json'])
        self.assertEqual(code, 0, row)
        self.assertEqual(row['result']['metadata']['tests']['maps'], ['zm_transit'])
    def test_inspect_reports_deepcopy_recursion_as_diagnostic(self):
        m = self.module('gobblegum_machine', maps=['zm_transit'], tests='test-contract.json')
        # This depth parses as JSON but exceeds deepcopy's recursive call budget.
        depth = sys.getrecursionlimit() * 3 // 4
        raw = json.dumps(contract(not_covered='NESTED')).replace('"NESTED"', '[' * depth + '0' + ']' * depth)
        json.loads(raw)
        (m / 'test-contract.json').write_text(raw)
        code, row = invoke(['module', 'inspect', str(m / 'module.json'), '--json'])
        self.assertEqual(code, 1, row)
        diagnostic = row['details']['inspection']['diagnostics'][0]
        self.assertEqual(diagnostic['error_code'], 'input_invalid')
        self.assertEqual(diagnostic['field'], '/')
        self.assertEqual(diagnostic['message'], 'Invalid test contract structure')
    def test_inspect_reports_oversized_numeric_field_as_diagnostic(self):
        m=self.module('gobblegum_machine',maps=['zm_transit'],tests='test-contract.json')
        d=contract();d['steps'][0]['evidence']={'clip_before_s':10**4000}
        (m/'test-contract.json').write_text(json.dumps(d))
        code,row=invoke(['module','inspect',str(m/'module.json'),'--json'])
        self.assertEqual(code,1,row)
        self.assertEqual(row['error_code'],'input_invalid',row)
        diagnostic=row['details']['inspection']['diagnostics'][0]
        self.assertEqual(diagnostic['error_code'],'input_invalid')
        self.assertEqual(diagnostic['field'],'/steps/0/evidence/clip_before_s')
    def test_inspect_hashes_contract_and_reports_missing(self):
        m=self.module('gobblegum_machine',maps=['zm_transit'],tests='test-contract.json')
        code,row=invoke(['module','inspect',str(m/'module.json'),'--json']);self.assertEqual(code,1,row)
        self.assertEqual(row['details']['inspection']['diagnostics'][0]['field'],'/tests')
        raw=json.dumps(contract()).encode();(m/'test-contract.json').write_bytes(raw)
        code,row=invoke(['module','inspect',str(m/'module.json'),'--json']);self.assertEqual(code,0,row)
        self.assertEqual(row['result']['metadata']['tests'],{'sha256':hashlib.sha256(raw).hexdigest(),'steps':1,'human_steps':0,'maps':['zm_transit'],'requires_probe':False})
    def test_inspect_reports_probe_requirement_instead_of_refusing(self):
        # A module is inspected alone; whether a probe is present is the composition's fact, so
        # agent probe verbs are reported, never refused, here.
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
    def test_tests_path_symlink_cycle_is_a_structured_failure(self):
        # Python 3.12 Path.resolve() turns an ELOOP into RuntimeError; the contract must reject
        # it as input_invalid, not let it escape as an unstructured exception.
        m=self.module('gobblegum_machine',tests='test-contract.json')
        (m/'test-contract.json').write_text(json.dumps(contract()))
        real=Path.resolve
        def loop(self,*args,**kwargs):
            if self.name=='test-contract.json': raise RuntimeError('Symlink loop from %r' % str(self))
            return real(self,*args,**kwargs)
        with mock.patch.object(Path,'resolve',loop):
            code,row=invoke(['module','inspect',str(m/'module.json'),'--json'])
        self.assertEqual(code,1,row)
        self.assertEqual(row.get('error_code'),'input_invalid',row)
        diagnostic=row['details']['inspection']['diagnostics'][0]
        self.assertEqual(diagnostic['error_code'],'input_invalid')
        self.assertEqual(diagnostic['field'],'/tests')
