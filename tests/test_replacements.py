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
