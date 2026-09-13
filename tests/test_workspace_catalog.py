"""Workspace observations do not promote declarations or other scopes into facts."""
import json
import tempfile
import unittest
from pathlib import Path
from plutonium_agent_toolkit.dev.workspace_catalog import catalog
from plutonium_agent_toolkit.core.errors import Failure
from test_workspace import invoke

class WorkspaceCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.write('workspace.json', {})
        self.write('modules/example/module.json', {'schema':1,'id':'example','version':'1.0','category':'weapons','kind':'firearm','recipe':'recipe.json','distribution':'private','bases':['stock'],'maps':['zm_transit'],'provides':{'soundbanks':['example.all']}})

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_missing_workspace_refused_and_absent_registries_are_unknown(self):
        with self.assertRaises(Failure): catalog(str(self.root / 'missing'))
        row = catalog(str(self.root))['modules'][0]
        self.assertEqual(row['build_records'], [])
        self.assertIsNone(row['weapon_class'])
        self.assertIsNone(row['icon_binding'])

    def test_preserves_build_scopes_and_independent_flags(self):
        self.write('registry/module-recipes.json', {'recipes':[{'id':'example','catalog_id':'example','builds':[{'id':'stock-1','foundation':'stock','map':'zm_transit','offline_verified':True,'installed':False,'receipt':'jobs/one/receipt.json'}]}]})
        self.write('registry/t6-modules.json', {'modules':[{'id':'example','weapon_class':'Pistols','build_revisions':[{'id':'other-1','foundation':'other','map':'zm_factory','runtime_verified':True,'player_accepted':False}]}]})
        code, reply = invoke(['workspace','catalog',str(self.root),'--json'])
        self.assertEqual(code,0,reply)
        row = reply['result']['modules'][0]
        self.assertEqual(row['weapon_class'],'Pistols')
        self.assertEqual(row['provides'],{'soundbanks':['example.all']})
        self.assertEqual(len(row['build_records']),2)
        built, loaded = row['build_records']
        self.assertEqual(built['map'],'zm_transit')
        self.assertFalse(built['installed'])
        self.assertIsNone(built['runtime_verified'])
        self.assertTrue(loaded['runtime_verified'])
        self.assertIsNone(loaded['offline_verified'])
        self.assertFalse(loaded['player_accepted'])
        self.assertEqual(loaded['source'],'registry/t6-modules.json')
        self.assertNotIn('launched', loaded)
        self.assertNotIn('captured', loaded)

    def test_explicit_icon_binding_only_texture_samples_do_not_become_portraits(self):
        asset = {'url':'local-media/'+'a'*64+'.webp','binding':{'role':'texture sample; not a module portrait'}}
        art = self.write('art/local-catalog.json',{'modules':[{'declarationId':'example','artwork':[asset],'coverSymbol':{'url':'library-symbols/weapon.svg'}}]})
        row = catalog(str(self.root),str(art))['modules'][0]
        self.assertIsNone(row['icon_binding'])
        self.assertEqual(row['symbol'],'symbol-weapon')
        media = self.root / asset['url']
        media = self.root / 'art' / asset['url']
        media.parent.mkdir(parents=True)
        media.write_bytes(b'webp fixture')
        asset['binding']['role']='shared HUD icon'
        self.write('art/local-catalog.json',{'modules':[{'declarationId':'example','artwork':[asset]}]})
        self.assertEqual(catalog(str(self.root),str(art))['modules'][0]['icon_binding']['role'],'shared HUD icon')

    def test_invalid_declaration_is_reported_without_hiding_other_rows(self):
        self.write('modules/invalid/module.json', {'schema':99})
        value = catalog(str(self.root))
        self.assertEqual(len(value['modules']),1)
        self.assertEqual(len(value['diagnostics']),1)

    def test_foundation_staging_comes_from_descriptor_and_file_presence(self):
        self.write('foundations/foundation.json',{'id':'example-base','profile_prefix':'test','maps':{'zm_factory':{},'zm_moon':{}},'private_descriptor':'../base/descriptor.json'})
        self.write('base/descriptor.json',{'link_loads':{'zm_factory':['zone.ff']}})
        (self.root/'base/zone.ff').write_bytes(b'fixture')
        found = catalog(str(self.root))['foundations']
        self.assertTrue(next(r for r in found if r['map']=='zm_factory')['staged'])
        self.assertFalse(next(r for r in found if r['map']=='zm_moon')['staged'])
        self.assertEqual(found[0]['source'],'foundations/foundation.json')
