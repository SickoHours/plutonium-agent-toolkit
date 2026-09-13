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

class ExternalSymbols(unittest.TestCase):
    """Unqualified calls to stock exports without the matching #include link-fail in the engine."""
    def test_unqualified_stock_call_without_include_fails(self):
        src='init()\n{\n    players = get_players();\n    x = self get_player_equipment();\n}\n'
        rows=checks.external_symbols('scripts/zm/a.gsc',src)
        self.assertEqual(rows[0]['outcome'],'failed');self.assertIn('get_players',rows[0]['detail']);self.assertIn('common_scripts/utility',rows[0]['detail'])
        self.assertIn('get_player_equipment',rows[0]['detail'])
    def test_include_or_qualification_resolves(self):
        src='#include common_scripts\\utility;\ninit()\n{\n    players = get_players();\n    e = self maps\\mp\\zombies\\_zm_utility::get_player_equipment();\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed')
    def test_local_definition_and_witnessed_builtins_are_not_externals(self):
        src='init()\n{\n    helper();\n    iprintln("x");\n}\nhelper()\n{\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed')
    def test_comments_are_not_calls(self):
        src='// get_players( is only a comment\n/* get_player_equipment( */\ninit()\n{\n    helper();\n}\nhelper()\n{\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed')
    def test_unknown_names_stay_not_counted(self):
        src='init()\n{\n    totally_unknown_thing();\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'not_counted')
