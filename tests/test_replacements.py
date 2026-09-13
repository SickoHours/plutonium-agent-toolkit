import json
from pathlib import Path
import unittest
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
