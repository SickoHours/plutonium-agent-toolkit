import unittest
from plutonium_agent_toolkit.dev import checks

class OfflineChecks(unittest.TestCase):
    def test_over_budget_fails(self):
        rows=[{'id':'sound','count_source':'assets.soundbank','bound':2}]
        out=checks.pool_checks({'modules':[{'provides':{'soundbanks':['new']}}]},rows,{'assets':{'soundbank':2}})
        self.assertEqual(out[0]['outcome'],'failed')
    def test_no_counting_source_is_not_counted(self):
        out=checks.pool_checks({'modules':[]},[{'id':'unknown','count_source':None,'bound':9}],{})
        self.assertEqual(out[0]['outcome'],'not_counted')
    def test_projectile_union_cannot_be_inferred_from_weapon_count(self):
        out=checks.pool_checks({'modules':[{'provides':{'weapons':['gun']}}]},[{'id':'fx','count_source':'projectile_fx_distinct','bound':40}],{'projectile_fx_distinct':15})
        self.assertEqual(out[0]['outcome'],'not_counted')
    def test_unresolved_external_is_a_failed_symbol_row(self):
        out=checks.script_result('x.gsc','Unresolved external: bad_symbol with 2 parameters',False)
        self.assertEqual(out['outcome'],'failed');self.assertIn('bad_symbol',out['detail'])
    def test_successful_compilation_does_not_claim_external_resolution(self):
        self.assertEqual(checks.script_result('x.gsc','',True)['outcome'],'not_counted')
