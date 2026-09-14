import json
from pathlib import Path
import unittest
from unittest.mock import patch
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import compositions as c
from tests.test_compositions import declaration, CompositionFixture
from tests.test_dev_routes import invoke

class ReplacementDeclaration(unittest.TestCase):
    def test_normalizes_and_deduplicates(self):
        d=c.validate_declaration_metadata(declaration('x',replaces={'functions':['MAPS/MP/ZOMBIES/_ZM::ROUND_THINK','maps/mp/zombies/_zm::round_think'],'files':['Scripts/X.gsc','scripts/x.gsc']},entry={'replace':'scripts/zm/x::replace','register':'scripts/zm/x::register'}))
        self.assertEqual(d['replaces']['functions'],['maps/mp/zombies/_zm::round_think']);self.assertEqual(d['replaces']['files'],['scripts/x.gsc'])
    def test_engine_entry_points_are_base_owned(self):
        for target in ['maps/mp/zm_transit::main','maps/mp/zombies/_zm::codecallback_x','maps/mp/gametypes_zm/zclassic::main','maps/mp/x::gamemode_callback_setup']:
            with self.assertRaises(Failure) as cm:c.validate_declaration_metadata(declaration('x',replaces={'functions':[target],'files':[]}))
            self.assertEqual(cm.exception.details['field'],'/replaces/functions/0');self.assertIn('engine entry point',cm.exception.hint)
    def test_entry_is_a_function_reference(self):
        with self.assertRaises(Failure) as cm:c.validate_declaration_metadata(declaration('x',entry={'replace':'bad;quit','register':'x::y'}))
        self.assertEqual(cm.exception.details['field'],'/entry/replace')

class ReplacementCollision(CompositionFixture):
    def test_function_collision_cannot_be_decided_away(self):
        target='maps/mp/zombies/_zm::round_think'
        for mid in ['alpha','beta']:self.module(mid,replaces={'functions':[target],'files':[]})
        for decisions in [[],[{'collision':'function:'+target,'owner':'alpha','reason':'Try to override'}]]:
            comp=self.composition(['alpha','beta'],decisions=decisions)
            code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
            self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_invalid')
            self.assertEqual(row['details']['collisions'][0],{'collision':'function:'+target,'kind':'function','modules':['alpha','beta']})
    def test_whole_file_replacement_overlap_is_refused(self):
        for mid in ['alpha','beta']:self.module(mid,replaces={'functions':[],'files':['maps/mp/zombies/_zm.gsc']})
        comp=self.composition(['alpha','beta']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['details']['collisions'][0]['kind'],'file')

class ReplacementScan(CompositionFixture):
    def test_undeclared_source_target_is_refused(self):
        m=self.module('alpha');(m/'scripts/alpha.gsc').write_text('main() { replaceFunc(maps\\mp\\zombies\\_zm::round_think, ::mine); }\nmine() {}')
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'declaration_mismatch');self.assertIn('maps/mp/zombies/_zm::round_think',row['hint'])
    def test_declared_but_unfound_is_a_warning(self):
        self.module('alpha',replaces={'functions':['maps/mp/zombies/_zm::round_think'],'files':[]})
        comp=self.composition(['alpha']);out=self.out();code,row=invoke(['module','plan',str(comp),'--output',out,'--json'])
        self.assertEqual(code,0,row);self.assertTrue(json.loads((Path(out)/'plan.json').read_text())['warnings'])
    def test_scan_normalizes_case_and_separators(self):
        self.assertEqual(c.scan_replacements('replaceFunc(MAPS\\MP\\ZOMBIES\\_ZM::Round_Think, ::mine);'),{'maps/mp/zombies/_zm::round_think'})
    def test_replacefunc_text_in_comments_and_strings_is_ignored(self):
        # Prose in a comment or a quoted literal makes no replacement call: the scan sees code only.
        text=('// replaceFunc(maps\\mp\\zombies\\_zm::round_think, ::mine);\n'
              '/* replaceFunc(maps\\mp\\zombies\\_zm::other_think, ::mine); */\n'
              'note() { iprintln( "replaceFunc(maps\\\\mp\\\\zombies\\\\_zm::string_think, ::mine)" ); }\n')
        self.assertEqual(c.scan_replacements(text),set())
    def test_comment_only_replacement_does_not_fail_the_plan(self):
        m=self.module('alpha')
        (m/'scripts/alpha.gsc').write_text('// replaceFunc(maps\\mp\\zombies\\_zm::round_think, ::mine);\nmain() {}\n')
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,0,row)
    def test_helper_name_is_not_a_replacefunc_call(self):
        # A word boundary: `my_replaceFunc(...)` is a helper, not the engine replacement call.
        self.assertEqual(c.scan_replacements('my_replaceFunc(maps\\mp\\zombies\\_zm::round_think, ::mine);'),set())
    def test_helper_name_does_not_fail_the_plan(self):
        m=self.module('alpha')
        (m/'scripts/alpha.gsc').write_text('my_replaceFunc(maps\\mp\\zombies\\_zm::round_think, ::mine);\nmain() {}\n')
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,0,row)

class GeneratedEntry(CompositionFixture):
    def entry_member(self,mid):
        m=self.module(mid,entry={'replace':f'scripts/zm/{mid}::{mid}_replace','register':f'scripts/zm/{mid}::{mid}_register'})
        (m/f'scripts/{mid}.gsc').write_text(f'{mid}_replace() {{}}\n{mid}_register() {{}}')
        return m
    def test_entry_is_compiled_zoned_and_read_back(self):
        self.entry_member('alpha');self.entry_member('beta');comp=self.composition(['beta','alpha']);out=self.out()
        code,row=invoke(['module','build',str(comp),'--output',out,'--json']);self.assertEqual(code,0,row)
        target='scripts/zm/zz_stock_pack_test_entry.gsc'
        source=Path(out)/'generated-entry/zz_stock_pack_test_entry.gsc';self.assertTrue(source.is_file())
        s=source.read_text();self.assertLess(s.index('::alpha_replace();'),s.index('::beta_replace();'));self.assertLess(s.index('::alpha_register();'),s.index('::beta_register();'))
        self.assertIn('rawfile,'+target,(Path(out)/'project/zone_source/mod.zone').read_text())
        self.assertEqual(row['result']['rawfiles_verified'],3)
        self.assertTrue((Path(out)/'readback'/target).is_file())
    def test_entry_member_cannot_define_its_own_main(self):
        m=self.entry_member('alpha');(m/'scripts/alpha.gsc').write_text('main() {}')
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['details']['field'],'/modules/0/entry')
    def test_main_in_a_block_comment_is_not_an_entry_definition(self):
        m=self.entry_member('alpha')
        (m/'scripts/alpha.gsc').write_text('/*\nmain()\n*/\nalpha_replace() {}\nalpha_register() {}\n')
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,0,row)
    def test_main_call_at_column_zero_is_not_a_definition(self):
        m=self.entry_member('alpha')
        (m/'scripts/alpha.gsc').write_text('main();\nalpha_replace() {}\nalpha_register() {}\n')
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,0,row)
    def test_entry_main_definition_is_case_insensitive(self):
        m=self.entry_member('alpha')
        (m/'scripts/alpha.gsc').write_text('Main()\n{\n}\nalpha_replace() {}\nalpha_register() {}\n')
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['details']['field'],'/modules/0/entry')
    def test_entry_reference_matching_is_case_insensitive_and_emits_the_canonical_include(self):
        m=self.root/'modules'/'alpha';(m/'scripts').mkdir(parents=True)
        (m/'scripts'/'alpha.gsc').write_text('alpha_replace() {}\nalpha_register() {}\n')
        (m/'project.json').write_text(json.dumps({"schema":1,"game":"t6","mode":"zm","name":"alpha",
            "scripts":[{"source":"scripts/alpha.gsc","target":"scripts/zm/Alpha.gsc","instance":"server"}],"assets":[],"loads":[]}))
        (m/'module.json').write_text(json.dumps(declaration('alpha',
            entry={'replace':'scripts/zm/alpha::alpha_replace','register':'scripts/zm/alpha::alpha_register'})))
        comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['module','build',str(comp),'--output',out,'--json']);self.assertEqual(code,0,row)
        generated=(Path(out)/'generated-entry'/'zz_stock_pack_test_entry.gsc').read_text()
        self.assertIn('#include scripts\\zm\\Alpha;',generated)
        self.assertIn('scripts\\zm\\Alpha::alpha_replace();',generated)
        self.assertTrue((Path(out)/'generated-entry'/'scripts'/'zm'/'Alpha.gsc').is_file())
    def test_entry_reference_to_an_unknown_target_is_refused(self):
        m=self.entry_member('alpha')
        (m/'module.json').write_text(json.dumps(declaration('alpha',
            entry={'replace':'scripts/zm/other::alpha_replace','register':'scripts/zm/other::alpha_register'})))
        comp=self.composition(['alpha']);code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_invalid')
        self.assertIn('entry reference',row['message'].lower())
    def test_generated_entry_is_in_the_plan_scripts_and_checks(self):
        self.entry_member('alpha');comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['module','plan',str(comp),'--output',out,'--json']);self.assertEqual(code,0,row)
        plan=json.loads((Path(out)/'plan.json').read_text())
        target='scripts/zm/zz_stock_pack_test_entry.gsc'
        self.assertIn(target,[s['target'] for s in plan['scripts']])
        self.assertEqual(plan['generated_entry']['target'],target)
        self.assertIn('externals:'+target,[check['id'] for check in plan['checks']])
    def test_generated_entry_include_tree_is_staged_when_the_compiler_runs(self):
        m=self.entry_member('alpha')
        (m/'scripts'/'maps'/'mp').mkdir(parents=True)
        (m/'scripts'/'maps'/'mp'/'_utility.gsc').write_text('utility_think() {}\n')
        (m/'scripts'/'alpha.gsc').write_text('#include maps\\mp\\_utility;\n\nalpha_replace() { utility_think(); }\nalpha_register() {}\n')
        comp=self.composition(['alpha']);out=self.out()
        from plutonium_agent_toolkit.dev import scripts
        seen=[];real=scripts.execute
        def capture(args,child):
            root=Path(args.includes)
            seen.append({'input':args.input,'scripts_zm':(root/'scripts'/'zm'/'alpha.gsc').is_file(),
                         'utility':(root/'maps'/'mp'/'_utility.gsc').is_file()})
            return real(args,child)
        with patch.object(c.scripts,'execute',capture):
            code,row=invoke(['module','build',str(comp),'--output',out,'--json'])
        self.assertEqual(code,0,row)
        entry_calls=[call for call in seen if call['input'].endswith('zz_stock_pack_test_entry.gsc')]
        self.assertTrue(entry_calls,seen)
        self.assertTrue(all(call['scripts_zm'] and call['utility'] for call in entry_calls),entry_calls)
        root=Path(out)/'generated-entry'
        self.assertTrue((root/'scripts'/'zm'/'alpha.gsc').is_file())
        self.assertTrue((root/'maps'/'mp'/'_utility.gsc').is_file())
    def test_generated_entry_target_reservation_is_case_insensitive(self):
        self.entry_member('alpha')
        self.module('beta',script_target='scripts/zm/ZZ_stock_pack_test_entry.gsc')
        comp=self.composition(['alpha','beta']);code,row=invoke(['module','build',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_invalid')
        self.assertIn('generated entry',row['message'].lower())
    def test_generated_entry_counts_against_the_script_limit(self):
        from plutonium_agent_toolkit.dev import projects
        self.module('alpha');self.entry_member('gamma')
        comp=self.composition(['alpha','gamma'])
        with patch.object(projects,'MAX_SCRIPTS',2):
            code,row=invoke(['module','plan',str(comp),'--output',self.out(),'--json'])
        self.assertEqual(code,1,row);self.assertEqual(row['error_code'],'input_limit')
    def test_iw5_entry_target_uses_the_title_namespace(self):
        d=self.root/'modules'/'alpha';(d/'scripts').mkdir(parents=True)
        (d/'scripts'/'alpha.gsc').write_text('alpha_replace() {}\nalpha_register() {}\n')
        (d/'project.json').write_text(json.dumps({"schema":1,"game":"iw5","mode":"mp","name":"alpha",
            "scripts":[{"source":"scripts/alpha.gsc","target":"scripts/alpha.gsc","instance":"server"}],"assets":[],"loads":[]}))
        (d/'module.json').write_text(json.dumps(declaration('alpha',game='iw5',
            entry={'replace':'scripts/alpha::alpha_replace','register':'scripts/alpha::alpha_register'})))
        pack=self.root/'packs'/'stock_iw5_test';pack.mkdir(parents=True)
        (pack/'composition.json').write_text(json.dumps({"schema":1,"name":"stock_iw5_test","game":"iw5","base":"stock",
            "map":"mp_dome","modules":["../../modules/alpha"],"loads":[]}))
        code,row=invoke(['module','plan',str(pack/'composition.json'),'--output',self.out(),'--json'])
        self.assertEqual(code,0,row)
        plan=json.loads((Path(row['result']['output'])/'plan.json').read_text())
        self.assertIn('scripts/zz_stock_iw5_test_entry.gsc',[s['target'] for s in plan['scripts']])
        self.assertNotIn('scripts/zm/zz_stock_iw5_test_entry.gsc',[s['target'] for s in plan['scripts']])

class LooseScripts(CompositionFixture):
    def test_compiled_scripts_are_emitted_loose_beside_the_package(self):
        self.module('alpha');comp=self.composition(['alpha']);out=self.out()
        code,row=invoke(['module','build',str(comp),'--output',out,'--json']);self.assertEqual(code,0,row)
        self.assertEqual(row['result']['loose_scripts'],['scripts/zm/alpha.gsc'])
        loose=Path(out)/'packages/scripts/zm/alpha.gsc';self.assertTrue(loose.is_file())
        self.assertEqual(loose.read_bytes(),(Path(out)/'readback/scripts/zm/alpha.gsc').read_bytes())
