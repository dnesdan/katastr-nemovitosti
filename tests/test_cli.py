"""Actual process-level workflows; network adapters are isolated at their boundary."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL = Path(os.environ.get("KATASTR_SKILL_ROOT", Path(__file__).resolve().parents[1] / "skills/katastr-nemovitosti")).resolve()
SCRIPT = SKILL / "scripts/katastr.py"
sys.path.insert(0, str(SKILL / "scripts"))
import katastr


FAKE_NETWORK_BOOTSTRAP = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import katastr, sources, http_client
root = Path(os.environ["KATASTR_TEST_DIR"])
class FakeClient:
    def __init__(self, cache_dir=None):
        self.cache_dir = Path(cache_dir) if cache_dir else root / "cache"
http_client.HttpClient = FakeClient
def answer(client, *args, **kwargs):
    (root / "adapter-called").write_text("yes")
    return {"fixture": True, "args": list(args), "kwargs": kwargs}
for name in ("ruian", "ruian_building", "parcel", "wms"):
    setattr(sources, name, answer)
def map_answer(client, url, layer, bbox, out, **kwargs):
    (root / "adapter-called").write_text("yes")
    out = Path(out); sidecar = Path(str(out)+".json")
    if out.exists() or sidecar.exists():
        raise ValueError("Adapter refuses existing output")
    if os.environ.get("KATASTR_TEST_MAP_FAIL"):
        raise RuntimeError("Simulated unavailable source")
    out.write_bytes(b"SYNTHETIC MAP BYTES")
    result = {"fixture": True, "file": str(out), "sidecar": str(sidecar), "bbox": bbox, "kwargs": kwargs}
    sidecar.write_text(json.dumps(result))
    return result
sources.wms_map = map_answer
raise SystemExit(katastr.main(sys.argv[2:]))
'''


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="katastr-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = os.environ.copy()
        self.env["PYTHONUTF8"] = "1"
        self.env["KATASTR_TEST_DIR"] = str(self.root)

    def cli(self, *args, expected=0, network=False, extra_env=None):
        command = [sys.executable, str(SCRIPT)]
        if network:
            command = [sys.executable, "-c", FAKE_NETWORK_BOOTSTRAP, str(SKILL / "scripts")]
        result = subprocess.run(command + [str(arg) for arg in args], cwd=self.root,
                                env={**self.env, **(extra_env or {})}, capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def init_case(self, name="case.json", place="Uherský Brod"):
        path = self.root / name
        self.cli("init", "--title", "Modelový průchod", "--place", place, "--out", path)
        return path

    def document(self):
        path = self.root / "original.txt"
        path.write_text("List vlastnictví: 42\nParcela: st. 12/3\nPodíl: 1/8\nSOUKROMY_DOKUMENT_TEST", encoding="utf-8")
        return path

    def map_args(self, output, *extra):
        return ("fetch", "map", "--layer", "test", "--bbox", "16.5,49.1,16.6,49.2", "--out", output, *extra)

    def test_init_inspect_add_validate_report_workflow_preserves_originals(self):
        case = self.init_case()
        doc = self.document()
        original_doc, original_case = doc.read_bytes(), case.read_bytes()
        inspected = self.root / "inspection.json"
        self.cli("inspect", doc, "--out", inspected)
        self.assertTrue(json.loads(inspected.read_text())["requires_review"])
        expanded = self.root / "case-with-document.json"
        result = self.cli("add-document", case, doc, "--id", "doc-test", "--title", "Modelový podklad", "--kind", "lv", "--out", expanded)
        self.assertEqual(result.stdout, "")
        self.assertIn(str(expanded), result.stderr)
        data = json.loads(expanded.read_text())
        self.assertEqual(data["documents"][0]["id"], "doc-test")
        self.assertFalse(data["documents"][0]["public"])
        self.assertEqual(data["findings"][0]["status"], "unverified")
        self.assertEqual(data["documents"][0]["register_state_at"], "")
        self.assertIn("OK:", self.cli("validate", expanded).stdout)
        for kind, extension in (("html", "html"), ("markdown", "md"), ("geojson", "geojson")):
            with self.subTest(format=kind):
                output = self.root / ("report." + extension)
                self.cli("report", expanded, "--format", kind, "--out", output)
                self.assertGreater(output.stat().st_size, 30)
                if kind == "geojson":
                    self.assertEqual(json.loads(output.read_text())["type"], "FeatureCollection")
        self.assertEqual(doc.read_bytes(), original_doc)
        self.assertEqual(case.read_bytes(), original_case)

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "Optional pypdf")
    def test_real_pdf_with_attachment_can_be_imported(self):
        fixture = Path(__file__).parent / "fixtures/documents/synthetic-lv-attachments.pdf"
        self.assertTrue(fixture.is_file())
        result = self.cli("inspect", fixture)
        inspection = json.loads(result.stdout)
        self.assertEqual(inspection["completeness"], "partial")
        self.assertEqual(inspection["attachments"][0]["type"], "xml")
        self.assertNotIn("path", inspection["attachments"][0])

    def test_public_report_requires_review_and_strips_private_documents(self):
        case = self.init_case()
        doc = self.document()
        extended = self.root / "extended.json"
        self.cli("add-document", case, doc, "--id", "d", "--title", "TAJNY_NAZEV", "--out", extended)
        public = self.root / "public.html"
        self.cli("report", extended, "--public", "--out", public, expected=2)
        self.assertFalse(public.exists())
        data = json.loads(extended.read_text())
        data["case"]["sharing"] = "public-reviewed"
        extended.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = extended.read_bytes()
        self.cli("report", extended, "--public", "--out", public)
        self.assertNotIn("TAJNY_NAZEV", public.read_text())
        self.assertNotIn("SOUKROMY_DOKUMENT_TEST", public.read_text())
        self.assertIn("Přehled ke sdílení", public.read_text())
        private = self.root / "private.html"
        self.cli("report", extended, "--out", private)
        self.assertIn("TAJNY_NAZEV", private.read_text())
        self.assertIn("Soukromý pracovní přehled", private.read_text())
        self.assertEqual(extended.read_bytes(), before)

    def test_existing_output_requires_force(self):
        case = self.init_case()
        before = case.read_bytes()
        self.cli("init", "--title", "Replacement", "--place", "Most", "--out", case, expected=2)
        self.assertEqual(case.read_bytes(), before)
        self.cli("init", "--title", "Replacement", "--place", "Most", "--out", case, "--force")
        self.assertEqual(json.loads(case.read_text())["case"]["locality"], "Most")

    def test_force_never_overwrites_input_document_or_report_source(self):
        case, doc = self.init_case(), self.document()
        for command in (("inspect", doc, "--out", doc, "--force"),
                        ("add-document", case, doc, "--id", "d", "--title", "D", "--out", doc, "--force"),
                        ("report", case, "--out", case, "--force"),
                        ("compare", case, case, "--out", case, "--force")):
            before = {path: path.read_bytes() for path in (case, doc)}
            with self.subTest(command=command[0]):
                self.cli(*command, expected=2)
                self.assertEqual(before, {path: path.read_bytes() for path in (case, doc)})

    def test_symlink_output_does_not_change_target(self):
        target = self.root / "target.txt"
        target.write_text("KEEP")
        link = self.root / "linked.json"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation is unavailable on this OS")
        self.cli("init", "--title", "T", "--place", "P", "--out", link, "--force", expected=2)
        self.assertEqual(target.read_text(), "KEEP")

    def test_outputs_attachments_and_cache_stay_outside_skill(self):
        bad_out = SKILL / "forbidden-case-output.json"
        self.cli("init", "--title", "T", "--place", "P", "--out", bad_out, expected=2)
        self.assertFalse(bad_out.exists())
        self.cli("inspect", self.document(), "--attachments", SKILL / "forbidden-attachments", expected=2)
        self.cli("fetch", "ruian", "Brno", "--cache", SKILL / "forbidden-cache", network=True, expected=2)
        self.assertFalse((self.root / "adapter-called").exists())

    def test_path_with_spaces_and_unicode(self):
        case = self.init_case("případ s mezerami.json")
        self.cli("validate", case)

    def test_plan_and_sources_are_structured_not_findings(self):
        for place in ("Brno", "Uherský Brod", "Most", "Jihlava"):
            with self.subTest(place=place):
                result = self.cli("plan", "--place", place, "--topics", "identity,planning")
                data = json.loads(result.stdout)
                self.assertEqual(data["status"], "planned")
                self.assertFalse(data["identity_confirmed"])
                self.assertEqual(data["place_query"], place)
                self.assertNotIn("findings", data)
                self.assertTrue(data["sources"])
        sources = json.loads(self.cli("sources", "--topic", "water").stdout)
        self.assertTrue(all("water" in item["topics"] for item in sources["sources"]))
        self.cli("plan", "--place", "Brno", "--topics", "nonexistent-topic", expected=2)

    def test_errors_are_actionable_without_traceback(self):
        self.cli("validate", self.root / "missing.json", expected=2)
        malformed = self.root / "bad.json"
        malformed.write_text('{"broken":')
        self.cli("validate", malformed, expected=2)
        self.cli("init", "--title", " ", "--place", "Brno", "--out", self.root / "bad-out.json", expected=2)
        self.assertFalse((self.root / "bad-out.json").exists())

    def test_compare_returns_json_without_mutating_sources(self):
        case = self.init_case()
        newer = self.root / "newer.json"
        data = json.loads(case.read_text())
        data["findings"].append({"id": "new-check", "title": "Prověřit přístup", "topic": "access", "status": "missing", "severity": "medium", "summary": "Chybí podklad", "object_ids": [], "evidence_ids": [], "next_step": "Získat listinu", "public": False})
        newer.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        old, new = case.read_bytes(), newer.read_bytes()
        result = json.loads(self.cli("compare", case, newer).stdout)
        self.assertIn("new-check", result["changes"]["findings"]["added"])
        self.assertEqual((case.read_bytes(), newer.read_bytes()), (old, new))

    def test_fetch_wrapper_parameters_and_stdout_json(self):
        commands = [
            (("fetch", "ruian", "Brno", "--kind", "cadastral", "--limit", "7", "--refresh"), ["Brno"], {"kind": "cadastral", "limit": 7, "refresh": True}),
            (("fetch", "building", "12345"), ["12345"], {"refresh": False}),
            (("fetch", "parcel", "--cadastral", "123456", "--number", "12/3", "--series", "building"), ["123456", "12/3"], {"series": "building", "refresh": False}),
            (("fetch", "wms", "--wms-version", "1.1.1"), ["https://services.cuzk.gov.cz/wms/local-km-wms.asp"], {"version": "1.1.1", "refresh": False}),
        ]
        for arguments, positional, keyword in commands:
            with self.subTest(service=arguments[1]):
                data = json.loads(self.cli(*arguments, network=True).stdout)
                self.assertEqual(data["args"], positional)
                self.assertEqual(data["kwargs"], keyword)

    def test_map_sidecar_stdout_and_force_have_consistent_paths(self):
        output = self.root / "map.png"
        sidecar = Path(str(output) + ".json")
        result = self.cli(*self.map_args(output), network=True)
        data = json.loads(result.stdout)
        self.assertEqual(output.read_bytes(), b"SYNTHETIC MAP BYTES")
        self.assertEqual(json.loads(sidecar.read_text()), data)
        self.assertEqual(data["file"], str(output))
        self.assertEqual(data["sidecar"], str(sidecar))
        self.assertNotIn(".katastr-map-", result.stdout)
        output.write_bytes(b"OLD")
        sidecar.write_text("OLD METADATA")
        self.cli(*self.map_args(output), network=True, expected=2)
        self.assertEqual(output.read_bytes(), b"OLD")
        self.cli(*self.map_args(output, "--force"), network=True)
        self.assertEqual(output.read_bytes(), b"SYNTHETIC MAP BYTES")
        self.assertEqual(json.loads(sidecar.read_text())["file"], str(output))
        self.assertFalse(list(self.root.glob(".katastr-*")))

    def test_map_existing_sidecar_blocks_before_fetch(self):
        output = self.root / "map.png"
        sidecar = Path(str(output) + ".json")
        sidecar.write_text("KEEP")
        self.cli(*self.map_args(output), network=True, expected=2)
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "adapter-called").exists())
        self.assertEqual(sidecar.read_text(), "KEEP")

    def test_map_custom_metadata_and_same_sidecar_alias(self):
        output = self.root / "map.png"
        custom = self.root / "metadata.json"
        self.cli(*self.map_args(output, "--metadata", custom), network=True)
        self.assertEqual(json.loads(custom.read_text())["file"], str(output))
        other = self.root / "other.png"
        alias = Path(str(other) + ".json")
        self.cli(*self.map_args(other, "--metadata", alias), network=True)
        self.assertEqual(json.loads(alias.read_text())["file"], str(other))

    def test_map_metadata_collision_and_bad_bbox_do_not_fetch(self):
        output = self.root / "map.png"
        self.cli(*self.map_args(output, "--metadata", output), network=True, expected=2)
        self.cli("fetch", "map", "--layer", "x", "--bbox", "16,49,nan,50", "--out", output, network=True, expected=2)
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "adapter-called").exists())

    def test_map_fetch_failure_preserves_old_map_and_metadata(self):
        output = self.root / "map.png"
        sidecar = Path(str(output) + ".json")
        output.write_bytes(b"OLD")
        sidecar.write_text("OLD METADATA")
        self.cli(*self.map_args(output, "--force"), network=True, expected=2,
                 extra_env={"KATASTR_TEST_MAP_FAIL": "yes"})
        self.assertEqual(output.read_bytes(), b"OLD")
        self.assertEqual(sidecar.read_text(), "OLD METADATA")

    def test_bundle_restores_previous_files_after_write_failure(self):
        a, b = self.root / "a", self.root / "b"
        a.write_bytes(b"OLD A"); b.write_bytes(b"OLD B")
        write = katastr._write_bytes
        def fail_second(data, path, force=False):
            if path == b:
                raise OSError("simulated disk error")
            write(data, path, force)
        with mock.patch.object(katastr, "_write_bytes", side_effect=fail_second), self.assertRaises(OSError):
            katastr._save_bundle([(a, b"NEW A"), (b, b"NEW B")], force=True)
        self.assertEqual(a.read_bytes(), b"OLD A")
        self.assertEqual(b.read_bytes(), b"OLD B")
        self.assertFalse(list(self.root.glob(".katastr-*")))

    def test_bundle_keeps_recoverable_backup_if_rollback_itself_fails(self):
        original = self.root / "original"
        original.write_bytes(b"ORIGINAL CONTENT")
        replace = katastr.os.replace
        def fail_restore(source, target):
            if Path(source).name.startswith(".katastr-backup-"):
                raise PermissionError("simulated restore failure")
            return replace(source, target)
        with mock.patch.object(katastr, "_write_bytes", side_effect=OSError("simulated write failure")), mock.patch.object(katastr.os, "replace", side_effect=fail_restore), self.assertRaises(RuntimeError):
            katastr._save_bundle([(original, b"NEW CONTENT")], force=True)
        backups = list(self.root.glob(".katastr-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"ORIGINAL CONTENT")

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_private_case_file_permissions(self):
        case = self.init_case()
        self.assertEqual(case.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
