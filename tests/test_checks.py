import json
import os
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
    def row(self,rows,prefix):
        """The one row with this id prefix. The check emits an `externals:` verdict and, separately,
        an `externals-unknown:` listing of names no table owns, so a caller must say which it means."""
        found=[r for r in rows if r['id'].startswith(prefix)]
        self.assertEqual(len(found),1,[r['id'] for r in rows])
        return found[0]
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
    def test_unknown_names_stay_not_counted_in_their_own_row(self):
        """Still not_counted — ignorance cannot refuse a build — but under `externals-unknown:`, so a
        name that is really an unresolved external is not read beside two unwitnessed builtins."""
        src='init()\n{\n    totally_unknown_thing();\n}\n'
        rows=checks.external_symbols('scripts/zm/a.gsc',src)
        unknown=self.row(rows,'externals-unknown:')
        self.assertEqual(unknown['outcome'],'not_counted')
        self.assertIn('totally_unknown_thing',unknown['detail'])
        self.assertIn('no table names an owner',unknown['detail'])
        self.assertNotIn('totally_unknown_thing',self.row(rows,'externals:')['detail'])
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
        """The `.csc` still gets no clean bill for a call witnessed only on the server VM: the name
        is carried out on the unknown row, never silently dropped from the verdict."""
        src='init()\n{\n    precachemodel("model");\n}\n'
        rows=checks.external_symbols('scripts/zm/effects.csc',src)
        unknown=self.row(rows,'externals-unknown:')
        self.assertEqual(unknown['outcome'],'not_counted')
        self.assertIn('precachemodel',unknown['detail'])
        self.assertNotIn('precachemodel',self.row(rows,'externals:')['detail'])
    def test_server_only_builtin_in_a_server_script_resolves(self):
        src='init()\n{\n    precachemodel("model");\n}\n'
        self.assertEqual(checks.external_symbols('scripts/zm/hello.gsc',src)[0]['outcome'],'passed')
    def test_non_t6_scripts_are_not_judged_against_t6_tables(self):
        src='init()\n{\n    get_players();\n}\n'
        rows=checks.external_symbols('scripts/a.gsc',src,game='iw5')
        self.assertEqual(rows[0]['outcome'],'not_counted')
    def test_builtin_spelling_is_case_insensitive(self):
        src='init()\n{\n    PrecacheModel("model");\n}\n'
        client=checks.external_symbols('scripts/zm/effects.csc',src)
        self.assertIn('precachemodel',self.row(client,'externals-unknown:')['detail'])
        server=checks.external_symbols('scripts/zm/hello.gsc',src)
        self.assertEqual(self.row(server,'externals:')['outcome'],'passed')
        self.assertEqual([r for r in server if r['id'].startswith('externals-unknown:')],[])
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
        self.assertNotEqual(self.row(rows,'externals:')['outcome'],'failed')
        unknown=self.row(rows,'externals-unknown:')
        self.assertEqual(unknown['outcome'],'not_counted')
        self.assertNotIn('maps/mp/zombies/_zm_utility',unknown['detail'])
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
    def test_a_bare_call_no_include_covers_fails_naming_the_owner_that_exports_it(self):
        """blast_furnace, 2026-09-15: `register_zombie_damage_callback(::ammo_damage)` with no
        #include at all. The check had no `_zm_spawner` row and said not_counted; the campaign group
        loaded and died at `COM_ERROR (6) Unresolved external "register_zombie_damage_callback"`."""
        src='main()\n{\n    register_zombie_damage_callback(::ammo_damage);\n}\nammo_damage()\n{\n}\n'
        row=self.row(checks.external_symbols('scripts/zm/halo_blast_furnace.gsc',src),'externals:')
        self.assertEqual(row['outcome'],'failed')
        self.assertIn('register_zombie_damage_callback',row['detail'])
        self.assertIn('maps/mp/zombies/_zm_spawner',row['detail'])
    def test_the_same_bare_call_with_its_include_passes(self):
        src=('#include maps\\mp\\zombies\\_zm_spawner;\nmain()\n{\n'
             '    register_zombie_damage_callback(::ammo_damage);\n}\nammo_damage()\n{\n}\n')
        self.assertEqual(self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')['outcome'],'passed')
    def test_the_same_call_qualified_needs_no_include(self):
        src=('main()\n{\n    maps\\mp\\zombies\\_zm_spawner::register_zombie_damage_callback(::ammo_damage);\n'
             '}\nammo_damage()\n{\n}\n')
        self.assertEqual(self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')['outcome'],'passed')
    def test_more_arguments_than_the_scope_takes_fails_naming_the_include_to_add(self):
        """qol_max_ammo, 2026-09-15: includes only maps/mp/_utility, whose get_players takes no
        argument. The call passed one and the load died at `Unresolved external "get_players" with 1
        parameters`; common_scripts/utility exports the one-argument form."""
        src='#include maps\\mp\\_utility;\nmain()\n{\n    players = get_players( self.team );\n}\n'
        row=self.row(checks.external_symbols('scripts/zm/qol_max_ammo.gsc',src),'externals:')
        self.assertEqual(row['outcome'],'failed')
        self.assertIn('get_players called with 1 argument',row['detail'])
        self.assertIn('only maps/mp/_utility exports it, with 0',row['detail'])
        self.assertIn('add #include common_scripts\\utility',row['detail'])
    def test_the_owner_that_declares_that_arity_being_in_scope_passes(self):
        """qol_instant_nuke includes both utilities and links: the scope holds a one-argument
        get_players, so the arities are judged per owner and never merged into one set."""
        src=('#include common_scripts\\utility;\n#include maps\\mp\\_utility;\n'
             'main()\n{\n    players = get_players( self.team );\n}\n')
        self.assertEqual(self.row(checks.external_symbols('scripts/zm/qol_instant_nuke.gsc',src),'externals:')['outcome'],'passed')
    def test_fewer_arguments_than_declared_is_not_a_fault(self):
        """GSC passes undefined for an argument a call omits; 564 bare calls in the patch_zm
        decompile do it, including maps/mp/_busing's two-argument setclientsysstate."""
        src='#include maps\\mp\\_utility;\nmain()\n{\n    setclientsysstate( "busCmd", 1 );\n}\n'
        self.assertEqual(self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')['outcome'],'passed')
    def test_a_qualified_call_with_an_arity_its_owner_lacks_fails(self):
        src='main()\n{\n    players = maps\\mp\\_utility::get_players( self.team );\n}\n'
        row=self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')
        self.assertEqual(row['outcome'],'failed')
        self.assertIn('maps/mp/_utility::get_players called with 1 argument',row['detail'])
    def test_a_qualified_call_naming_a_function_its_owner_does_not_export_fails(self):
        """The linker refuses `owner::name` for an absent name exactly as it refuses a bare miss;
        passing it would let a typo or a renamed helper through the only check that can see it."""
        src='main()\n{\n    maps\\mp\\_utility::no_such_helper();\n}\n'
        row=self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')
        self.assertEqual(row['outcome'],'failed')
        self.assertIn('maps/mp/_utility does not export no_such_helper',row['detail'])
    def test_a_qualified_call_on_the_wrong_owner_names_the_owner_that_does_export_it(self):
        """gersch, gstrike and matryoshka all qualify register_tactical_grenade_for_level to
        _zm_weapons; it is declared in _zm_utility, so the linker refuses all three."""
        src='main()\n{\n    maps\\mp\\zombies\\_zm_weapons::register_tactical_grenade_for_level("x");\n}\n'
        row=self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')
        self.assertEqual(row['outcome'],'failed')
        self.assertIn('maps/mp/zombies/_zm_weapons does not export register_tactical_grenade_for_level',row['detail'])
        self.assertIn('maps/mp/zombies/_zm_utility does',row['detail'])
    def test_a_qualified_call_into_a_partial_row_is_not_read_negatively(self):
        """The client rows carry only the names proven so far, so an absence there is silence, not
        evidence the client utility lacks the name."""
        src='main()\n{\n    clientscripts\\mp\\_utility::some_unproven_name();\n}\n'
        self.assertEqual(self.row(checks.external_symbols('scripts/zm/a.csc',src),'externals:')['outcome'],'passed')
    def test_a_qualified_call_into_a_path_no_row_owns_is_not_judged(self):
        """A pack's own script, or any path the table has no row for, is map-scripts' business."""
        src='main()\n{\n    maps\\mp\\halo\\mine::helper();\n}\n'
        self.assertEqual(self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')['outcome'],'passed')
    def test_a_string_literal_argument_is_counted_as_an_argument(self):
        """The mask blanks string literals; counting arguments on the blanked text would read
        `get_players("axis")` as passing none and miss the excess."""
        src='#include maps\\mp\\_utility;\nmain()\n{\n    get_players( "axis" );\n}\n'
        self.assertEqual(self.row(checks.external_symbols('scripts/zm/a.gsc',src),'externals:')['outcome'],'failed')
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
    def test_a_header_read_naming_a_bank_the_zone_folder_lacks_costs_no_slot(self):
        # 2026-09-15: a composition read lowmip, code_post_gfx_zm, common_zm and zm_factory and only
        # zm_factory.ipak was in zone/all, so three of the four counted reads opened nothing.
        plan={'modules':[],'scripts':[],'assets':[],'seeds':[],
              'zone_header':['>level.ipak_read,base','>level.ipak_read,lowmip','>level.ipak_read,code_post_gfx_zm',
                             '>level.ipak_read,common_zm','>level.ipak_read,zm_factory']}
        rows=[{'id':'image-bank-slots','count_source':'ipak_slots','bound':16}]
        out=checks.pool_checks(plan,rows,{'ipak_slots':12,'banks_present':['zm_factory','zm_transit']})
        pool=next(r for r in out if r['id']=='pool:image-bank-slots')
        self.assertEqual(pool['contribution'],1);self.assertEqual(pool['count'],13);self.assertEqual(pool['outcome'],'passed')
        self.assertEqual([c['id'] for c in pool['contributors']],['zm_factory'])
        self.assertEqual(pool['not_counted_reads'],['lowmip','code_post_gfx_zm','common_zm'])
        skipped={r['id']:r for r in out if r['id'].startswith('pool:image-bank-slots:')}
        self.assertEqual(sorted(skipped),['pool:image-bank-slots:code_post_gfx_zm','pool:image-bank-slots:common_zm','pool:image-bank-slots:lowmip'])
        for row in skipped.values():
            self.assertEqual(row['outcome'],'not_counted');self.assertIn('costs no slot',row['detail'])
    def test_without_the_bank_inventory_every_read_still_counts(self):
        plan={'modules':[],'scripts':[],'assets':[],'seeds':[],
              'zone_header':['>level.ipak_read,base','>level.ipak_read,lowmip','>level.ipak_read,code_post_gfx_zm',
                             '>level.ipak_read,common_zm','>level.ipak_read,zm_factory']}
        rows=[{'id':'image-bank-slots','count_source':'ipak_slots','bound':16}]
        out=checks.pool_checks(plan,rows,{'ipak_slots':12})
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]['contribution'],4);self.assertEqual(out[0]['count'],16);self.assertEqual(out[0]['outcome'],'passed')
        self.assertNotIn('not_counted_reads',out[0])
        # An inventory that carries every read counts them all, the same as no inventory at all.
        out=checks.pool_checks(plan,rows,{'ipak_slots':12,'banks_present':['lowmip','code_post_gfx_zm','common_zm','zm_factory']})
        self.assertEqual(len(out),1);self.assertEqual(out[0]['contribution'],4)
    def test_the_bank_inventory_can_take_a_pack_under_the_bound(self):
        plan={'modules':[],'scripts':[],'assets':[],'seeds':[],
              'zone_header':['>level.ipak_read,'+n for n in ('a','b','c','d','e')]}
        rows=[{'id':'image-bank-slots','count_source':'ipak_slots','bound':16}]
        self.assertEqual(checks.pool_checks(plan,rows,{'ipak_slots':12})[0]['outcome'],'failed')
        out=checks.pool_checks(plan,rows,{'ipak_slots':12,'banks_present':['a','b','c','d']})
        self.assertEqual(out[0]['outcome'],'passed');self.assertEqual(out[0]['count'],16)
    def test_the_shipped_occupancy_records_no_bank_inventory_yet(self):
        # banks_present is optional and a measured install fills it; nothing shipped claims one.
        maps=checks.knowledge.load('occupancy.json')['maps']
        self.assertTrue(maps and all('banks_present' not in row for row in maps.values()))
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

class DonorShadowing(unittest.TestCase):
    """The link log is the fact: it names the zone every rooted asset's copy came from."""
    def plan(self,**extra):
        row={'name':'b2_pack_test','seeds':[],'adapters':[],
             'loads':['/x/common_zm.ff','/x/moon-client60-blood.ff'],'base_loads':['common_zm'],
             'base_listings':['/x/common_zm-list.txt']}
        row.update(extra);return row
    def owned(self):return {'image':{'camo_gold_nml','weapon_camo_neutral'},'material':{'mc/mtl_stock'}}
    def test_link_sources_reads_the_zone_each_copy_came_from(self):
        text=('Loaded zone "moon-client60-blood" (T6)\n'
              'Loaded rawfile "scripts/zm/x.gsc" (src: disk)\n'
              'Loaded image "camo_gold_nml" (src: moon-client60-blood)\n'
              '\x1b[37mLoaded material "mc/mtl_stock" (src: common_zm)\x1b[0m\n')
        self.assertEqual(checks.link_sources(text),
                         [('image','camo_gold_nml','moon-client60-blood'),('material','mc/mtl_stock','common_zm')])
    def test_a_base_owned_name_rooted_from_a_donor_fails_with_the_count_and_the_names(self):
        sources=[('image','camo_gold_nml','moon-client60-blood'),
                 ('image','weapon_camo_neutral','moon-client60-blood'),
                 ('material','mc/mtl_stock','common_zm'),
                 ('image','t5_weapon_thundergun_n','disk')]
        out=checks.donor_shadowing(self.plan(),self.owned(),sources)
        self.assertEqual(out[0]['outcome'],'failed')
        self.assertEqual(out[0]['count'],2,'the base zone\'s own copy and a disk root are not shadowing')
        self.assertEqual(sorted(out[0]['names']),['camo_gold_nml','weapon_camo_neutral'])
        self.assertIn('moon-client60-blood',out[0]['detail'])
    def test_a_clean_link_log_passes_and_says_how_many_names_were_excluded(self):
        out=checks.donor_shadowing(self.plan(),self.owned(),[('image','t5_weapon_thundergun_n','disk')])
        self.assertEqual(out[0]['outcome'],'passed');self.assertEqual(out[0]['count'],0)
        self.assertIn('image 2',out[0]['detail']);self.assertIn('material 1',out[0]['detail'])
    def test_a_composition_that_loads_only_its_base_needs_no_listing(self):
        out=checks.donor_shadowing(self.plan(loads=['/x/common_zm.ff'],base_listings=[]),None)
        self.assertEqual(out[0]['outcome'],'passed');self.assertIn('no donor zone',out[0]['detail'])
    def test_listings_that_carry_no_image_or_material_decide_nothing(self):
        out=checks.donor_shadowing(self.plan(),{'image':set(),'material':set()})
        self.assertEqual(out[0]['outcome'],'not_counted');self.assertIn('no image or material row',out[0]['detail'])

class LooseOverrides(unittest.TestCase):
    """storage/t6/images is machine state: a loose file there wins over every bank, for every mod
    folder and for the bare game. A loose copy of a base-owned name is refusal-grade and no
    composition change can cause or cure it."""
    def plan(self,**extra):
        row={'name':'b2_pack_test','loads':['/x/common_zm.ff','/x/moon.ff'],'base_loads':['common_zm']}
        row.update(extra);return row
    def owned(self):return {'image':{'camo_zombies_nml','zom_icon_bullets'},'material':{'mc/mtl_stock'}}
    def loose(self,*names):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        directory=Path(temp.name)/'images';directory.mkdir()
        for name in names:(directory/name).write_bytes(b'IWi\x0d'+b'\0'*32)
        return directory
    def test_a_loose_file_carrying_a_base_owned_name_is_refusal_grade_and_named(self):
        out=checks.loose_overrides(self.plan(),self.owned(),
                                   self.loose('camo_zombies_nml.iwi','t5_weapon_thundergun_n.iwi','zom_icon_bullets.iwi'))
        self.assertEqual(out[0]['outcome'],'failed')
        self.assertEqual(out[0]['count'],2,'the loose file the base does not carry is not shadowing')
        self.assertEqual(sorted(out[0]['names']),['camo_zombies_nml','zom_icon_bullets'])
        self.assertTrue(out[0]['counted'])
        self.assertEqual(out[0]['loose_images'],3)
        self.assertEqual(sorted(r['id'] for r in out[1:]),
                         ['loose-overrides:camo_zombies_nml','loose-overrides:zom_icon_bullets'])
        self.assertTrue(all(r['outcome']=='failed' for r in out[1:]))
        self.assertIn('for the bare game',out[1]['detail'])
        self.assertIn('load the bare foundation as a control',out[1]['detail'])
    def test_a_loose_path_with_nothing_the_base_owns_passes_and_says_how_many_it_read(self):
        out=checks.loose_overrides(self.plan(),self.owned(),self.loose('t5_weapon_thundergun_n.iwi','notes.txt'))
        self.assertEqual(len(out),1);self.assertEqual(out[0]['outcome'],'passed')
        self.assertEqual(out[0]['loose_images'],1,'only .iwi files are loose textures')
        self.assertTrue(out[0]['counted'])
    def test_an_unconfigured_loose_path_is_not_counted_rather_than_passed(self):
        out=checks.loose_overrides(self.plan(),self.owned(),None)
        self.assertEqual(len(out),1);self.assertEqual(out[0]['outcome'],'not_counted')
        self.assertFalse(out[0]['counted'],'not counted and counted-clean are different facts')
        self.assertIn('no T6 storage folder is configured',out[0]['detail'])
        self.assertIn('pat configure --plutonium-storage-t6',out[0]['hint'])
    def test_a_configured_loose_path_that_is_absent_here_is_not_counted_either(self):
        out=checks.loose_overrides(self.plan(),self.owned(),self.loose()/'gone')
        self.assertEqual(out[0]['outcome'],'not_counted');self.assertFalse(out[0]['counted'])
        self.assertIn('is not a directory',out[0]['detail'])
        self.assertIn('not a pass either',out[0]['detail'])
    def test_a_scan_the_bound_cut_short_with_no_hit_is_not_counted(self):
        # The shadowing file may be one the bound never reached; a partial negative proves nothing.
        # Directory order is the filesystem's, so the bound is set where nothing can be read.
        directory=self.loose('camo_zombies_nml.iwi')
        with patch.object(checks,'MAX_LOOSE_FILES',0):
            out=checks.loose_overrides(self.plan(),self.owned(),directory)
        self.assertEqual(out[0]['outcome'],'not_counted');self.assertFalse(out[0]['counted'])
        self.assertIn('stopped before reading all of them',out[0]['detail'])
    def test_without_a_base_listing_nothing_is_compared(self):
        out=checks.loose_overrides(self.plan(),{'image':set()},self.loose('camo_zombies_nml.iwi'))
        self.assertEqual(out[0]['outcome'],'not_counted');self.assertIn('No base listing',out[0]['detail'])
        self.assertNotIn('counted',out[0],'the loose path was never read, so it is neither counted nor uncounted')
    def test_a_reference_row_name_is_not_a_base_copy(self):
        out=checks.loose_overrides(self.plan(),{'image':{',ref_only'}},self.loose('ref_only.iwi'))
        self.assertEqual(out[0]['outcome'],'not_counted')
    def test_the_match_is_case_insensitive_like_the_file_system_the_client_reads(self):
        out=checks.loose_overrides(self.plan(),{'image':{'Camo_Zombies_NML'}},self.loose('camo_zombies_nml.IWI'))
        self.assertEqual(out[0]['outcome'],'failed')
        self.assertEqual(out[0]['names'],['Camo_Zombies_NML'])
        self.assertIn('camo_zombies_nml.IWI',out[1]['detail'],'the row names the file as it is on disk')
    def test_the_row_list_is_bounded_and_the_summary_still_counts_them_all(self):
        names={f'camo_{i:03d}' for i in range(checks.MAX_LOOSE_ROWS+5)}
        out=checks.loose_overrides(self.plan(),{'image':names},self.loose(*(f'{n}.iwi' for n in names)))
        self.assertEqual(out[0]['count'],len(names))
        self.assertEqual(len(out)-1,checks.MAX_LOOSE_ROWS)
        self.assertIn(f'first {checks.MAX_LOOSE_ROWS} listed',out[0]['detail'])

class LooseImagesDirectory(unittest.TestCase):
    """The path is configured, never guessed: it comes from the storage key `pat configure` writes."""
    def home(self,config_row=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        home=Path(temp.name)/'home';home.mkdir()
        if config_row is not None:(home/'config.json').write_text(json.dumps(config_row))
        saved=os.environ.get('PAT_HOME');os.environ['PAT_HOME']=str(home)
        self.addCleanup(lambda:os.environ.__setitem__('PAT_HOME',saved) if saved else os.environ.pop('PAT_HOME',None))
        return home
    def test_the_configured_storage_folder_decides_the_loose_path(self):
        storage=str(Path(tempfile.gettempdir()).resolve()/'pat-storage-t6')
        self.home({'plutonium_storage_t6':storage})
        self.assertEqual(checks.loose_images_dir(),Path(storage)/'images')
    def test_no_storage_configured_is_none_so_the_check_reports_not_counted(self):
        self.home({})
        self.assertIsNone(checks.loose_images_dir())
    def test_a_configuration_that_cannot_be_read_is_none_rather_than_a_failed_plan(self):
        self.home({'not_a_known_key':'x'})
        self.assertIsNone(checks.loose_images_dir())

class ImageSources(unittest.TestCase):
    """A pack whose images have no pixels loads, renders blank and reports nothing; the plan has to say so."""
    def plan(self,**extra):
        row={'name':'b2_pack_test','assets':[],'seeds':[],'adapters':[],'zone_header':['>level.ipak_read,zm_factory']}
        row.update(extra);return row
    def image_row(self,path,module='wavegun'):
        return {'source':str(path),'target':'images/tex.iwi','type':'image','name':'tex','module':module}
    def test_an_embedded_image_with_bytes_is_a_header_not_a_delivery(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        iwi=Path(temp.name)/'tex.iwi';iwi.write_bytes(b'IWi\x0d'+b'\0'*32)
        out=checks.image_sources(self.plan(assets=[self.image_row(iwi)]))
        # A header in the zone is not pixels: packages/images/ is an artifact the engine never
        # reads, so a rooted .iwi is not_counted, never passed, and the row says where pixels live.
        self.assertEqual(out[0]['outcome'],'not_counted')
        self.assertEqual(out[1]['id'],'image-sources:tex')
        self.assertEqual(out[1]['outcome'],'not_counted')
        self.assertIn('storage/t6/images',out[1]['detail'])
        self.assertIn('never reads a mod folder',out[1]['detail'])
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
