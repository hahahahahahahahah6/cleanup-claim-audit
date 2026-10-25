"""Tests for cleanup-claim-audit (run with PYTHONPATH=src)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cleanup_claim_audit.audit import (  # noqa: E402
    CLEANUP_PHRASES, NOCLEANUP_PHRASES, audit, collect_evidence,
    extract_claims)
from cleanup_claim_audit.__main__ import main  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MARKER = "CLEANUP_CLAIM_AUDIT_MARKER_DO_NOT_LEAK"


def make_project(readme=None, files=None, docs=None):
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
    for rel, text in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel, text in (docs or {}).items():
        path = root / "docs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def run_cli(root, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main([str(root)] + list(args))
    return code, buf.getvalue()


class ClaimTests(unittest.TestCase):
    def claims_for(self, readme, **kw):
        return extract_claims(make_project(readme=readme, **kw), ())

    def test_all_cleanup_phrases(self):
        for phrase in CLEANUP_PHRASES:
            with self.subTest(phrase=phrase):
                found = self.claims_for("Tool. It %s every run." % phrase)
                self.assertIn("cleanup", found)
                self.assertIn(phrase, found["cleanup"])

    def test_all_nocleanup_phrases(self):
        for phrase in NOCLEANUP_PHRASES:
            with self.subTest(phrase=phrase):
                found = self.claims_for("Tool. It %s, by design." % phrase)
                self.assertIn("nocleanup", found)
                self.assertIn(phrase, found["nocleanup"])

    def test_never_cleans_single_family(self):
        found = self.claims_for("It never cleans up temporary files.")
        self.assertEqual(set(found), {"nocleanup"})

    def test_does_not_clean_single_family(self):
        found = self.claims_for("It does not clean up temporary files.")
        self.assertEqual(set(found), {"nocleanup"})

    def test_does_not_remove_temp_single_family(self):
        found = self.claims_for("It does not remove temporary files.")
        self.assertEqual(set(found), {"nocleanup"})

    def test_leaves_no_counts_cleanup(self):
        found = self.claims_for("It leaves no temporary files.")
        self.assertEqual(set(found), {"cleanup"})

    def test_no_left_behind_counts_cleanup(self):
        found = self.claims_for("No temporary files left behind.")
        self.assertEqual(set(found), {"cleanup"})

    def test_never_removes_suppressed_no_nocleanup_phrase(self):
        # "never removes temp files" is not a NOCLEANUP phrase; the
        # CLEANUP match is suppressed by the leftover "never".
        found = self.claims_for("It never removes temp files.")
        self.assertEqual(found, {})

    def test_does_not_remove_temp_suppressed(self):
        found = self.claims_for("It does not remove temp files.")
        self.assertEqual(found, {})

    def test_fenced_code_excluded(self):
        found = self.claims_for(
            "Plain intro.\n```\nIt cleans up temporary files.\n```\n")
        self.assertEqual(found, {})

    def test_inline_code_counts(self):
        found = self.claims_for(
            "The tool `cleans up temporary files` after each run.")
        self.assertIn("cleanup", found)

    def test_bare_nouns_no_claim(self):
        found = self.claims_for(
            "Temporary files and cleanup are discussed here at length.")
        self.assertEqual(found, {})

    def test_bare_temp_files_no_claim(self):
        found = self.claims_for("It writes temp files to disk.")
        self.assertEqual(found, {})

    def test_docs_subdir_counts(self):
        found = self.claims_for(
            "Intro.", docs={"guide.md": "It cleans up temporary files."})
        self.assertIn("cleanup", found)

    def test_docs_fenced_excluded(self):
        found = self.claims_for(
            "Intro.",
            docs={"guide.md": "```\nIt cleans up temporary files.\n```\n"})
        self.assertEqual(found, {})

    def test_ignore_glob(self):
        root = make_project(
            readme="Intro.",
            docs={"guide.md": "It cleans up temporary files."})
        self.assertEqual(extract_claims(root, ("docs/*",)), {})

    def test_case_and_hyphen_normalised(self):
        found = self.claims_for(
            "It Cleans-Up Temporary Files after every run.")
        self.assertIn("cleanup", found)

    def test_symlink_doc_skipped(self):
        root = make_project()
        target = root / "target.md"
        target.write_text("It cleans up temporary files.", encoding="utf-8")
        os.symlink(target, root / "README.md")
        # README.md is a symlink; root README must be skipped.
        self.assertEqual(extract_claims(root, ()), {})

    def test_no_readme_no_claim(self):
        self.assertEqual(extract_claims(make_project(), ()), {})


class EvidenceTests(unittest.TestCase):
    def evidence_for(self, source):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "main.py"
        path.write_text(source, encoding="utf-8")
        return collect_evidence(path, "main.py")

    def test_os_unlink(self):
        self.assertTrue(self.evidence_for("import os\nos.unlink(p)\n"))

    def test_path_unlink(self):
        self.assertTrue(self.evidence_for("p.unlink()\n"))

    def test_os_remove(self):
        self.assertTrue(self.evidence_for("import os\nos.remove(p)\n"))

    def test_shutil_rmtree(self):
        self.assertTrue(self.evidence_for(
            "import shutil\nshutil.rmtree(d)\n"))

    def test_os_removedirs(self):
        self.assertTrue(self.evidence_for("import os\nos.removedirs(d)\n"))

    def test_tempdir_attr(self):
        self.assertTrue(self.evidence_for(
            "import tempfile\ntempfile.TemporaryDirectory()\n"))

    def test_tempfile_attr(self):
        self.assertTrue(self.evidence_for(
            "import tempfile\ntempfile.TemporaryFile()\n"))

    def test_atexit_register_attr(self):
        self.assertTrue(self.evidence_for(
            "import atexit\natexit.register(f)\n"))

    def test_bare_tempdir_from_import(self):
        self.assertTrue(self.evidence_for(
            "from tempfile import TemporaryDirectory\nTemporaryDirectory()\n"))

    def test_bare_tempfile_from_import(self):
        self.assertTrue(self.evidence_for(
            "from tempfile import TemporaryFile\nTemporaryFile()\n"))

    def test_bare_register_from_import(self):
        self.assertTrue(self.evidence_for(
            "from atexit import register\nregister(f)\n"))

    def test_aliased_tempdir_from_import(self):
        self.assertTrue(self.evidence_for(
            "from tempfile import TemporaryDirectory as TD\nTD()\n"))

    def test_named_temp_default(self):
        self.assertTrue(self.evidence_for(
            "import tempfile\ntempfile.NamedTemporaryFile()\n"))

    def test_named_temp_delete_true(self):
        self.assertTrue(self.evidence_for(
            "import tempfile\ntempfile.NamedTemporaryFile(delete=True)\n"))

    def test_named_temp_delete_false_not_evidence(self):
        self.assertEqual(self.evidence_for(
            "import tempfile\ntempfile.NamedTemporaryFile(delete=False)\n"), [])

    def test_named_temp_delete_variable_not_evidence(self):
        self.assertEqual(self.evidence_for(
            "import tempfile\ntempfile.NamedTemporaryFile(delete=flag)\n"), [])

    def test_mkstemp_not_evidence(self):
        self.assertEqual(self.evidence_for(
            "import tempfile\ntempfile.mkstemp()\n"), [])

    def test_mkdtemp_not_evidence(self):
        self.assertEqual(self.evidence_for(
            "import tempfile\ntempfile.mkdtemp()\n"), [])

    def test_bare_import_not_evidence(self):
        self.assertEqual(self.evidence_for(
            "import tempfile\nimport os\nimport shutil\nimport atexit\n"), [])

    def test_bare_name_without_import_not_evidence(self):
        self.assertEqual(self.evidence_for("TemporaryDirectory()\n"), [])

    def test_shadowed_bare_name_not_evidence(self):
        self.assertEqual(self.evidence_for(
            "from tempfile import TemporaryDirectory\n"
            "def TemporaryDirectory():\n    pass\nTemporaryDirectory()\n"), [])

    def test_comment_not_evidence(self):
        self.assertEqual(self.evidence_for("# os.unlink(p)\n"), [])

    def test_string_not_evidence(self):
        self.assertEqual(self.evidence_for('x = "os.unlink(p)"\n'), [])

    def test_syntax_error_no_evidence(self):
        self.assertEqual(self.evidence_for("def broken(:\n"), [])

    def test_open_write_not_evidence(self):
        self.assertEqual(self.evidence_for(
            'open("/tmp/x", "w").write("hi")\n'), [])


class AuditTests(unittest.TestCase):
    def test_good_cleanup_pass(self):
        result = audit(FIXTURES / "good" / "cleanup")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["verified_claims"]), 1)
        self.assertEqual(result["verified_claims"][0]["family"], "cleanup")

    def test_good_nocleanup_pass(self):
        result = audit(FIXTURES / "good" / "nocleanup")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verified_claims"][0]["family"], "nocleanup")

    def test_bad_cleanup_exact_high(self):
        result = audit(FIXTURES / "bad" / "cleanup")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["rule"],
                         "documented-cleanup-claim-false")
        self.assertEqual(result["findings"][0]["severity"], "HIGH")

    def test_bad_nocleanup_exact_high(self):
        result = audit(FIXTURES / "bad" / "nocleanup")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["rule"],
                         "documented-no-cleanup-claim-false")
        self.assertEqual(result["findings"][0]["severity"], "HIGH")

    def test_testonly_cleanup_medium(self):
        result = audit(FIXTURES / "testonly" / "cleanup")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["findings"][0]["rule"],
                         "documented-cleanup-claim-false-test-only")
        self.assertEqual(result["findings"][0]["severity"], "MEDIUM")

    def test_testonly_nocleanup_medium(self):
        result = audit(FIXTURES / "testonly" / "nocleanup")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["findings"][0]["rule"],
                         "documented-no-cleanup-claim-false-test-only")
        self.assertEqual(result["findings"][0]["severity"], "MEDIUM")

    def test_no_source_cleanup_high(self):
        root = make_project(
            readme="It cleans up temporary files after every run.")
        result = audit(root)
        self.assertEqual(result["findings"][0]["severity"], "HIGH")
        self.assertEqual(result["findings"][0]["evidence"], ["no-source"])

    def test_no_source_nocleanup_high(self):
        root = make_project(
            readme="It does not clean up temporary files.")
        result = audit(root)
        self.assertEqual(result["findings"][0]["rule"],
                         "documented-no-cleanup-claim-false")
        self.assertEqual(result["findings"][0]["evidence"], ["no-source"])

    def test_no_claim_pass(self):
        root = make_project(readme="A plain tool.", files={
            "main.py": "import os\nos.unlink(p)\n"})
        self.assertEqual(audit(root)["status"], "PASS")

    def test_mixed_claims_cleanup_fails_nocleanup_verified(self):
        root = make_project(
            readme="It cleans up temporary files. It does not clean up "
            "temporary files.",
            files={"main.py": "import tempfile\ntempfile.mkstemp()\n"})
        result = audit(root)
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["rule"],
                         "documented-cleanup-claim-false")
        self.assertEqual([c["family"] for c in result["verified_claims"]],
                         ["nocleanup"])

    def test_test_file_at_root_counts_as_test(self):
        root = make_project(
            readme="It cleans up temporary files.",
            files={"test_main.py": "import shutil\nshutil.rmtree(d)\n"})
        result = audit(root)
        self.assertEqual(result["findings"][0]["severity"], "MEDIUM")

    def test_examples_dir_excluded(self):
        root = make_project(
            readme="It cleans up temporary files.",
            files={"examples/demo.py": "import shutil\nshutil.rmtree(d)\n"})
        result = audit(root)
        self.assertEqual(result["findings"][0]["evidence"], ["no-source"])

    def test_marker_never_leaks(self):
        code, out = run_cli(FIXTURES / "bad" / "cleanup", "--json")
        self.assertEqual(code, 2)
        self.assertNotIn(MARKER, out)

    def test_self_audit_pass(self):
        root = Path(__file__).resolve().parents[1]
        result = audit(root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["claims"], {})


class CliTests(unittest.TestCase):
    def test_good_exit_0(self):
        code, out = run_cli(FIXTURES / "good" / "cleanup")
        self.assertEqual(code, 0)
        self.assertIn("status: PASS", out)

    def test_bad_exit_2(self):
        code, out = run_cli(FIXTURES / "bad" / "cleanup")
        self.assertEqual(code, 2)
        self.assertIn("documented-cleanup-claim-false", out)

    def test_bad_path_exit_1(self):
        code, _ = run_cli(Path("/nonexistent-cleanup-audit-root"))
        self.assertEqual(code, 1)

    def test_json_valid(self):
        code, out = run_cli(FIXTURES / "bad" / "nocleanup", "--json")
        self.assertEqual(code, 2)
        parsed = json.loads(out)
        self.assertEqual(parsed["status"], "FAIL")
        self.assertEqual(parsed["findings"][0]["family"], "nocleanup")

    def test_fail_on_high_testonly_exit_0(self):
        code, _ = run_cli(FIXTURES / "testonly" / "cleanup",
                          "--fail-on", "HIGH")
        self.assertEqual(code, 0)

    def test_fail_on_high_bad_exit_2(self):
        code, _ = run_cli(FIXTURES / "bad" / "cleanup",
                          "--fail-on", "HIGH")
        self.assertEqual(code, 2)

    def test_verbose_prints_claims(self):
        code, out = run_cli(FIXTURES / "good" / "cleanup", "--verbose")
        self.assertEqual(code, 0)
        self.assertIn("claim:", out)

    def test_version(self):
        with self.assertRaises(SystemExit) as caught:
            main(["--version"])
        self.assertEqual(caught.exception.code, 0)

    def test_bad_flag_exit_1(self):
        with self.assertRaises(SystemExit) as caught:
            main([str(FIXTURES / "good" / "cleanup"), "--bogus"])
        self.assertEqual(caught.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
