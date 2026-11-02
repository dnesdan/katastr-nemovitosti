#!/usr/bin/env python3
"""Command line tools for Katastr a souvislosti. No login or data upload."""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import sys
import tempfile

from case_model import compare_cases, new_case, public_case, read_case, require_valid, utc_now

SKILL_ROOT = Path(__file__).resolve().parents[1]


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def output_path(value, force=False):
    requested = Path(value).expanduser()
    if requested.is_symlink():
        raise ValueError("Výstupní soubor nesmí být symbolický odkaz.")
    path = requested.resolve()
    if path == SKILL_ROOT or SKILL_ROOT in path.parents:
        raise ValueError("Případové výstupy ukládej mimo adresář instalovaného skillu.")
    if path.exists() and not force:
        raise ValueError("Výstup už existuje. Zvol jiný soubor nebo výslovné --force.")
    if path.exists() and not path.is_file():
        raise ValueError("Výstup musí být cesta k běžnému souboru.")
    return path


def input_path(value):
    return Path(value).expanduser().resolve()


def data_directory(value, label):
    requested = Path(value).expanduser()
    if requested.is_symlink():
        raise ValueError(f"{label}: adresář nesmí být symbolický odkaz.")
    path = requested.resolve()
    if path == SKILL_ROOT or SKILL_ROOT in path.parents:
        raise ValueError(f"{label} ukládej mimo adresář instalovaného skillu.")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{label}: očekávána cesta k adresáři.")
    return path


def _write_bytes(data, target, force=False):
    """Publish a complete temporary file; a no-force save never replaces a peer."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".katastr-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temp, target)
        else:
            try:
                os.link(temp, target)
            except FileExistsError as exc:
                raise ValueError("Výstup mezitím vznikl; nic nepřepsáno.") from exc
            except OSError as exc:
                if exc.errno not in {errno.EPERM, errno.EACCES, errno.ENOSYS, errno.EXDEV, errno.EOPNOTSUPP}:
                    raise
                # Some network filesystems do not support hard links. Exclusive
                # creation still protects another file and uses private permissions.
                try:
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError as collision:
                    raise ValueError("Výstup mezitím vznikl; nic nepřepsáno.") from collision
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save(text, path=None, force=False):
    if path is None:
        print(text, end="" if text.endswith("\n") else "\n")
        return
    target = output_path(path, force)
    _write_bytes(text.encode("utf-8"), target, force)
    print(str(target), file=sys.stderr)


def _save_bundle(payloads, force=False):
    """Preflight all map outputs and restore old files after a normal write error."""
    targets = [output_path(path, force) for path, _ in payloads]
    if len(set(targets)) != len(targets):
        raise ValueError("Výstupy mapy a metadat vyžadují různé soubory.")
    backups = {}
    written = []
    succeeded = False
    try:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            if force and target.exists():
                fd, backup = tempfile.mkstemp(prefix=".katastr-backup-", dir=target.parent)
                os.close(fd)
                os.replace(target, backup)
                backups[target] = Path(backup)
        for target, (_, data) in zip(targets, payloads):
            _write_bytes(data, target, force=False)
            written.append(target)
        succeeded = True
    except Exception as original:
        restore_errors = []
        for target in written:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                restore_errors.append(str(target))
        for target, backup in backups.items():
            try:
                os.replace(backup, target)
            except OSError:
                restore_errors.append(str(backup))
        if restore_errors:
            raise RuntimeError("Zápis selhal a některé výstupy nelze obnovit. Zachované zálohy/cesty: " + ", ".join(restore_errors)) from original
        raise
    finally:
        if succeeded:
            for backup in backups.values():
                backup.unlink(missing_ok=True)


def fetch_map(client, args):
    """Stage the adapter's immutable map+sidecar before applying CLI --force."""
    import sources
    target = output_path(args.out, args.force)
    sidecar = output_path(str(target) + ".json", args.force)
    metadata = output_path(args.metadata, args.force) if args.metadata else None
    if metadata == target:
        raise ValueError("Mapa a metadata vyžadují různé výstupní soubory.")
    try:
        bbox = [float(n.strip()) for n in args.bbox.split(",")]
    except ValueError as exc:
        raise ValueError("BBOX zadej jako čtyři desetinná čísla west,south,east,north.") from exc
    # Validate before creating directories or invoking a network client.
    sources.parse_bbox(bbox, "EPSG:4326")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".katastr-map-", dir=target.parent) as temporary:
        staged = Path(temporary) / target.name
        result = sources.wms_map(client, args.url, args.layer, bbox, staged, width=args.width,
                                 height=args.height, version=args.wms_version, crs="EPSG:4326", refresh=args.refresh)
        result = {**result, "file": str(target), "sidecar": str(sidecar)}
        metadata_bytes = json_text(result).encode("utf-8")
        payloads = [(target, staged.read_bytes()), (sidecar, metadata_bytes)]
        if metadata is not None and metadata != sidecar:
            payloads.append((metadata, metadata_bytes))
        _save_bundle(payloads, args.force)
    print(str(target), file=sys.stderr)
    print(str(sidecar), file=sys.stderr)
    if metadata is not None and metadata != sidecar:
        print(str(metadata), file=sys.stderr)
    if metadata is None:
        save(json_text(result))


def catalogue():
    return json.loads((SKILL_ROOT / "references/source-catalogue.json").read_text(encoding="utf-8"))


def select_sources(topics):
    data = catalogue()
    known = {t for source in data["sources"] for t in source["topics"]}
    if set(topics) - known:
        raise ValueError("Neznámé téma: " + ", ".join(sorted(set(topics)-known)) + ". Dostupná: " + ", ".join(sorted(known)))
    return [source for source in data["sources"] if not topics or set(source["topics"]) & set(topics)]


def research_plan(place, topics):
    if not place.strip():
        raise ValueError("Uveď obec/území, pro které plán připravujeme.")
    return {"plan_version": "property-plan/1.0", "created_at": utc_now(), "place_query": place.strip(),
            "status": "planned", "identity_confirmed": False,
            "notice": "Plán výzkumu. Zdroje níže nejsou dosud prověřené pro tuto nemovitost.",
            "steps": [
                "Určit objekt: kód katastru, typ, parcelní číslo a číselná řada; u jednotky i vazba na dům.",
                "Zaznamenat účel prověření a rozhodný okamžik; zapsat související parcely a přístup.",
                "Prozkoumat vybrané veřejné zdroje a uchovat skutečné dotazy, čas, pokrytí a důkazy.",
                "Přečíst dodané dokumenty, prověřit úplnost, přílohy a kritické OCR hodnoty.",
                "Doložit jednotlivé závěry nebo přesně označit rozpor, mezeru a další potřebný podklad.",
                "Validovat případ a vydat přehledný report s konkrétními citacemi a dalšími kroky."],
            "selected_topics": topics, "sources": select_sources(topics),
            "local_routing": "Územní plán a místní podklady dohledat podle konkrétní obce, ORP a kraje. Nevybrat pevnou výchozí obec.",
            "document_handoff": "Přihlášení a případný nákup výpisu/listiny provede uživatel. Požadavek musí uvést přesný dokument a řešenou otázku."}


def add_document(case, inspection, identifier, title, kind):
    import copy
    out = copy.deepcopy(case)
    out["documents"].append({"id": identifier, "title": title, "kind": kind,
        "sha256": inspection["sha256"], "pages": inspection.get("page_count") or 0,
        "register_state_at": "", "issued_at": "", "imported_at": utc_now(),
        "completeness": inspection.get("completeness", "unknown"),
        "seal_status": inspection.get("seal_status", "not_checked"), "public": False,
        "inspection": inspection})
    out["findings"].append({"id": identifier + "-kontrola", "title": "Ověřit importovaný dokument: " + title,
        "topic": "documents", "status": "unverified", "severity": "medium",
        "summary": "Automatická inspekce byla uložena. Identifikátory, časový stav, obsah a úplnost vyžadují kontrolu originálu.",
        "object_ids": [], "evidence_ids": [], "next_step": "Otevřít originál a přílohy, potvrdit klíčové údaje a přidat přesně lokalizované důkazy.", "public": False})
    out["research_log"].append({"at": utc_now(), "query": "Lokální import dokumentu " + identifier,
        "status": "ok", "note": "Inspekce není úplná právní interpretace ani kryptografické ověření pečeti."})
    return require_valid(out)


def add_output(parser, required=False):
    parser.add_argument("--out", required=required, help="Výstupní soubor mimo skill; bez volby standardní výstup")
    parser.add_argument("--force", action="store_true", help="Výslovně přepsat existující výstup")


def build_parser():
    parser = argparse.ArgumentParser(description="Katastr a souvislosti: veřejné podklady, PDF/XML a citovaný offline report.")
    parser.add_argument("--version", action="version", version="Katastr a souvislosti 0.1.0 (property-case/1.0)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="Založit prázdný soukromý případ")
    p.add_argument("--title", required=True); p.add_argument("--place", required=True)
    p.add_argument("--purpose", default="Orientace v nemovitosti"); p.add_argument("--region", default="")
    add_output(p, True)
    p = sub.add_parser("sources", help="Katalog dostupných zdrojů, nikoli rešerše")
    p.add_argument("--topic", action="append", default=[]); add_output(p)
    p = sub.add_parser("plan", help="Připravit plán hledání a předání dokumentů")
    p.add_argument("--place", required=True); p.add_argument("--topics", default="identity,rights,planning,water,utilities")
    add_output(p)
    p = sub.add_parser("validate", help="Ověřit model, identitu, souřadnice a vazby důkazů")
    p.add_argument("case")
    p = sub.add_parser("inspect", help="Lokálně prohlédnout PDF/XML/text bez změny originálu")
    p.add_argument("document"); p.add_argument("--attachments", help="Volitelná složka pro bezpečně pojmenované přílohy")
    p.add_argument("--ocr", action="store_true", help="OCR stran bez textu; vyžaduje Poppler a Tesseract")
    add_output(p)
    p = sub.add_parser("add-document", help="Připojit soukromou inspekci a otevřenou kontrolu k případu")
    p.add_argument("case"); p.add_argument("document"); p.add_argument("--id", required=True)
    p.add_argument("--title", required=True); p.add_argument("--kind", default="other")
    p.add_argument("--ocr", action="store_true"); add_output(p, True)
    p = sub.add_parser("report", help="Vytvořit samostatný HTML/Markdown/GeoJSON výstup")
    p.add_argument("case"); p.add_argument("--format", choices=["html", "markdown", "geojson"], default="html")
    p.add_argument("--public", action="store_true", help="Pouze výslovně zkontrolovaný a označený výběr")
    add_output(p, True)
    p = sub.add_parser("compare", help="Porovnat dvě uložené verze stejného případu")
    p.add_argument("older"); p.add_argument("newer"); add_output(p)
    p = sub.add_parser("fetch", help="Malé čtení podporovaných veřejných datových služeb")
    services = p.add_subparsers(dest="service", required=True)
    for name in ("ruian", "building", "parcel", "wms", "map"):
        item = services.add_parser(name)
        item.add_argument("--cache", help="Sdílená cache mimo adresář skillu")
        item.add_argument("--refresh", action="store_true", help="Obnovit zdroj s dodržením blokování a rozestupů")
        add_output(item, name == "map")
        if name == "ruian":
            item.add_argument("query"); item.add_argument("--kind", choices=["address", "municipality", "cadastral", "part"], default="address")
            item.add_argument("--limit", type=int, default=20)
        elif name == "building":
            item.add_argument("code")
        elif name == "parcel":
            item.add_argument("--cadastral", required=True); item.add_argument("--number", required=True)
            item.add_argument("--series", choices=["land", "building"], default="land")
        else:
            item.add_argument("--url", default="https://services.cuzk.gov.cz/wms/local-km-wms.asp")
            item.add_argument("--wms-version", choices=["1.1.1", "1.3.0"])
            if name == "map":
                item.add_argument("--layer", required=True); item.add_argument("--bbox", required=True, help="west,south,east,north v EPSG:4326")
                item.add_argument("--width", type=int, default=1000); item.add_argument("--height", type=int, default=700)
                item.add_argument("--metadata", help="Další kopie JSON původu; výchozí soubor mapa.png.json vzniká vždy")
    return parser


def run(args):
    if args.command == "validate":
        read_case(input_path(args.case))
        print("OK: property-case/1.0; platná struktura a vazby. Nejde o potvrzení věcné pravdivosti.")
        return
    if getattr(args, "out", None):
        output_path(args.out, args.force)
    if args.command == "init":
        result = require_valid(new_case(args.title, args.place, args.purpose, args.region))
    elif args.command == "sources":
        result = {"checked_at": catalogue()["checked_at"], "sources": select_sources(args.topic)}
    elif args.command == "plan":
        result = research_plan(args.place, [t.strip() for t in args.topics.split(",") if t.strip()])
    elif args.command in ("inspect", "add-document"):
        from documents import inspect_document
        document = input_path(args.document)
        if getattr(args, "out", None) and document == input_path(args.out):
            raise ValueError("Originální dokument se nesmí přepsat výstupem inspekce.")
        attachments = getattr(args, "attachments", None)
        attachments = data_directory(attachments, "Přílohy") if attachments else None
        case = read_case(input_path(args.case)) if args.command == "add-document" else None
        result = inspect_document(document, output_dir=attachments, ocr=args.ocr)
        if args.command == "add-document":
            result = add_document(case, result, args.id, args.title, args.kind)
    elif args.command == "report":
        from report import render_html, render_markdown, export_geojson
        if input_path(args.case) == input_path(args.out):
            raise ValueError("Report nesmí přepsat zdrojový případ.")
        case = read_case(input_path(args.case))
        if args.public:
            case = public_case(case)
        else:
            # The local full report can include private records even when a
            # reviewed public subset exists. Its banner must describe this output.
            case["case"]["sharing"] = "private"
        result = {"html": render_html, "markdown": render_markdown, "geojson": export_geojson}[args.format](case)
    elif args.command == "compare":
        older, newer = input_path(args.older), input_path(args.newer)
        if getattr(args, "out", None) and input_path(args.out) in (older, newer):
            raise ValueError("Porovnání nesmí přepsat žádný zdrojový případ.")
        result = compare_cases(read_case(older), read_case(newer))
    elif args.command == "fetch":
        from http_client import HttpClient
        import sources
        cache = data_directory(args.cache, "Cache") if args.cache else None
        client = HttpClient(cache_dir=cache)
        # An environment-selected default cache must also stay outside the skill.
        if hasattr(client, "cache_dir"):
            data_directory(client.cache_dir, "Cache")
        if args.service == "ruian":
            result = sources.ruian(client, args.query, kind=args.kind, limit=args.limit, refresh=args.refresh)
        elif args.service == "building":
            result = sources.ruian_building(client, args.code, refresh=args.refresh)
        elif args.service == "parcel":
            result = sources.parcel(client, args.cadastral, args.number, series=args.series, refresh=args.refresh)
        elif args.service == "wms":
            result = sources.wms(client, args.url, version=args.wms_version, refresh=args.refresh)
        else:
            fetch_map(client, args)
            return
    else:
        raise ValueError("Neznámý příkaz")
    save(result if isinstance(result, str) else json_text(result), getattr(args, "out", None), getattr(args, "force", False))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run(args)
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
