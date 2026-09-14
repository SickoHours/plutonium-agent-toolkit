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
