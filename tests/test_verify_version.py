"""``module verify-declaration``: the ``/version`` row, and the folder fingerprint behind it.

A fix that lands must be visible. These are the executable half of docs/MODULES.md, "What a
checker can verify, kind by kind", for one promise: that a module whose authored bytes moved
since its newest evidence row also moved its version. Every fixture is a synthetic module in a
git repository this test creates inside its own temporary directory; nothing here reads the
toolkit's own repository, a real bank or a game.
"""
import json
import os
import subprocess
from unittest import mock

from plutonium_agent_toolkit.dev.verify import folder_fingerprint
from tests.test_module_verify import ModuleVerifyFixture

SHA = "a" * 64
SCOPE = {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit"}
BUILT = {"type": "built-alone", "scope": SCOPE, "at": "2026-09-11", "offline_verified": True,
         "package_sha256": SHA, "receipt": {"path": "build/build.json", "sha256": "1" * 64}}


class VersionFixture(ModuleVerifyFixture):
    """A module inside a repository of this test's own making, with a fixed author and no read of
    the machine's git configuration, so the commits are the same on every host."""

    def setUp(self):
        super().setUp()
        # Discovery stops above the temporary directory: a module outside a repository must read
        # as one here even when the temporary directory itself sits inside somebody's checkout.
        ceiling = mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.root.parent)})
        ceiling.start()
        self.addCleanup(ceiling.stop)
        self.git_env = dict(os.environ, HOME=str(self.root),
                            GIT_CONFIG_GLOBAL=str(self.root / "gitconfig"), GIT_CONFIG_SYSTEM=os.devnull,
                            GIT_AUTHOR_NAME="Toolkit Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                            GIT_COMMITTER_NAME="Toolkit Test", GIT_COMMITTER_EMAIL="test@example.invalid",
                            GIT_AUTHOR_DATE="2026-09-11T10:00:00+00:00",
                            GIT_COMMITTER_DATE="2026-09-11T10:00:00+00:00")

    def git(self, *args):
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, env=self.git_env)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        return done.stdout.decode("utf-8", "replace")

    def ledger(self, directory, rows=(BUILT,)):
        (directory / "evidence.json").write_text(json.dumps(
            {"schema": 1, "subject": {"id": directory.name}, "rows": list(rows)}, indent=2))
        return directory

    def committed(self, mid="alpha", assets=None, **overrides):
        """A module with a source tree and a ledger, all of it in one commit."""
        directory = self.module_with_assets(mid, assets) if assets else self.module(mid, **overrides)
        (directory / "src").mkdir(exist_ok=True)
        (directory / "src" / "helper.gsc").write_text("helper()\n{\n}\n")
        self.ledger(directory)
        self.git("init", "-q")
        self.git("add", "--", "modules")
        self.git("commit", "-qm", "the package this evidence row names")
        return directory

    def reference(self, mid="alpha"):
        """The short commit the route measures from: the one that first added the package hash."""
        log = self.git("log", "--format=%H", "--reverse", "-S", SHA, "--", f"modules/{mid}/evidence.json")
        return log.split()[0][:8]


class VersionRowTests(VersionFixture):
    def test_a_module_with_no_ledger_is_not_counted(self):
        row = self.one(self.verify(self.module("alpha")), "/version", "not_counted")
        self.assertEqual((row["declared"], row["observed"], row["note"]), (["0.1.0"], [], "no ledger"))

    def test_bytes_unchanged_since_the_evidence_row_agree(self):
        directory = self.committed()
        row = self.one(self.verify(directory), "/version", "agrees")
        self.assertEqual((row["declared"], row["observed"]), (["0.1.0"], ["0.1.0"]))
        self.assertIn(self.reference(), row["note"])

    def test_a_source_edit_with_no_bump_is_declared_not_observed_strict_fails_and_propose_bumps_the_patch(self):
        directory = self.committed()
        (directory / "scripts" / "alpha.gsc").write_text("main()\n{\n    level thread alpha();\n}\n\nalpha()\n{\n    wait 2;\n}\n")
        self.git("commit", "-qam", "the fix that landed")
        short = self.reference()
        row = self.one(self.verify(directory), "/version", "declared_not_observed")
        self.assertEqual(row["observed"], [f"0.1.0 at {short}"])
        self.assertEqual(row["note"], f"the folder's bytes changed since the newest evidence row ({SHA[:8]}, "
                                      f"commit {short}) and version did not move: bump it")
        self.one(self.verify(directory, "--strict", expect=1), "/version", "declared_not_observed")
        self.assertEqual(self.verify(directory, "--propose")["proposal"]["version"], "0.1.1")

    def test_a_version_that_moved_agrees_on_the_same_edit(self):
        directory = self.committed()
        (directory / "scripts" / "alpha.gsc").write_text("main()\n{\n    wait 2;\n}\n")
        self.redeclare(directory, "alpha", version="0.1.1")
        row = self.one(self.verify(directory), "/version", "agrees")
        self.assertEqual((row["declared"], row["observed"]), (["0.1.1"], [f"0.1.0 at {self.reference()}"]))
        self.assertEqual(row["note"], f"version moved since {self.reference()}")

    def test_a_version_that_is_not_semantic_is_reported_and_never_bumped_by_machine(self):
        directory = self.committed("alpha", version="beta")
        (directory / "scripts" / "alpha.gsc").write_text("main()\n{\n    wait 2;\n}\n")
        result = self.verify(directory, "--propose")
        self.one(result, "/version", "declared_not_observed")
        self.assertNotIn("version", result["proposal"])
        notes = [n for n in result["proposal_notes"] if n.startswith("version: 'beta' is not MAJOR.MINOR.PATCH")]
        self.assertEqual(len(notes), 1, result["proposal_notes"])

    def test_a_module_outside_a_repository_is_not_counted_with_the_reason(self):
        row = self.one(self.verify(self.ledger(self.module("alpha"))), "/version", "not_counted")
        self.assertEqual(row["note"], "the module directory is not inside a git repository")


class FingerprintTests(VersionFixture):
    def test_build_outputs_donor_payloads_and_prose_are_not_the_modules_authored_bytes(self):
        directory = self.committed()
        for name in ("prepared/mod.ff", "docs/NOTES.md", "README.md",
                     "build-inputs.json", "inputs.json"):
            (directory / name).parent.mkdir(parents=True, exist_ok=True)
            (directory / name).write_text("bytes that are not this module's source\n")
        self.one(self.verify(directory), "/version", "agrees")
        (directory / "src" / "helper.gsc").write_text("helper()\n{\n    wait 1;\n}\n")
        self.one(self.verify(directory), "/version", "declared_not_observed")

    def test_a_source_a_recipe_row_names_is_an_authored_byte_wherever_it_lives(self):
        rows = [{"source": "assets/tree.atr", "target": "animtrees/zm_transit_basic.atr", "type": "rawfile"}]
        directory = self.committed("alpha", assets=rows)
        self.one(self.verify(directory), "/version", "agrees")
        (directory / "assets" / "tree.atr").write_bytes(b"BYTES assets/tree.atr, corrected\n")
        self.one(self.verify(directory), "/version", "declared_not_observed")

    def test_a_file_under_assets_that_no_recipe_row_names_is_not_one(self):
        directory = self.committed()
        (directory / "assets").mkdir(exist_ok=True)
        (directory / "assets" / "donor_dump.gdt").write_text("a donor payload no recipe row compiles\n")
        self.one(self.verify(directory), "/version", "agrees")

    def test_the_fingerprint_is_the_same_on_two_reads_of_an_unchanged_folder(self):
        directory = self.committed()
        first, second = folder_fingerprint(directory), folder_fingerprint(directory)
        self.assertEqual(first, second)
        # module.json, the recipe it names, the script that recipe compiles, and the src/ tree.
        self.assertEqual(first["files"], 4)
        self.assertRegex(first["sha256"], r"^[0-9a-f]{64}\Z")
