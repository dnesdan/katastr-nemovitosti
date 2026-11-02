"""Conservative, offline inspection of user supplied cadastral documents.

This extracts evidence candidates, not legal conclusions or authenticated records.
PDF inspection needs pypdf >= 5; optional OCR uses Poppler and Tesseract locally.
The input file is never rewritten. Attachments are untrusted and never executed.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_PAGES = 300
MAX_PAGE_TEXT = 100_000
MAX_TOTAL_TEXT = 2_000_000
MAX_ATTACHMENTS = 40
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 24 * 1024 * 1024
MAX_XML_ELEMENTS = 20_000
MAX_XML_DEPTH = 64
MAX_OCR_PAGES = 20


class DocumentError(ValueError):
    """A document cannot be inspected without changing its input assumptions."""

    def __init__(self, message: str, code: str = "invalid_document"):
        super().__init__(message)
        self.code = code


def _warning(result: dict, code: str, message: str, **locator: object) -> None:
    result["warnings"].append({"code": code, "message": message, **locator})


def _ascii(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(c))


def _base(data: bytes, kind: str, name: str) -> dict:
    return {
        "inspection_version": "document-inspection/1.0",
        "file_name": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "type": kind, "size": len(data), "page_count": None,
        "pages": [], "attachments": [], "warnings": [],
        "completeness": "unknown", "seal_status": "not_checked",
        "candidates": {}, "requires_review": True,
    }


def _read_input(path: Path) -> bytes:
    if not path.is_file():
        raise DocumentError("Vstup není běžný soubor.", "not_a_file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DocumentError("Soubor přesahuje limit 32 MiB.", "file_too_large")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError("Soubor přesahuje limit 32 MiB.", "file_too_large")
    if not data:
        raise DocumentError("Soubor je prázdný.", "empty_document")
    return data


def _xml_text(data: bytes) -> str:
    if len(data) > MAX_XML_BYTES:
        raise DocumentError("XML přesahuje limit 5 MiB.", "xml_too_large")
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        if data.startswith(b"\x00<"):
            return data.decode("utf-16-be")
        if data.startswith(b"<\x00"):
            return data.decode("utf-16-le")
        return data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DocumentError("Podporované XML musí být UTF-8 nebo UTF-16.",
                            "xml_encoding") from exc


def _xml_inventory(data: bytes) -> dict:
    text = _xml_text(data)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
        raise DocumentError("XML obsahuje zakázanou deklaraci DTD nebo entity.",
                            "unsafe_xml")
    # Parse decoded text so UTF-16 and declaration variations cannot bypass checks.
    # No schema, XInclude, URL, processing instruction or external resource is loaded.
    depth = 0
    count = 0
    root = None
    fields: list[dict] = []
    leaf_count = 0
    values_truncated = False
    path: list[str] = []
    try:
        for event, node in ET.iterparse(io.StringIO(text), events=("start", "end")):
            if event == "start":
                depth += 1
                count += 1
                if depth > MAX_XML_DEPTH or count > MAX_XML_ELEMENTS:
                    raise DocumentError("XML překračuje limit struktury.", "xml_limits")
                if root is None:
                    root = node
                path.append(node.tag)
            else:
                value = (node.text or "").strip()
                if not len(node) and value:
                    leaf_count += 1
                    values_truncated = values_truncated or len(value) > 2000
                    if len(fields) < 500:
                        fields.append({"tag": node.tag, "value": value[:2000],
                                       "locator": "/".join(path)})
                depth -= 1
                path.pop()
    except ET.ParseError as exc:
        raise DocumentError("XML není dobře utvořené.", "invalid_xml") from exc
    if root is None:
        raise DocumentError("XML nemá kořenový element.", "invalid_xml")
    tag = root.tag
    namespace = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
    attrs = {str(k): str(v)[:500] for k, v in list(root.attrib.items())[:30]}
    return {"root_tag": tag, "namespace": namespace, "root_attributes": attrs,
            "element_count": count, "schema_status": "unsupported",
            "fields": fields, "fields_truncated": leaf_count > 500,
            "values_truncated": values_truncated,
            "attributes_truncated": len(root.attrib) > 30 or any(len(str(v)) > 500 for v in root.attrib.values())}


def _find_candidates(pages: list[dict]) -> dict:
    found: dict[str, list] = {
        "lv_numbers": [], "cadastral_areas": [], "parcels": [], "shares": [],
        "proceedings": [], "register_state_at": [], "issued_at": [],
        "sections": [], "page_markers": [],
    }
    kind = "unknown"
    patterns = {
        "lv_numbers": re.compile(
            r"\b(?:list\s+vlastnictvi|LV)\s*(?:c(?:islo)?\.?\s*)?[:=]?\s*(\d{1,9})\b", re.I),
        "proceedings": re.compile(r"\b(?:V|Z|P)-\d{1,9}-\d{4}(?:-\d{1,5})?\b", re.I),
        "parcels": re.compile(
            r"\b(?:parcelni\s+cislo|parcela|parc\.\s*c\.)\s*[:=]?\s*(st\.\s*)?(\d{1,9}(?:/\d{1,5})?)\b", re.I),
        "shares": re.compile(r"\bpodil\s*[:=]?\s*(\d{1,12})\s*/\s*(\d{1,12})\b", re.I),
        "cadastral_areas": re.compile(
            r"\bkatastralni\s+uzemi\s*[:=]?\s*\[?(\d{6})\]?([^\n]{0,100})", re.I),
        "page_markers": re.compile(
            r"\b(?:strana|stranka|page)\s*:?\s*(\d{1,4})\s*(?:z|of|/)\s*(\d{1,4})\b", re.I),
    }
    for page in pages:
        text = unicodedata.normalize("NFC", page.get("text", ""))
        plain = _ascii(text)
        if re.search(r"vypis\s+z\s+katastru|list\s+vlastnictvi", plain, re.I):
            kind = "lv"
        for key, pattern in patterns.items():
            for match in list(pattern.finditer(plain))[:100]:
                candidate: dict = {"page": page["number"],
                                   "text": text[match.start():match.end()],
                                   "origin": page["extraction"], "review_required": True}
                if key == "shares":
                    candidate["value"] = {"numerator": int(match[1]), "denominator": int(match[2])}
                    candidate["valid_fraction"] = int(match[2]) > 0 and int(match[1]) <= int(match[2])
                elif key == "parcels":
                    candidate["value"] = {"number": match[2], "series": "building" if match[1] else "unspecified"}
                elif key == "cadastral_areas":
                    candidate["value"] = {"code": match[1], "name_candidate": match[2].strip()}
                elif key == "page_markers":
                    candidate["value"] = {"number": int(match[1]), "total": int(match[2])}
                else:
                    candidate["value"] = match[1] if match.lastindex else match[0]
                found[key].append(candidate)
        for line in text.splitlines():
            normalized = _ascii(line)
            for key, label in (("register_state_at", r"(?:platnost.*?\bk|stav.*?\b(?:k|ke))"),
                               ("issued_at", r"(?:vyhotoveno|vytvoreno|vydano|datum\s+vyhotoveni)")):
                match = re.search(label + r"\s*[:=]?\s*(\d{1,2}\.\s*\d{1,2}\.\s*\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)", normalized, re.I)
                if match:
                    found[key].append({"value": match[1], "page": page["number"],
                                       "text": line, "origin": page["extraction"], "review_required": True})
            section = re.match(r"^\s*(B1|A|B|C|D|E|F)\s+([^\d\s].{2,120})$", line)
            if section:
                found["sections"].append({"value": section[1], "page": page["number"],
                                          "text": line, "review_required": True})
    return {"kind": kind, **found}


def _assess_completeness(result: dict) -> None:
    text = "\n".join(page["text"] for page in result["pages"])
    if re.search(r"(?:^|\n)\s*CASTECNY\s+VYPIS\b", _ascii(text), re.I):
        result["completeness"] = "partial"
        _warning(result, "partial_extract", "Dokument je označen jako částečný výpis.")
    markers = result["candidates"].get("page_markers", [])
    totals = {x["value"]["total"] for x in markers}
    if len(totals) == 1:
        total = next(iter(totals))
        seen = {x["value"]["number"] for x in markers}
        if total > (result["page_count"] or 0):
            result["completeness"] = "partial"
            _warning(result, "missing_pages", "Tištěné stránkování uvádí více stran než obsahuje soubor.")
        if total and seen == set(range(1, total + 1)) and total == result["page_count"]:
            result["page_sequence_complete"] = True
    elif len(totals) > 1:
        _warning(result, "mixed_page_sequences", "Dokument obsahuje různá stránkování; zkontroluj jeho části.")
    # Physical pagination is insufficient to certify legal/document completeness.
    if result["completeness"] == "unknown":
        _warning(result, "completeness_not_certified", "Úplnost je nutné ověřit podle rozsahu, stran a příloh originálu.")


def _resolve(obj: object) -> object:
    return obj.get_object() if hasattr(obj, "get_object") else obj


def _object_key(obj: object) -> tuple:
    ref = getattr(obj, "indirect_reference", None)
    if ref is None and hasattr(obj, "idnum"):
        ref = obj
    return ("ref", ref.idnum, getattr(ref, "generation", 0)) if ref is not None else ("obj", id(obj))


def _file_specs(reader: object, pages: list, result: dict) -> list[tuple[str, object]]:
    specs = []
    seen_specs: set = set()
    seen_nodes: set = set()

    def add(obj: object, name: str = "") -> None:
        key = _object_key(obj)
        if key in seen_specs:
            return
        seen_specs.add(key)
        if len(specs) >= MAX_ATTACHMENTS:
            raise DocumentError("Příliš mnoho vložených souborů.", "attachment_count_limit")
        obj = _resolve(obj)
        if isinstance(obj, dict) and "/EF" in obj:
            specs.append((name or str(obj.get("/UF") or obj.get("/F") or "příloha"), obj))

    def visit_tree(obj: object, depth: int = 0) -> None:
        if depth > 16 or len(seen_nodes) > 1000:
            raise DocumentError("Strom příloh překračuje limit.", "attachment_tree_limit")
        key = _object_key(obj)
        if key in seen_nodes:
            return
        seen_nodes.add(key)
        obj = _resolve(obj)
        if not isinstance(obj, dict):
            return
        pairs = _resolve(obj.get("/Names", []))
        for i in range(0, len(pairs) - 1, 2):
            add(pairs[i + 1], str(pairs[i]))
        for child in _resolve(obj.get("/Kids", [])):
            visit_tree(child, depth + 1)

    root = reader.root_object
    try:
        names = _resolve(root.get("/Names", {}))
        if isinstance(names, dict) and "/EmbeddedFiles" in names:
            visit_tree(names["/EmbeddedFiles"])
        for holder in [root, *pages]:
            for spec in _resolve(holder.get("/AF", [])):
                add(spec)
            for annotation in _resolve(holder.get("/Annots", [])):
                annotation = _resolve(annotation)
                if isinstance(annotation, dict) and annotation.get("/Subtype") == "/FileAttachment" and "/FS" in annotation:
                    add(annotation["/FS"])
    except Exception as exc:
        code = exc.code if isinstance(exc, DocumentError) else "attachment_inventory_error"
        _warning(result, code, "Inventář příloh není úplný; zbývající přílohy ověř v prohlížeči PDF.")
    return specs


def _attachment_type(data: bytes, name: str) -> tuple[str, str]:
    if data.lstrip().startswith(b"%PDF-"):
        return "pdf", ".pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff", ".tif"
    if Path(name).suffix.lower() in {".html", ".htm", ".svg", ".js", ".mjs", ".py", ".sh", ".exe", ".bat", ".cmd", ".ps1", ".jar", ".zip"}:
        return "unsupported", ""
    if name.lower().endswith(".xml") or data.lstrip().startswith((b"<?xml", b"<")) or data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "xml", ".xml"
    if name.lower().endswith(".txt"):
        try:
            data.decode("utf-8-sig")
            return "text", ".txt"
        except UnicodeError:
            pass
    return "unsupported", ""


def _save_attachment(directory: Path, name: str, data: bytes) -> str:
    if directory.is_symlink():
        raise DocumentError("Adresář příloh nesmí být symbolický odkaz.", "unsafe_output_path")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name  # name is generated internally, never the embedded filename
    if destination.is_symlink():
        raise DocumentError("Cílová příloha je symbolický odkaz.", "unsafe_output_path")
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if destination.is_file() and destination.stat().st_size == len(data):
            with destination.open("rb") as existing:
                if hashlib.sha256(existing.read(MAX_ATTACHMENT_BYTES + 1)).digest() == hashlib.sha256(data).digest():
                    return name
        raise DocumentError("Cílový soubor přílohy již existuje s jiným obsahem.", "output_collision")
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    return name


def _inspect_attachments(reader: object, pages: list, result: dict, output_dir: Path | None) -> None:
    total = 0
    for index, (name, spec) in enumerate(_file_specs(reader, pages, result), 1):
        attachment = {"name": name, "type": "unknown", "size": None, "sha256": None,
                      "status": "unread", "requires_review": True}
        result["attachments"].append(attachment)
        try:
            ef = _resolve(spec["/EF"])
            stream = _resolve(ef.get("/UF") or ef.get("/F"))
            if not hasattr(stream, "get_data"):
                raise DocumentError("Příloha nemá čitelný datový proud.", "attachment_stream")
            declared_size = _resolve(stream.get("/Params", {})).get("/Size")
            if declared_size is not None and int(declared_size) > MAX_ATTACHMENT_BYTES:
                raise DocumentError("Příloha překračuje velikostní limit.", "attachment_size_limit")
            data = stream.get_data()
            if len(data) > MAX_ATTACHMENT_BYTES or total + len(data) > MAX_TOTAL_ATTACHMENT_BYTES:
                raise DocumentError("Přílohy překračují velikostní limit.", "attachment_size_limit")
            total += len(data)
            kind, extension = _attachment_type(data, name)
            attachment.update({"type": kind, "size": len(data),
                               "sha256": hashlib.sha256(data).hexdigest(), "status": "inventoried"})
            if kind == "unsupported":
                attachment["status"] = "blocked"
                _warning(result, "unsupported_attachment", "Příloha má nepodporovaný formát; nebyla extrahována.", attachment=index)
                continue
            if kind == "xml":
                attachment["xml"] = _xml_inventory(data)
                attachment["status"] = "inspected"
                _warning(result, "xml_schema_unsupported", "XML bylo inventarizováno; struktura právních údajů není validována podle schématu NTŘ.", attachment=index)
                if any(attachment["xml"][key] for key in ("fields_truncated", "values_truncated", "attributes_truncated")):
                    _warning(result, "xml_inventory_truncated", "Inventář XML přílohy byl zkrácen; originál obsahuje další údaje.", attachment=index)
            if output_dir is not None:
                safe_name = f"attachment-{index:03d}-{attachment['sha256'][:12]}{extension}"
                attachment["path"] = _save_attachment(output_dir, safe_name, data)
            if kind in ("pdf", "image/png", "image/jpeg", "image/tiff"):
                attachment["requires_followup"] = True
                _warning(result, "attachment_content_not_read", "Obrazová nebo PDF příloha vyžaduje samostatné přečtení; inventář není analýzou jejího obsahu.", attachment=index)
        except Exception as exc:
            attachment["status"] = "blocked"
            code = exc.code if isinstance(exc, DocumentError) else "attachment_read_error"
            attachment["error_code"] = code
            _warning(result, code, "Přílohu se nepodařilo bezpečně zpracovat; obsah zůstává neověřený.", attachment=index)


def _signature_status(reader: object, result: dict) -> None:
    try:
        fields = reader.get_fields() or {}
        for field in fields.values():
            if field.get("/FT") == "/Sig" and field.get("/V"):
                result["seal_status"] = "present_unverified"
        perms = _resolve(reader.root_object.get("/Perms", {}))
        if isinstance(perms, dict) and perms.get("/DocMDP"):
            result["seal_status"] = "present_unverified"
    except Exception:
        _warning(result, "signature_inspection_failed", "Přítomnost podpisu či pečeti nelze spolehlivě určit.")
    if result["seal_status"] == "present_unverified":
        _warning(result, "signature_not_verified", "Podpisové údaje jsou přítomné; kryptografická platnost, certifikát a časové razítko nebyly ověřeny.")


def _ocr_page(data: bytes, number: int, language: str) -> str:
    """Render exactly the bytes used for the hash, never reopen the user's path."""
    with tempfile.TemporaryDirectory(prefix="katastr-ocr-") as tmp:
        snapshot = Path(tmp) / "source.pdf"
        fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        stem = Path(tmp) / "page"
        subprocess.run(["pdftoppm", "-f", str(number), "-l", str(number), "-scale-to", "3200",
                        "-singlefile", "-png", str(snapshot), str(stem)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=45)
        result = subprocess.run(["tesseract", str(stem) + ".png", "stdout", "-l", language],
                                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        return result.stdout.decode("utf-8", errors="replace")[:MAX_PAGE_TEXT]


def _ocr_language(result: dict) -> str | None:
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        _warning(result, "ocr_unavailable", "Pro OCR chybí Poppler (pdftoppm) nebo Tesseract; původní text zůstává zachován.")
        return None
    try:
        process = subprocess.run(["tesseract", "--list-langs"], check=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        languages = process.stdout.decode("utf-8", errors="replace").splitlines()
        selected = [lang for lang in ("ces", "eng") if lang in languages]
        if not selected:
            _warning(result, "ocr_language_unavailable", "Tesseract nemá jazyk ces ani eng; OCR nebylo spuštěno.")
            return None
        if "ces" not in selected:
            _warning(result, "ocr_czech_unavailable", "OCR používá anglický model; české znaky a všechny identifikátory vyžadují vizuální kontrolu.")
        return "+".join(selected)
    except (OSError, subprocess.SubprocessError):
        _warning(result, "ocr_unavailable", "Dostupnost jazyků OCR se nepodařilo ověřit.")
        return None


def _inspect_pdf(data: bytes, path: Path, output_dir: Path | None, ocr: bool) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentError("Pro PDF nainstaluj volitelnou závislost: python -m pip install 'pypdf>=5'.",
                            "dependency_missing") from exc
    result = _base(data, "pdf", path.name)
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            result["encrypted"] = True
            if not reader.decrypt(""):
                _warning(result, "password_required", "PDF vyžaduje heslo; připrav oprávněně přístupnou kopii. Originál zůstává zachován.")
                return result
        count = len(reader.pages)
        result["page_count"] = count
        if count > MAX_PAGES:
            raise DocumentError("PDF přesahuje limit 300 stran.", "page_limit")
        pages = list(reader.pages)
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("PDF nelze přečíst; zkontroluj originál v prohlížeči.", "invalid_pdf") from exc
    _signature_status(reader, result)
    language = _ocr_language(result) if ocr else None
    total_text = 0
    ocr_count = 0
    for number, page in enumerate(pages, 1):
        extracted = {"number": number, "text": "", "extraction": "none"}
        try:
            text = page.extract_text() or ""
            if len(text) > MAX_PAGE_TEXT:
                _warning(result, "page_text_truncated", "Text stránky byl omezen na 100 000 znaků.", page=number)
            extracted.update(text=text[:MAX_PAGE_TEXT], extraction="native" if text.strip() else "none")
        except Exception:
            _warning(result, "page_extraction_failed", "Nativní text stránky se nepodařilo získat.", page=number)
        if len(extracted["text"].strip()) < 20 and language:
            if ocr_count >= MAX_OCR_PAGES:
                _warning(result, "ocr_page_limit", "OCR je omezeno na 20 stran jednoho spuštění.", page=number)
            else:
                ocr_count += 1
                try:
                    text = _ocr_page(data, number, language)
                    if text.strip():
                        extracted["native_text"] = extracted["text"]
                        extracted.update(text=text, extraction="ocr")
                        _warning(result, "ocr_requires_visual_review", "Text pochází z OCR; parcelu, podíl, katastr a datum ověř vizuálně.", page=number)
                except (OSError, subprocess.SubprocessError):
                    _warning(result, "ocr_failed", "OCR stránky se nepodařilo dokončit; nevyvozuj nepřítomnost údajů.", page=number)
        remaining = max(0, MAX_TOTAL_TEXT - total_text)
        if len(extracted["text"]) > remaining:
            extracted["text"] = extracted["text"][:remaining]
            _warning(result, "total_text_truncated", "Celkový text překročil limit 2 000 000 znaků.", page=number)
        total_text += len(extracted["text"])
        if not extracted["text"].strip():
            _warning(result, "page_without_text", "Stránka nemá čitelný text; může obsahovat obrazový sken.", page=number)
        result["pages"].append(extracted)
    _inspect_attachments(reader, pages, result, output_dir)
    result["candidates"] = _find_candidates(result["pages"])
    _assess_completeness(result)
    return result


def inspect_document(path: Path | str, output_dir: Path | str | None = None, ocr: bool = False) -> dict:
    """Inspect PDF, UTF-8 text or UTF-8/UTF-16 XML without changing the original.

    ``output_dir`` opts into extraction of allowed embedded files to generated
    names. Output paths are relative to this directory, never original filenames.
    No attachments are followed recursively or automatically made public.
    ``ocr`` is explicit and only affects PDF pages with little native text.
    Every result requires human/agent review before it becomes case evidence.
    """
    path = Path(path)
    data = _read_input(path)
    output = Path(output_dir) if output_dir is not None else None
    if output is not None and output.is_symlink():
        raise DocumentError("Adresář příloh nesmí být symbolický odkaz.", "unsafe_output_path")
    if data.lstrip().startswith(b"%PDF-"):
        return _inspect_pdf(data, path, output, ocr)
    if path.suffix.lower() == ".pdf":
        raise DocumentError("Soubor nemá platnou hlavičku PDF.", "invalid_pdf")
    if path.suffix.lower() == ".xml" or data.lstrip().startswith((b"<", b"\xef\xbb\xbf<")) or data.startswith((b"\xff\xfe", b"\xfe\xff")):
        inventory = _xml_inventory(data)
        result = _base(data, "xml", path.name)
        result["xml"] = inventory
        _warning(result, "xml_schema_unsupported", "XML bylo přečteno jako struktura; schéma NTŘ ani právní vazby zatím nejsou podporovaným parserem validovány.")
        if any(inventory[key] for key in ("fields_truncated", "values_truncated", "attributes_truncated")):
            _warning(result, "xml_inventory_truncated", "Inventář XML byl zkrácen; originál obsahuje další údaje.")
        return result
    if path.suffix.lower() == ".txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeError as exc:
            raise DocumentError("Textový podklad musí být UTF-8.", "text_encoding") from exc
        result = _base(data, "text", path.name)
        if len(text) > MAX_TOTAL_TEXT:
            _warning(result, "total_text_truncated", "Text překročil limit 2 000 000 znaků.")
        result["pages"] = [{"number": 1, "text": text[:MAX_TOTAL_TEXT], "extraction": "supplied_text"}]
        result["candidates"] = _find_candidates(result["pages"])
        _warning(result, "text_not_original", "Samostatný text nedokládá vzhled, stránkování, pečeť ani úplnost originálu.")
        return result
    raise DocumentError("Podporovány jsou PDF, XML a UTF-8 TXT.", "unsupported_type")
