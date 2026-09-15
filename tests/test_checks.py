import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.core.jobs import Job
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

class PreLinkScriptChecks(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);job=Job(root/'job','module build',[],timeout=600)
        source=root/'module'/'x.gsc';source.parent.mkdir();source.write_text('main(){}\n')
        return job,source
    def test_check_scripts_uses_the_source_directory_for_sibling_includes(self):
        job,source=self.fixture();seen=[]
        def fake(args,child):seen.append(args);return {'files':[]}
        with patch.object(checks.scripts,'execute',fake):
            checks.check_scripts([(source,Path('scripts/zm/x.gsc'),'server')],SimpleNamespace(timeout=600),job,'t6')
        self.assertEqual(seen[0].includes,str(source.parent))
    def test_check_scripts_clamps_each_child_deadline_to_the_parent_remaining_time(self):
        job,source=self.fixture();job.deadline=time.monotonic()+5
        children=[]
        def fake(args,child):children.append(child);return {'files':[]}
        with patch.object(checks.scripts,'execute',fake):
            checks.check_scripts([(source,Path('a.gsc'),'server'),(source,Path('b.gsc'),'client')],SimpleNamespace(timeout=600),job,'t6')
        self.assertEqual(len(children),2)
        for child in children:self.assertLessEqual(child.deadline,job.deadline+0.1)
    def test_check_scripts_stops_once_the_parent_deadline_has_passed(self):
        job,source=self.fixture();calls=[]
        def fake(args,child):
            calls.append(args.input);job.deadline=time.monotonic()-1;return {'files':[]}
        with patch.object(checks.scripts,'execute',fake):
            with self.assertRaises(Failure) as cm:
                checks.check_scripts([(source,Path('a.gsc'),'server'),(source,Path('b.gsc'),'client')],SimpleNamespace(timeout=600),job,'t6')
        self.assertEqual(cm.exception.code,'backend_timeout')
        self.assertEqual(len(calls),1)
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
    def test_a_string_literal_is_not_an_unqualified_call(self):
        src='init()\n{\n    iprintln("get_players(");\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed')
    def test_escaped_quotes_and_comment_looking_strings_are_masked(self):
        src=('init()\n{\n'
             '    iprintln("a \\" get_players( b");\n'
             '    iprintln("// setclientfield( in a string");\n'
             '    iprintln("/* get_player_equipment( in a string */");\n'
             '}\n')
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed')
    def test_a_call_at_column_zero_is_not_a_local_definition(self):
        src='get_players();\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'failed')
    def test_a_local_definition_followed_by_a_body_is_not_an_external(self):
        src='helper()\n{\n}\ninit()\n{\n    helper();\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed')
    def test_server_only_builtin_in_a_client_script_never_passes(self):
        src='init()\n{\n    precachemodel("model");\n}\n'
        rows=checks.external_symbols('scripts/zm/effects.csc',src)
        self.assertNotEqual(rows[0]['outcome'],'passed')
        self.assertEqual(rows[0]['outcome'],'not_counted')
        self.assertIn('precachemodel',rows[0]['detail'])
    def test_server_only_builtin_in_a_server_script_resolves(self):
        src='init()\n{\n    precachemodel("model");\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/hello.gsc',src)[0]['outcome'],'passed')
    def test_non_t6_scripts_are_not_judged_against_t6_tables(self):
        src='init()\n{\n    get_players();\n}\n'
        rows=checks.external_symbols('scripts/a.gsc',src,game='iw5')
        self.assertEqual(rows[0]['outcome'],'not_counted')
    def test_builtin_spelling_is_case_insensitive(self):
        src='init()\n{\n    PrecacheModel("model");\n}\n'
        self.assertNotEqual(checks.external_symbols('scripts/zm/effects.csc',src)[0]['outcome'],'passed')
        self.assertEqual(checks.external_symbols('scripts/zm/hello.gsc',src)[0]['outcome'],'passed')
    def test_stock_export_spelling_is_case_insensitive(self):
        rows=checks.external_symbols('scripts/zm/a.gsc','Get_Players();\n')
        self.assertEqual(rows[0]['outcome'],'failed')
        self.assertIn('get_players',rows[0]['detail'])
    def test_an_indented_local_definition_still_resolves(self):
        src='main()\n{\n    helper();\n}\n    helper()\n    {\n    }\n'
        self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed')
    def test_an_indented_include_still_covers_its_stock_call(self):
        for directive in ('#include','#Include'):
            src='    '+directive+' common_scripts\\utility;\ninit()\n{\n    players = get_players();\n}\n'
            self.assertEqual(checks.external_symbols('scripts/zm/a.gsc',src)[0]['outcome'],'passed',directive)

class PoolAccounting(unittest.TestCase):
    """The two pools that refused real packs at mod selection on 2026-09-14 are counted offline."""
    def test_rawfiles_count_recipe_scripts_delivered_assets_and_seed_roots_and_name_contributors(self):
        plan={'modules':[{'id':'wavegun','provides':{}},{'id':'hud','provides':{}}],
              'scripts':[{'target':'scripts/zm/hud.gsc','module':'hud'}],
              'assets':[{'target':'model_export/a.glb','type':'rawfile','module':'wavegun'},
                        {'target':'model_export/b.glb','type':'rawfile','module':'wavegun','deliver':False},
                        {'target':'xmodel/a.json','type':'xmodel','module':'wavegun'}],
              'seeds':[{'id':'wavegun','roots':['rawfile,animtrees/x.atr','weapon,gun']}],'zone_header':[]}
        rows=[{'id':'rawfile-assets','count_source':'assets.rawfile','bound':1024}]
        out=checks.pool_checks(plan,rows,{'assets':{'rawfile':1022}})
        self.assertEqual(out[0]['outcome'],'failed');self.assertEqual(out[0]['count'],1025);self.assertEqual(out[0]['contribution'],3)
        self.assertEqual(out[0]['contributors'][0],{'id':'wavegun','count':2});self.assertIn('wavegun (2)',out[0]['detail'])
        self.assertEqual(checks.footprint(plan)['hud'],{'rawfiles':1,'soundbanks':[],'scripts':1})
    def test_image_bank_reads_beyond_the_startup_set_count_against_slots(self):
        plan={'modules':[],'scripts':[],'assets':[],'seeds':[],
              'zone_header':['>level.ipak_read,base','>level.ipak_read,zm_factory','>level.ipak_read,dlc0','>level.ipak_read,dlc2','>level.ipak_read,dlc3','>level.ipak_read,dlc3']}
        rows=[{'id':'image-bank-slots','count_source':'ipak_slots','bound':16}]
        out=checks.pool_checks(plan,rows,{'ipak_slots':12})
        self.assertEqual(out[0]['contribution'],4);self.assertEqual(out[0]['outcome'],'passed')
        plan['zone_header']+=['>level.ipak_read,zm_temple']
        out=checks.pool_checks(plan,rows,{'ipak_slots':12})
        self.assertEqual(out[0]['outcome'],'failed');self.assertEqual([c['id'] for c in out[0]['contributors']],['zm_factory','dlc0','dlc2','dlc3','zm_temple'])
    def test_base_token_maps_to_the_occupancy_foundation(self):
        self.assertEqual(checks.foundation_of('b2'),'dlc5-beta2');self.assertEqual(checks.foundation_of('stock'),'stock')
        rows=checks.evaluate({'base':'b2','map':'zm_factory','modules':[],'scripts':[],'assets':[],'seeds':[],'zone_header':[]})
        rawfile=next(r for r in rows if r['id']=='pool:rawfile-assets')
        self.assertEqual(rawfile['outcome'],'passed');self.assertEqual(rawfile['base'],481)
    def test_shipped_limits_include_rawfiles_and_image_bank_slots(self):
        rows=checks.evaluate({'base':'stock','map':'zm_transit','modules':[],'scripts':[],'assets':[],'seeds':[],'zone_header':[]})
        ids={r['id'] for r in rows};self.assertIn('pool:rawfile-assets',ids);self.assertIn('pool:image-bank-slots',ids)

class MapScriptExternals(unittest.TestCase):
    """Beta 2 dropped _zm_perk_divetonuke from Der Riese; a module including it links, then COM_ERRORs at load."""
    def test_a_script_another_pack_member_provides_is_carried(self):
        src='#include maps\\mp\\halo\\cr35_buildables;\nmain(){ maps\\mp\\halo\\cr35_buildables::register(); }\n'
        out=checks.map_script_externals('scripts/zm/acid.gsc',src,'zm_factory','dlc5-beta2')
        self.assertEqual(out[0]['outcome'],'failed')
        out=checks.map_script_externals('scripts/zm/acid.gsc',src,'zm_factory','dlc5-beta2',provided={'maps/mp/halo/cr35_buildables.gsc'})
        self.assertEqual(out[0]['outcome'],'passed')
    def test_include_of_a_script_the_map_lacks_fails(self):
        src='#include maps\\mp\\zombies\\_zm_perk_divetonuke;\nmain(){ maps\\mp\\zombies\\_zm_perk_divetonuke::enable_divetonuke_perk_for_level(); }\n'
        out=checks.map_script_externals('scripts/zm/phd.gsc',src,'zm_factory','dlc5-beta2')
        self.assertEqual(out[0]['outcome'],'failed');self.assertIn('_zm_perk_divetonuke',out[0]['detail'])
    def test_carried_script_passes_and_unknown_map_is_not_counted(self):
        src='#include maps\\mp\\zombies\\_zm_utility;\nmain(){ x = maps\\mp\\zombies\\_zm_perks::vending_trigger_think(); }\n'
        self.assertEqual(checks.map_script_externals('scripts/zm/a.gsc',src,'zm_factory','dlc5-beta2')[0]['outcome'],'passed')
        self.assertEqual(checks.map_script_externals('scripts/zm/a.gsc',src,'zm_nowhere','dlc5-beta2')[0]['outcome'],'not_counted')
        self.assertEqual(checks.map_script_externals('scripts/zm/a.gsc','main(){}\n','zm_factory','dlc5-beta2')[0]['outcome'],'not_counted')
