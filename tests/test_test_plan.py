import json
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke
from tests.test_testing_contracts import contract

class TestPlanRoute(CompositionFixture):
    def member(self, mid, **over):
        m=self.module(mid,maps=['zm_transit'],tests='test-contract.json',**over)
        c=contract(module=mid,maps={'zm_transit':{'preconditions':[]}})
        (m/'test-contract.json').write_text(json.dumps(c));return m,c
    def test_missing_contract_is_structured_and_receipted(self):
        self.member('alpha');self.module('beta',maps=['zm_transit'])
        comp=self.composition(['alpha','beta']);out=self.out()
        code,row=invoke(['test','plan','--composition',str(comp.parent),'--output',out,'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_missing',row)
        self.assertEqual(row['details']['field'],'/modules/1/tests')
        self.assertIn('receipt',row)
