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

    def test_non_object_foundation_maps_is_a_diagnostic(self):
        self.write('foundations/bad.json', {'id':'base','profile_prefix':'stock','maps':[], 'link_loads':{'zm_factory':[]}})
        result = catalog(str(self.root))
        self.assertEqual(len(result['modules']), 1)
        self.assertIn('maps must be an object', result['diagnostics'][0]['message'])

    def test_non_object_cover_symbol_is_a_module_diagnostic(self):
        art = self.write('art.json', {'modules':[{'declarationId':'example','coverSymbol':[]}]})
        result = catalog(str(self.root), str(art))
        self.assertEqual(result['modules'], [])
        self.assertIn('coverSymbol must be an object', result['diagnostics'][0]['message'])

    def test_icon_bytes_have_an_aggregate_budget(self):
        from unittest.mock import patch
        from plutonium_agent_toolkit.dev import workspace_catalog as wc
        declaration = json.loads((self.root/'modules/example/module.json').read_text())
        self.write('modules/second/module.json', dict(declaration, id='second'))
        artworks = []
        for mid, token in [('example','a'), ('second','b')]:
            url = 'local-media/' + token*64 + '.webp'
            file = self.root / url
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(b'xx')
            artworks.append({'declarationId':mid, 'artwork':[{'url':url,'binding':{'role':'bound HUD icon'}}]})
        art = self.write('art.json', {'modules':artworks})
        with patch.object(wc, 'MAX_ICON_BYTES', 3):
            result = catalog(str(self.root), str(art))
        self.assertEqual(len(result['modules']), 1)
        self.assertIn('aggregate budget', result['diagnostics'][0]['message'])

    def test_shared_icon_is_read_once_per_catalog(self):
        from unittest.mock import patch
        from plutonium_agent_toolkit.dev import workspace_catalog as wc
        declaration = json.loads((self.root/'modules/example/module.json').read_text())
        self.write('modules/second/module.json', dict(declaration, id='second'))
        url = 'local-media/' + 'a'*64 + '.webp'
        file = self.root / url
        file.parent.mkdir()
        file.write_bytes(b'xx')
        art = self.write('art.json', {'modules':[{'declarationId':mid,'artwork':[{'url':url,'binding':{'role':'shared HUD icon'}}]} for mid in ['example','second']]})
        with patch.object(wc, 'MAX_ICON_BYTES', 2), patch.object(wc.hashlib, 'sha256', wraps=wc.hashlib.sha256) as hashed:
            result = catalog(str(self.root), str(art))
        self.assertEqual(len(result['modules']), 2)
        self.assertEqual(hashed.call_count, 3)  # Two declarations, one shared image.
        self.assertEqual(result['diagnostics'], [])

    def test_declaration_hash_and_validation_use_the_same_snapshot(self):
        import hashlib
        from unittest.mock import patch
        from plutonium_agent_toolkit.dev import workspace_catalog as wc
        file = self.root/'modules/example/module.json'
        original = file.read_bytes()
        validate = wc.validate_declaration_metadata
        def replace_after_validation(data):
            result = validate(data)
            file.write_text(json.dumps(dict(data, id='replaced')))
            return result
        with patch.object(wc, 'validate_declaration_metadata', side_effect=replace_after_validation):
            row = catalog(str(self.root))['modules'][0]
        self.assertEqual(row['id'], 'example')
        self.assertEqual(row['declaration_sha256'], hashlib.sha256(original).hexdigest())

    def test_build_bound_is_checked_before_projecting_the_next_row(self):
        from unittest.mock import patch
        from plutonium_agent_toolkit.dev import workspace_catalog as wc
        self.write('registry/module-recipes.json', {'recipes':[{'id':'example','builds':[{'id':str(i)} for i in range(128)]}]})
        self.write('registry/t6-modules.json', {'modules':[{'id':'example','build_revisions':[{'id':str(i)} for i in range(129)]}]})
        with patch.object(wc, 'project_record', wraps=wc.project_record) as project:
            result = catalog(str(self.root))
        self.assertEqual(project.call_count, 256)
        self.assertEqual(result['modules'], [])
        self.assertIn('256 build records', result['diagnostics'][0]['message'])

    def test_non_object_link_loads_is_a_foundation_diagnostic(self):
        self.write('foundations/bad.json', {'id':'base','profile_prefix':'stock','maps':{'zm_factory':{}}, 'link_loads':[]})
        result = catalog(str(self.root))
        self.assertEqual(result['foundations'], [])
        self.assertIn('link_loads must be an object', result['diagnostics'][0]['message'])

    def test_optional_registry_symlinks_are_rejected_with_diagnostics(self):
        target = self.write('target.json', {'modules':[]})
        directory = self.root/'registry'
        directory.mkdir()
        link = directory/'t6-modules.json'
        for destination in (target, self.root/'missing.json'):
            with self.subTest(destination=destination.name):
                try:
                    link.symlink_to(destination)
                except OSError as exc:
                    self.skipTest(str(exc))
                result = catalog(str(self.root))
                self.assertEqual(len(result['modules']), 1)
                self.assertIn('link', result['diagnostics'][0]['message'])
                link.unlink()

    def test_foundation_map_count_is_bounded_before_projection(self):
        self.write('foundations/large.json', {'id':'base','profile_prefix':'stock','maps':{f'zm_{i}':{} for i in range(65)}})
        result = catalog(str(self.root))
        self.assertEqual(result['foundations'], [])
        self.assertTrue(result['truncated'])
        self.assertIn('map count bound', result['diagnostics'][0]['message'])

    def test_total_foundation_rows_are_bounded(self):
        for i in range(5):
            self.write(f'foundations/base{i}.json', {'id':f'base{i}','profile_prefix':'stock','maps':{f'zm_{j}':{} for j in range(64)}})
        result = catalog(str(self.root))
        self.assertEqual(len(result['foundations']), 256)
        self.assertTrue(result['truncated'])
        self.assertIn('foundation row bound', result['diagnostics'][0]['message'])

    def test_unhashable_registry_ids_are_ignored(self):
        self.write('registry/t6-modules.json', {'modules':[{'id':[]}, {'id':{}}, {'id':'example','weapon_class':'Pistols'}]})
        result = catalog(str(self.root))
        self.assertEqual(result['modules'][0]['weapon_class'], 'Pistols')
        self.assertEqual(result['diagnostics'], [])

    def test_deep_json_returns_a_structured_failure_or_diagnostic(self):
        from plutonium_agent_toolkit.dev.workspace_catalog import read_object
        file = self.root/'deep.json'
        file.write_text('{"nested":' + '['*20000 + '0' + ']'*20000 + '}')
        with self.assertRaises(Failure) as raised:
            read_object(file)
        self.assertEqual(raised.exception.code, 'input_invalid')
        self.write('foundations/base.json', {'id':'base','profile_prefix':'stock','private_descriptor':'../deep.json'})
        result = catalog(str(self.root))
        self.assertIn('not readable JSON', result['diagnostics'][0]['message'])

    def test_directory_enumeration_stops_before_materializing_unbounded_entries(self):
        import contextlib
        from types import SimpleNamespace
        from unittest.mock import patch
        from plutonium_agent_toolkit.dev import workspace_catalog as wc
        count = 0
        @contextlib.contextmanager
        def scan(_):
            def entries():
                nonlocal count
                for i in range(10000):
                    count += 1
                    yield SimpleNamespace(name=f'entry{i}.json')
            yield entries()
        for limit in (64, wc.MAX_MODULES):
            with self.subTest(limit=limit), patch.object(wc.os, 'scandir', side_effect=scan):
                count = 0
                with self.assertRaises(Failure) as raised:
                    wc.directory_entries(self.root, limit)
                self.assertEqual(raised.exception.code, 'input_limit')
                self.assertEqual(count, limit + 1)

    def test_foundation_ids_must_be_strings_before_emission(self):
        file = self.root/'foundations/bad.json'
        file.parent.mkdir()
        for field in ('id', 'profile_prefix'):
            data = {'id':'base','profile_prefix':'stock','maps':{'zm_factory':{}},'link_loads':{'zm_factory':[]}}
            data[field] = float('nan')
            file.write_text(json.dumps(data))
            code, reply = invoke(['workspace','catalog',str(self.root),'--json'])
            self.assertEqual(code, 0, reply)
            self.assertEqual(reply['result']['foundations'], [])
            self.assertIn('must be non-empty strings', reply['result']['diagnostics'][0]['message'])

    def test_catalog_output_escapes_lone_surrogates_in_records_and_provides(self):
        declaration = json.loads((self.root/'modules/example/module.json').read_text())
        self.write('modules/example/module.json', dict(declaration, provides={'soundbanks':['bank\ud800']}))
        self.write('registry/t6-modules.json', {'modules':[{'id':'example','weapon_class':'class\ud801','build_revisions':[{'id':'build\ud802','scope':'scope\ud803'}]}]})
        code, reply = invoke(['workspace','catalog',str(self.root),'--json'])
        self.assertEqual(code, 0, reply)
        result = reply['result']
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        module = result['modules'][0]
        self.assertEqual(module['provides']['soundbanks'], ['bank\\ud800'])
        self.assertEqual(module['weapon_class'], 'class\\ud801')
        self.assertEqual(module['build_records'][0]['id'], 'build\\ud802')
        self.assertEqual(module['build_records'][0]['scope'], 'scope\\ud803')

    def test_empty_load_list_is_staged_but_missing_load_data_is_not(self):
        self.write('foundations/base.json', {'id':'base','profile_prefix':'stock','maps':{'zm_factory':{},'zm_moon':{}},'link_loads':{'zm_factory':[]}})
        rows = catalog(str(self.root))['foundations']
        self.assertTrue(next(row for row in rows if row['map']=='zm_factory')['staged'])
        self.assertFalse(next(row for row in rows if row['map']=='zm_moon')['staged'])

    def test_catalog_applies_module_directory_entry_limit(self):
        from unittest.mock import patch
        from plutonium_agent_toolkit.dev import workspace_catalog as wc
        (self.root/'modules/second').mkdir()
        with patch.object(wc, 'MAX_MODULES', 1), self.assertRaises(Failure) as raised:
            catalog(str(self.root))
        self.assertEqual(raised.exception.code, 'input_limit')

    def test_catalog_reports_excess_foundation_directory_entries(self):
        for i in range(65):
            self.write(f'foundations/base{i}.json', {'id':str(i),'profile_prefix':'stock','maps':{}})
        result = catalog(str(self.root))
        self.assertTrue(result['truncated'])
        self.assertEqual(result['foundations'], [])
        self.assertIn('64 entries', result['diagnostics'][0]['message'])
