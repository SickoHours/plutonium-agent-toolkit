import json
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
    def test_a_client_script_is_not_refused_for_a_server_only_export(self):
        """A `.csc` links against client scripts only; no stock client script includes a `maps/` path,
        so resolving a server export here would demand an include that cannot exist."""
        src='init()\n{\n    e = self get_player_equipment();\n}\n'
        rows=checks.external_symbols('scripts/zm/weapon.csc',src)
        self.assertEqual(rows[0]['outcome'],'not_counted')
        self.assertNotIn('maps/mp/zombies/_zm_utility',rows[0]['detail'])
    def test_a_server_script_is_still_refused_for_the_same_export(self):
        src='init()\n{\n    e = self get_player_equipment();\n}\n'
        rows=checks.external_symbols('scripts/zm/weapon.gsc',src)
        self.assertEqual(rows[0]['outcome'],'failed')
        self.assertIn('maps/mp/zombies/_zm_utility',rows[0]['detail'])
    def test_a_client_export_with_its_client_include_resolves(self):
        src=('#include clientscripts\\mp\\_utility;\n#include clientscripts\\mp\\zombies\\_zm_utility;\n'
             'init()\n{\n    level.a = add_to_array(level.a,self);\n    onplayerconnect_callback(::watch);\n}\nwatch()\n{\n}\n')
        self.assertEqual(checks.external_symbols('scripts/zm/weapon.csc',src)[0]['outcome'],'passed')
    def test_a_client_export_without_its_client_include_fails_naming_the_client_path(self):
        src='init()\n{\n    level.a = add_to_array(level.a,self);\n}\n'
        rows=checks.external_symbols('scripts/zm/weapon.csc',src)
        self.assertEqual(rows[0]['outcome'],'failed')
        self.assertIn('clientscripts/mp/_utility',rows[0]['detail'])
        self.assertNotIn('common_scripts/utility',rows[0]['detail'])
    def test_a_vm_with_no_export_rows_is_not_counted_rather_than_failed(self):
        table={'schema':1,'exports':{'common_scripts/utility':{'vm':'server','functions':['add_to_array']}}}
        with patch.object(checks.knowledge,'load',return_value=table):
            rows=checks.external_symbols('scripts/zm/weapon.csc','init()\n{\n    add_to_array(level.a,self);\n}\n')
        self.assertEqual(rows[0]['outcome'],'not_counted')
        self.assertIn('client',rows[0]['detail'])

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

class ImageSources(unittest.TestCase):
    """A pack whose images have no pixels loads, renders blank and reports nothing; the plan has to say so."""
    def plan(self,**extra):
        row={'name':'b2_pack_test','assets':[],'seeds':[],'adapters':[],'zone_header':['>level.ipak_read,zm_factory']}
        row.update(extra);return row
    def image_row(self,path,module='wavegun'):
        return {'source':str(path),'target':'images/tex.iwi','type':'image','name':'tex','module':module}
    def test_an_embedded_image_with_bytes_carries_its_own_pixels(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        iwi=Path(temp.name)/'tex.iwi';iwi.write_bytes(b'IWi\x0d'+b'\0'*32)
        out=checks.image_sources(self.plan(assets=[self.image_row(iwi)]))
        self.assertEqual(out[0]['outcome'],'passed')
        self.assertEqual(out[1],{'id':'image-sources:tex','outcome':'passed',
                                 'detail':'wavegun ships tex as its own image asset; the linker reads the file from disk and the build stages it beside the package, where the client reads its pixels'})
    def test_a_declared_image_whose_file_is_absent_or_empty_fails(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        empty=Path(temp.name)/'tex.iwi';empty.write_bytes(b'')
        for source in (Path(temp.name)/'gone.iwi',empty):
            out=checks.image_sources(self.plan(assets=[self.image_row(source)]))
            self.assertEqual(out[1]['outcome'],'failed');self.assertIn('missing or empty',out[1]['detail'])
    def test_a_referenced_image_is_never_passed_without_a_readback(self):
        out=checks.image_sources(self.plan(seeds=[{'id':'thundergun','roots':['image,t5_weapon_thundergun_n','rawfile,x.gsc']}]))
        self.assertEqual([r['outcome'] for r in out],['not_counted','not_counted'])
        self.assertIn('cannot be read offline',out[1]['detail'])
        self.assertIn('the header reads zm_factory',out[1]['detail'])
    def test_a_readback_turns_a_referenced_image_into_a_refusal_naming_the_member_and_the_hint(self):
        measured={'pack':'b2_pack_test','missing':{'t5_weapon_thundergun_n':'arsenal-thundergun prepared images/'},'present':[],'enumerated':False,'banks':[]}
        out=checks.image_sources(self.plan(seeds=[{'id':'thundergun','roots':['image,t5_weapon_thundergun_n','image,camo_code_nml']}]),measured)
        self.assertEqual(out[0]['outcome'],'failed');self.assertIn('1 of 2',out[0]['detail'])
        failed=next(r for r in out[1:] if r['outcome']=='failed')
        self.assertEqual(failed['id'],'image-sources:t5_weapon_thundergun_n')
        self.assertIn('thundergun references',failed['detail']);self.assertIn('located: arsenal-thundergun prepared images/',failed['detail'])
        self.assertEqual(next(r for r in out[1:] if r['id'].endswith('camo_code_nml'))['outcome'],'passed')
    def test_an_image_no_member_declares_is_still_named(self):
        out=checks.image_sources(self.plan(),{'pack':None,'missing':{'thermal_gradient2':None},'present':[],'enumerated':False,'banks':[]})
        self.assertEqual(out[1]['id'],'image-sources:thermal_gradient2')
        self.assertIn('No member declares thermal_gradient2',out[1]['detail'])
        self.assertIn('resolved from a zone the composition loads',out[1]['detail'])
    def test_a_readback_of_another_pack_decides_nothing(self):
        out=checks.image_sources(self.plan(),{'pack':'other_pack','missing':{'x':None},'present':[],'enumerated':False,'banks':[]})
        self.assertEqual(len(out),1);self.assertEqual(out[0]['outcome'],'not_counted');self.assertIn("'other_pack'",out[0]['detail'])
    def test_an_enumerated_readback_that_omits_a_referenced_image_decides_nothing_for_it(self):
        measured={'pack':None,'missing':{},'present':['other'],'enumerated':True,'banks':[]}
        out=checks.image_sources(self.plan(seeds=[{'id':'thundergun','roots':['image,t5_weapon_thundergun_n']}]),measured)
        self.assertEqual(out[1]['outcome'],'not_counted');self.assertIn('does not name it at all',out[1]['detail'])

    def test_a_plan_that_names_no_image_says_the_plan_is_not_the_counting_source(self):
        out=checks.image_sources(self.plan())
        self.assertEqual(len(out),1);self.assertEqual(out[0]['outcome'],'not_counted')
        self.assertIn('a readback beside the banks',out[0]['detail'])

class ImageReports(unittest.TestCase):
    def report(self,data):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'image-check.json';path.write_text(json.dumps(data));return path
    def test_the_documented_shape_names_present_and_missing_images(self):
        out=checks.read_image_report(self.report({'pack':'p','images':[{'name':'a','pixels':'present'},{'name':'b','pixels':'missing','located':'zm_moon'}]}))
        self.assertEqual(out['pack'],'p');self.assertEqual(out['present'],['a']);self.assertEqual(out['missing'],{'b':'zm_moon'})
        self.assertTrue(out['enumerated'],'the documented shape names every image it checked')
    def test_a_tool_that_lists_only_what_it_could_not_resolve_is_read_and_its_paths_are_not(self):
        out=checks.read_image_report(self.report({'pack':'p','images_dumped':252,'banks_opened':{'base':'/elsewhere/zone/base.ipak'},
                                                  'rows':[{'image':'b','sources':[{'path':'/elsewhere/x.iwi'}]},{'image':'c'}]}))
        self.assertEqual(sorted(out['missing']),['b','c']);self.assertEqual(out['banks'],['base'])
        self.assertFalse(out['enumerated'],'a missing-only list says nothing about the images it omits')
        self.assertNotIn('/elsewhere',json.dumps(out))
    def test_a_file_that_is_not_a_report_is_refused_with_a_hint(self):
        with self.assertRaises(Failure) as caught:
            checks.read_image_report(self.report({'hello':'world'}))
        self.assertEqual(caught.exception.code,'input_invalid');self.assertIn('images_without_pixels',caught.exception.hint)
