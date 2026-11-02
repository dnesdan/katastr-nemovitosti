"""Synthetic offline regressions: no real owners or private property records."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL = Path(os.environ.get("KATASTR_SKILL_ROOT", Path(__file__).resolve().parents[1] / "skills/katastr-nemovitosti"))
sys.path.insert(0, str(SKILL / "scripts"))
import documents

HAS_PYPDF = importlib.util.find_spec("pypdf") is not None


def make_pdf(path: Path, texts: list[str], attachments: list[tuple[str, bytes]] | None = None,
             password: str | None = None, signature: str | None = None):
    """Minimal PDF fixture in Helvetica; ASCII text is intentional."""
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, ByteStringObject, DecodedStreamObject,
                              DictionaryObject, NameObject, NumberObject, TextStringObject)
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        lines = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in text.splitlines()]
        content = "BT /F1 11 Tf 40 780 Td " + " 0 -16 Td ".join(f"({line}) Tj" for line in lines) + " ET"
        stream = DecodedStreamObject()
        stream.set_data(content.encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    for name, data in attachments or []:
        writer.add_attachment(name, data)
    if signature:
        field = DictionaryObject({NameObject("/FT"): NameObject("/Sig"), NameObject("/T"): TextStringObject("Synthetic signature field")})
        if signature == "filled":
            field[NameObject("/V")] = DictionaryObject({NameObject("/Type"): NameObject("/Sig"),
                NameObject("/ByteRange"): ArrayObject([NumberObject(0), NumberObject(1), NumberObject(2), NumberObject(3)]),
                NameObject("/Contents"): ByteStringObject(b"NOT A REAL SIGNATURE")})
        writer.root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject([writer._add_object(field)])})
    if password:
        writer.encrypt(password)
    writer.write(path)
    return writer


class DocumentTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name: str, data: bytes | str) -> Path:
        path = self.root / name
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def codes(self, result):
        return {warning["code"] for warning in result["warnings"]}


class DocumentTests(DocumentTestBase):
    def test_text_candidates_do_not_turn_parcel_fraction_into_share(self):
        path = self.write("podklad.txt", "List vlastnictví: 42\nKatastrální území: 123456 Modelová obec\nParcela: st. 12/3\nPodíl: 1/8\nV-123-2026-123\nPlatnost výpisu k 02.11.2026 10:30:00\nVyhotoveno 02.11.2026 11:20:00")
        result = documents.inspect_document(path)
        candidates = result["candidates"]
        self.assertEqual(candidates["lv_numbers"][0]["value"], "42")
        self.assertEqual(candidates["parcels"][0]["value"], {"number": "12/3", "series": "building"})
        self.assertEqual(len(candidates["shares"]), 1)
        self.assertEqual(candidates["shares"][0]["value"], {"numerator": 1, "denominator": 8})
        self.assertEqual(candidates["cadastral_areas"][0]["value"]["code"], "123456")
        self.assertNotEqual(candidates["register_state_at"][0]["value"], candidates["issued_at"][0]["value"])
        self.assertTrue(result["requires_review"])
        self.assertIsNone(result["page_count"])
        self.assertEqual(result["completeness"], "unknown")

    def test_unspecified_parcel_series_stays_unspecified(self):
        result = documents.inspect_document(self.write("p.txt", "Parcela: 12/3"))
        self.assertEqual(result["candidates"]["parcels"][0]["value"]["series"], "unspecified")

    def test_zero_denominator_candidate_is_not_valid_fraction(self):
        result = documents.inspect_document(self.write("p.txt", "Podíl: 1/0"))
        self.assertFalse(result["candidates"]["shares"][0]["valid_fraction"])

    def test_xml_inventory_is_not_a_legal_parser(self):
        result = documents.inspect_document(self.write("lv.xml", '<v:Vypis xmlns:v="urn:synthetic-cadastral-test" verze="3.0"><v:cisloLV>42</v:cisloLV></v:Vypis>'))
        self.assertEqual(result["xml"]["schema_status"], "unsupported")
        self.assertEqual(result["xml"]["namespace"], "urn:synthetic-cadastral-test")
        self.assertEqual(result["xml"]["fields"][0]["value"], "42")
        self.assertEqual(result["candidates"], {})
        self.assertIn("xml_schema_unsupported", self.codes(result))

    def test_utf16_xml_is_inspected(self):
        path = self.write("lv.xml", '<?xml version="1.0" encoding="UTF-16"?><vypis><cislo>42</cislo></vypis>'.encode("utf-16"))
        self.assertEqual(documents.inspect_document(path)["xml"]["fields"][0]["value"], "42")

    def test_doctype_rejected_even_with_utf16_encoding(self):
        xml = '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'
        for encoding in ("utf-8", "utf-16", "utf-16-be", "utf-16-le"):
            with self.subTest(encoding=encoding):
                with self.assertRaises(documents.DocumentError) as caught:
                    documents.inspect_document(self.write("unsafe.xml", xml.encode(encoding)))
                self.assertEqual(caught.exception.code, "unsafe_xml")

    def test_xml_does_not_fetch_schema_or_xinclude(self):
        path = self.write("lv.xml", '<r xmlns:xi="http://www.w3.org/2001/XInclude"><xi:include href="https://invalid.example/private"/></r>')
        result = documents.inspect_document(path)
        self.assertEqual(result["xml"]["element_count"], 2)
        self.assertEqual(result["xml"]["fields"], [])

    def test_invalid_and_overdeep_xml_rejected(self):
        for xml, code in (("<a>", "invalid_xml"), ("<a>" * 65 + "</a>" * 65, "xml_limits")):
            with self.subTest(code=code), self.assertRaises(documents.DocumentError) as caught:
                documents.inspect_document(self.write("p.xml", xml))
            self.assertEqual(caught.exception.code, code)

    def test_xml_node_limit(self):
        with mock.patch.object(documents, "MAX_XML_ELEMENTS", 3):
            with self.assertRaises(documents.DocumentError) as caught:
                documents.inspect_document(self.write("p.xml", "<a><b/><c/><d/></a>"))
        self.assertEqual(caught.exception.code, "xml_limits")

    def test_xml_value_truncation_is_visible(self):
        result = documents.inspect_document(self.write("p.xml", "<a><b>" + "x" * 2001 + "</b></a>"))
        self.assertTrue(result["xml"]["values_truncated"])
        self.assertIn("xml_inventory_truncated", self.codes(result))
        self.assertEqual(len(result["xml"]["fields"][0]["value"]), 2000)

    def test_invalid_pdf_header_unsupported_and_empty_inputs(self):
        for name, data, code in (("p.pdf", b"not pdf", "invalid_pdf"), ("p.exe", b"MZ executable", "unsupported_type"), ("p.txt", b"", "empty_document")):
            with self.subTest(code=code), self.assertRaises(documents.DocumentError) as caught:
                documents.inspect_document(self.write(name, data))
            self.assertEqual(caught.exception.code, code)

    def test_file_size_limit_applies_before_parse(self):
        with mock.patch.object(documents, "MAX_FILE_BYTES", 10):
            with self.assertRaises(documents.DocumentError) as caught:
                documents.inspect_document(self.write("p.txt", "x" * 11))
        self.assertEqual(caught.exception.code, "file_too_large")

    def test_optional_pdf_dependency_reports_actionable_error(self):
        path = self.write("p.pdf", b"%PDF-1.7 invalid fixture")
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            with self.assertRaises(documents.DocumentError) as caught:
                documents.inspect_document(path)
        self.assertEqual(caught.exception.code, "dependency_missing")


@unittest.skipUnless(HAS_PYPDF, "Optional pypdf is needed for PDF fixtures")
class PDFTests(DocumentTestBase):
    def pdf(self, texts: list[str], **kwargs) -> Path:
        path = self.root / "synthetic.pdf"
        make_pdf(path, texts, **kwargs)
        return path

    def test_partial_extract_preserves_original_and_hash(self):
        path = self.pdf(["VYPIS Z KATASTRU NEMOVITOSTI\nLV: 42\nCASTECNY VYPIS\nStrana 1 z 1"])
        before = path.read_bytes()
        result = documents.inspect_document(path)
        self.assertEqual(result["completeness"], "partial")
        self.assertIn("partial_extract", self.codes(result))
        self.assertEqual(result["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(), before)

    def test_missing_page_detected(self):
        result = documents.inspect_document(self.pdf(["VYPIS Z KATASTRU\nStrana 1 z 3"]))
        self.assertEqual(result["completeness"], "partial")
        self.assertIn("missing_pages", self.codes(result))

    def test_complete_pagination_does_not_certify_document_completeness(self):
        result = documents.inspect_document(self.pdf(["Strana 1 z 2", "Strana 2 z 2"]))
        self.assertTrue(result["page_sequence_complete"])
        self.assertEqual(result["completeness"], "unknown")

    def test_blank_pdf_is_unread_not_clean(self):
        result = documents.inspect_document(self.pdf([""]))
        self.assertEqual(result["pages"][0]["extraction"], "none")
        self.assertIn("page_without_text", self.codes(result))
        self.assertEqual(result["completeness"], "unknown")

    def test_page_limit(self):
        path = self.pdf(["one", "two"])
        with mock.patch.object(documents, "MAX_PAGES", 1), self.assertRaises(documents.DocumentError) as caught:
            documents.inspect_document(path)
        self.assertEqual(caught.exception.code, "page_limit")

    def test_duplicate_unsafe_attachment_names_are_unique_safe_files(self):
        path = self.pdf(["Synthetic cover"], attachments=[("../../outside.xml", b"<r>first</r>"), ("../../outside.xml", b"<r>second</r>")])
        result = documents.inspect_document(path, self.root / "attachments")
        items = result["attachments"]
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0]["path"], items[1]["path"])
        for item in items:
            self.assertNotIn("..", item["path"])
            self.assertEqual(Path(item["path"]).name, item["path"])
            self.assertTrue((self.root / "attachments" / item["path"]).exists())
        self.assertFalse((self.root / "outside.xml").exists())

    def test_attachments_are_not_written_without_explicit_output_directory(self):
        result = documents.inspect_document(self.pdf(["Synthetic cover"], attachments=[("a.xml", b"<r/>")]))
        self.assertNotIn("path", result["attachments"][0])

    def test_unsafe_xml_attachment_blocked_before_write(self):
        data = b'<!DOCTYPE a [<!ENTITY x "bad">]><a>&x;</a>'
        result = documents.inspect_document(self.pdf(["Cover"], attachments=[("a.xml", data)]), self.root / "out")
        self.assertEqual(result["attachments"][0]["status"], "blocked")
        self.assertIn("unsafe_xml", self.codes(result))
        self.assertFalse((self.root / "out").exists())

    def test_executable_and_html_attachments_not_extracted(self):
        result = documents.inspect_document(self.pdf(["Cover"], attachments=[("a.sh", b"#!/bin/sh\necho bad"), ("a.html", b"<html><script>bad()</script></html>")]), self.root / "out")
        self.assertEqual([x["status"] for x in result["attachments"]], ["blocked", "blocked"])
        self.assertFalse((self.root / "out").exists())

    def test_af_only_attachment_is_inventoried(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, NameObject
        path = self.pdf(["Cover"], attachments=[("linked.xml", b"<r/>")])
        writer = PdfWriter(clone_from=PdfReader(path))
        spec = writer.root_object["/Names"]["/EmbeddedFiles"]["/Names"][1]
        writer.root_object[NameObject("/AF")] = ArrayObject([spec])
        del writer.root_object["/Names"]
        writer.write(path)
        result = documents.inspect_document(path)
        self.assertEqual(len(result["attachments"]), 1)
        self.assertEqual(result["attachments"][0]["name"], "linked.xml")

    def test_nested_name_tree_is_inventoried(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, DictionaryObject, NameObject
        path = self.pdf(["Cover"], attachments=[("nested.xml", b"<r/>")])
        writer = PdfWriter(clone_from=PdfReader(path))
        leaf = writer.root_object["/Names"]["/EmbeddedFiles"]
        node = DictionaryObject({NameObject("/Kids"): ArrayObject([leaf])})
        node = DictionaryObject({NameObject("/Kids"): ArrayObject([writer._add_object(node)])})
        writer.root_object["/Names"][NameObject("/EmbeddedFiles")] = node
        writer.write(path)
        self.assertEqual(len(documents.inspect_document(path)["attachments"]), 1)

    def test_attachment_size_and_count_limits_fail_closed(self):
        path = self.pdf(["Cover"], attachments=[("a.txt", b"123456789"), ("b.txt", b"hi")])
        with mock.patch.object(documents, "MAX_ATTACHMENT_BYTES", 8):
            result = documents.inspect_document(path)
        self.assertEqual(result["attachments"][0]["status"], "blocked")
        self.assertEqual(result["attachments"][1]["status"], "inventoried")
        with mock.patch.object(documents, "MAX_ATTACHMENTS", 1):
            result = documents.inspect_document(path)
        self.assertEqual(len(result["attachments"]), 1)
        self.assertIn("attachment_count_limit", self.codes(result))

    def test_idempotent_extraction_and_symlink_protection(self):
        path = self.pdf(["Cover"], attachments=[("a.xml", b"<r/>")])
        out = self.root / "out"
        first = documents.inspect_document(path, out)
        second = documents.inspect_document(path, out)
        self.assertEqual(first["attachments"][0]["path"], second["attachments"][0]["path"])
        target = out / first["attachments"][0]["path"]
        target.unlink()
        original = self.write("untouched.txt", "ORIGINAL")
        target.symlink_to(original)
        third = documents.inspect_document(path, out)
        self.assertEqual(third["attachments"][0]["error_code"], "unsafe_output_path")
        self.assertEqual(original.read_text(), "ORIGINAL")

    def test_password_required_is_reported_without_attempting_secret_guess(self):
        result = documents.inspect_document(self.pdf(["Secret"], password="synthetic-test-password"))
        self.assertIn("password_required", self.codes(result))
        self.assertEqual(result["pages"], [])
        self.assertIsNone(result["page_count"])

    def test_blank_signature_and_present_signature_are_not_verified(self):
        empty = documents.inspect_document(self.pdf(["Cover"], signature="blank"))
        self.assertEqual(empty["seal_status"], "not_checked")
        present = documents.inspect_document(self.pdf(["Cover"], signature="filled"))
        self.assertEqual(present["seal_status"], "present_unverified")
        self.assertIn("signature_not_verified", self.codes(present))

    def test_ocr_unavailable_gracefully_preserves_text(self):
        path = self.pdf(["Short"])
        with mock.patch.object(documents.shutil, "which", return_value=None):
            result = documents.inspect_document(path, ocr=True)
        self.assertIn("ocr_unavailable", self.codes(result))
        self.assertIn("Short", result["pages"][0]["text"])

    def test_ocr_candidates_require_review_and_keep_native_text(self):
        path = self.pdf([""])
        with mock.patch.object(documents, "_ocr_language", return_value="eng"), mock.patch.object(documents, "_ocr_page", return_value="Parcela: 12/3\nPodil: 1/8"):
            result = documents.inspect_document(path, ocr=True)
        self.assertEqual(result["pages"][0]["extraction"], "ocr")
        self.assertEqual(result["pages"][0]["native_text"], "")
        self.assertTrue(result["candidates"]["shares"][0]["review_required"])
        self.assertEqual(result["candidates"]["shares"][0]["origin"], "ocr")

    def test_ocr_renders_hashed_snapshot_when_original_path_changes(self):
        path = self.pdf([""])
        original = path.read_bytes()
        replacement_path = self.root / "replacement.pdf"
        make_pdf(replacement_path, ["A DIFFERENT PDF"])
        replacement = replacement_path.read_bytes()
        rendered = []
        def change_original(_result):
            # Simulate another application saving over the original after the
            # inspector has read it, but before Poppler would open its path.
            path.write_bytes(replacement)
            return "eng"
        def execute(command, **_kwargs):
            if command[0] == "pdftoppm":
                snapshot = Path(command[-2])
                if os.name != "nt":
                    self.assertEqual(snapshot.stat().st_mode & 0o077, 0)
                    self.assertEqual(snapshot.parent.stat().st_mode & 0o077, 0)
                rendered.append((snapshot, snapshot.read_bytes()))
                return subprocess.CompletedProcess(command, 0, b"", b"")
            if command[0] == "tesseract":
                text = b"Podil: 1/8" if rendered[-1][1] == original else b"Podil: 3/4"
                return subprocess.CompletedProcess(command, 0, text, b"")
            self.fail("Unexpected subprocess")
        with mock.patch.object(documents, "_ocr_language", side_effect=change_original), mock.patch.object(documents.subprocess, "run", side_effect=execute):
            result = documents.inspect_document(path, ocr=True)
        self.assertEqual(result["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(result["pages"][0]["text"], "Podil: 1/8")
        self.assertEqual(rendered[0][1], original)
        self.assertNotEqual(rendered[0][0], path)
        self.assertFalse(rendered[0][0].exists(), "Private OCR snapshot must be removed")
        self.assertEqual(path.read_bytes(), replacement, "Inspector must not rewrite a concurrently changed original")

    def test_ocr_failure_stays_unread_and_ocr_is_not_used_for_native_page(self):
        path = self.pdf([""])
        with mock.patch.object(documents, "_ocr_language", return_value="eng"), mock.patch.object(documents, "_ocr_page", side_effect=subprocess.TimeoutExpired("ocr", 1)):
            result = documents.inspect_document(path, ocr=True)
        self.assertIn("ocr_failed", self.codes(result))
        self.assertIn("page_without_text", self.codes(result))
        path = self.pdf(["This page has enough native document text to read."])
        with mock.patch.object(documents, "_ocr_language", return_value="eng"), mock.patch.object(documents, "_ocr_page") as worker:
            documents.inspect_document(path, ocr=True)
            worker.assert_not_called()

    def test_text_truncation_is_explicit(self):
        path = self.pdf(["This page contains more than ten characters."])
        with mock.patch.object(documents, "MAX_PAGE_TEXT", 10):
            result = documents.inspect_document(path)
        self.assertEqual(len(result["pages"][0]["text"]), 10)
        self.assertIn("page_text_truncated", self.codes(result))


if __name__ == "__main__":
    unittest.main()
