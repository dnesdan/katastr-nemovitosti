"""Portable, offline property dossiers. Input must be validated before rendering.

The renderer never fetches maps, follows URLs, reads case document paths, or
mutates the case. Public selection is deliberately handled by case_model.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

STATUS = {
    "supported": "Doloženo", "conflict": "Rozpor", "missing": "Chybí podklad",
    "not_covered": "Zdroj nepokrývá", "unverified": "Neověřeno",
}
SEVERITY = {"high": "Zásadní pro rozhodnutí", "medium": "K dořešení", "info": "Souvislost"}
OBJECT_TYPES = {"parcel": "Parcela", "building": "Stavba", "unit": "Jednotka", "address": "Adresa", "area": "Území"}
TOPICS = {
    "identity": "Identita", "rights": "Právní vztahy", "access": "Přístup", "zoning": "Územní plán",
    "utilities": "Sítě", "flood": "Voda a povodně", "nature": "Příroda", "heritage": "Památky",
    "geology": "Geologie", "contamination": "Staré zátěže", "soil": "Půda", "history": "Historie",
    "energy": "Energie", "internet": "Internet", "noise": "Hluk", "documents": "Dokumenty",
}
ASSETS = Path(__file__).resolve().parent.parent / "assets"
MAP_PREVIEW_POINT_LIMIT = 20000


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _md(value) -> str:
    value = html.escape("" if value is None else str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|])", r"\\\1", value).replace("\r", "").replace("\n", " ")


def _url(value) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            return ""
        if any(c in value for c in ('<', '>', '"', "\\")):
            return ""
        _ = parts.port
        return value
    except ValueError:
        return ""


def _anchor(kind: str, identifier) -> str:
    return kind + "-" + hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:16]


def _date(value) -> str:
    if not value:
        return "neuvedeno"
    try:
        raw = str(value)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        date = f"{dt.day}. {dt.month}. {dt.year}"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return date
        clock = dt.strftime("%H:%M:%S")
        fraction = re.search(r"T\d{2}:\d{2}:\d{2}(\.\d+)", raw)
        if fraction:
            clock += fraction.group(1)
        offset = dt.strftime("%z")
        if offset:
            zone = "UTC" if offset == "+0000" else f"UTC{offset[:3]}:{offset[3:5]}"
        else:
            zone = "časové pásmo neuvedeno"
        return f"{date} · {clock} {zone}"
    except (ValueError, TypeError):
        return str(value)


def _link(url, label, css="") -> str:
    safe = _url(url)
    if not safe:
        return f'<span class="{_e(css)}">{_e(label)}</span>'
    return f'<a class="{_e(css)}" href="{_e(safe)}" target="_blank" rel="noopener noreferrer">{_e(label)}<span class="external" aria-hidden="true"> ↗</span></a>'


def _badge(status) -> str:
    key = status if status in STATUS else "unverified"
    return f'<span class="status status-{key}"><i aria-hidden="true"></i>{STATUS[key]}</span>'


def _locator(locator) -> str:
    if not isinstance(locator, dict):
        return "Lokátor neuveden"
    parts = []
    if locator.get("page") is not None:
        parts.append(f"strana {locator['page']}")
    if locator.get("section"):
        parts.append(f"oddíl {locator['section']}")
    if locator.get("attachment"):
        parts.append(f"příloha {locator['attachment']}")
    if locator.get("bbox"):
        parts.append("vyznačená oblast stránky")
    if locator.get("note"):
        parts.append(str(locator["note"]))
    return " · ".join(parts) or "Lokátor neuveden"


def _position(p):
    if not isinstance(p, (list, tuple)) or len(p) < 2:
        raise ValueError("Invalid position")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p[:2]):
        raise ValueError("Invalid coordinate")
    if not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90):
        raise ValueError("Not WGS84")
    return float(p[0]), float(p[1])


def _geometry_parts(geometry):
    """Return groups of rings, retaining polygon holes; reject malformed shapes."""
    if not isinstance(geometry, dict):
        raise ValueError("Missing geometry")
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point":
        groups = [[[_position(coords)]]]
    elif kind == "MultiPoint":
        groups = [[[_position(p)]] for p in coords]
    elif kind == "LineString":
        groups = [[[_position(p) for p in coords]]]
    elif kind == "MultiLineString":
        groups = [[[_position(p) for p in line]] for line in coords]
    elif kind == "Polygon":
        groups = [[[_position(p) for p in ring] for ring in coords]]
    elif kind == "MultiPolygon":
        groups = [[[_position(p) for p in ring] for ring in poly] for poly in coords]
    else:
        raise ValueError("Unsupported geometry")
    if not groups or any(not group or any(not line for line in group) for group in groups):
        raise ValueError("Empty geometry")
    if kind in {"Polygon", "MultiPolygon"} and any(len(ring) < 4 or ring[0] != ring[-1] for group in groups for ring in group):
        raise ValueError("Unclosed polygon")
    if kind in {"LineString", "MultiLineString"} and any(len(line) < 2 for group in groups for line in group):
        raise ValueError("Short line")
    return kind, groups


def _geometry_records(case, preview_limit=None):
    """Keep every object, distinguishing missing, invalid and limited previews.

    The HTML preview budget is not a validity condition and must never remove
    coordinates from a GeoJSON export.
    """
    records = []
    for obj in case.get("objects", []):
        record = {"object": obj, "kind": None, "groups": None, "count": 0}
        if obj.get("geometry") is None:
            records.append({**record, "state": "missing", "note": "Geometrie není dodána; objekt není zobrazen v mapě."})
            continue
        try:
            kind, groups = _geometry_parts(obj.get("geometry"))
            count = sum(len(line) for group in groups for line in group)
            record.update(kind=kind, groups=groups, count=count)
            if preview_limit is not None and count > preview_limit:
                note = (f"Geometrie je dodána ({count:,} bodů). Náhled není zobrazen: "
                        f"přesahuje limit {preview_limit:,} bodů. Export GeoJSON zachovává všechny souřadnice.").replace(",", " ")
                records.append({**record, "state": "preview_limited", "note": note})
            else:
                note = "Geometrie je zobrazena v mapě." if preview_limit is not None else "Geometrie je součástí podkladů."
                records.append({**record, "state": "available", "note": note})
        except (ValueError, TypeError, KeyError, OverflowError):
            records.append({**record, "state": "invalid", "note": "Geometrie je dodána, ale její formát nebo souřadnice nejsou použitelné. Je nutné ji opravit."})
    return records


def _usable_objects(case):
    return [(r["object"], r["kind"], r["groups"]) for r in _geometry_records(case) if r["state"] == "available"]


def _geometry_summary(records):
    if any(r["state"] == "preview_limited" for r in records):
        return "Geometrie je součástí podkladů, její rozsah ale přesahuje limit HTML náhledu. Export GeoJSON ji zachovává v plném rozsahu."
    if any(r["state"] == "invalid" for r in records):
        return "Dodanou geometrii nelze zobrazit kvůli formátu nebo souřadnicím. Mapový překryv nebyl vyhodnocen."
    return "Geometrie zatím není doložena. Mapový překryv nebyl vyhodnocen."


def _object_detail(obj):
    parts = [OBJECT_TYPES.get(obj.get("type"), "Objekt")]
    parcel = obj.get("parcel") or {}
    if parcel.get("number"):
        prefix = "st. " if parcel.get("series") == "building" else ""
        parts.append(prefix + str(parcel["number"]))
    cadastral = obj.get("cadastral_area") or {}
    if cadastral.get("name"):
        parts.append("k. ú. " + str(cadastral["name"]))
    if cadastral.get("code"):
        parts.append("kód k. ú. " + str(cadastral["code"]))
    if obj.get("registry_id"):
        parts.append("ID v registru " + str(obj["registry_id"]))
    if obj.get("address"):
        parts.append(str(obj["address"]))
    return " · ".join(parts)


def _map(case):
    records = _geometry_records(case, MAP_PREVIEW_POINT_LIMIT)
    usable = [(r["object"], r["kind"], r["groups"]) for r in records if r["state"] == "available"]
    rows = "".join(
        f'<li data-geometry-state="{r["state"]}" id="{_anchor("object-info",r["object"].get("id"))}">'
        f'<strong>{_e(r["object"].get("label",r["object"].get("id")))}</strong>'
        f'<span>{_e(_object_detail(r["object"]))}</span><span>{_e(r["note"])}</span></li>'
        for r in records
    )
    if not usable:
        return f'<section class="identity-card" id="mapa" aria-labelledby="map-title"><div class="section-eyebrow">01 / Místo</div><h2 id="map-title">Vymezení nemovitosti</h2><p class="muted">{_e(_geometry_summary(records))}</p><ul class="identity-list">{rows}</ul></section>'
    positions = [p for _, _, groups in usable for group in groups for line in group for p in line]
    latitude = sum(p[1] for p in positions) / len(positions)
    coslat = max(abs(math.cos(math.radians(latitude))), 0.01)
    factor = 111319.49079327358
    project = lambda p: (p[0] * factor * coslat, -p[1] * factor)
    world = [project(p) for p in positions]
    minx, maxx = min(p[0] for p in world), max(p[0] for p in world)
    miny, maxy = min(p[1] for p in world), max(p[1] for p in world)
    width, height = max(maxx-minx, 30.0), max(maxy-miny, 30.0)
    scale = min(790 / width, 420 / height)
    cx, cy = (minx+maxx)/2, (miny+maxy)/2
    def xy(p):
        x, y = project(p)
        return (450+(x-cx)*scale, 270+(y-cy)*scale)
    shapes, buttons = [], []
    for i, (obj, kind, groups) in enumerate(usable):
        oid = _anchor("object", obj.get("id", i))
        label, detail = obj.get("label", "Objekt"), _object_detail(obj)
        shape = []
        points = []
        for group in groups:
            if kind in {"Point", "MultiPoint"}:
                x, y = xy(group[0][0]); points.append((x,y))
                shape.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7"/>')
            else:
                commands = []
                for ring in group:
                    coords = [xy(p) for p in ring]; points.extend(coords)
                    commands.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x,y in coords) + (" Z" if kind in {"Polygon", "MultiPolygon"} else ""))
                shape.append(f'<path d="{" ".join(commands)}" fill-rule="evenodd"' + (' fill="none"' if "Line" in kind else '') + '/>')
        lx = (min(p[0] for p in points)+max(p[0] for p in points))/2
        ly = (min(p[1] for p in points)+max(p[1] for p in points))/2
        if len(usable) <= 15:
            shape.append(f'<text x="{lx:.2f}" y="{ly:.2f}" class="map-number">{i+1:02d}</text>')
        shapes.append(f'<g class="map-object map-color-{i%5}" data-object="{oid}" data-label="{_e(label)}" data-detail="{_e(detail)}" tabindex="0" role="button" aria-label="{_e(label)}" aria-pressed="false"><title>{_e(label)}</title>{"".join(shape)}</g>')
        buttons.append(f'<button type="button" class="object-key" data-select-object="{oid}" aria-pressed="false"><span class="object-number map-color-{i%5}">{i+1:02d}</span><span>{_e(label)}</span></button>')
    synthetic = case.get("case", {}).get("mode") == "synthetic"
    caption = "Modelová geometrie. Nejde o skutečnou parcelní mapu ani zjištění o konkrétní nemovitosti." if synthetic else "Geometrie z podkladů případu. Orientační zobrazení bez podkladových dlaždic; nenahrazuje vytyčení hranic."
    notes = list(dict.fromkeys(str(o.get("geometry_note")) for o, _, _ in usable if o.get("geometry_note")))
    source_names = {str(s.get("id")): s.get("provider") or s.get("title") for s in case.get("sources", [])}
    source_ids = list(dict.fromkeys(str(s) for o,_,_ in usable for s in o.get("source_ids", [])))
    citations = " · ".join(f'<a href="#{_anchor("source", s)}">{_e(source_names.get(s, s))}</a>' for s in source_ids)
    # The scale bar is approximate, based on the local equirectangular projection.
    maximum_m = 140 / scale
    exponent = 10 ** math.floor(math.log10(maximum_m))
    metres = max(v*exponent for v in (0.1,0.2,0.5,1,2,5) if v*exponent <= maximum_m)
    pixels = metres * scale
    scale_label = f"{metres/1000:g} km" if metres >= 1000 else f"{metres:g} m"
    return f'''<section class="map-card" id="mapa" aria-labelledby="map-title">
      <div class="card-heading"><div><div class="section-eyebrow">01 / Místo</div><h2 id="map-title">Nemovitost v prostoru</h2></div><span class="map-type">{'Modelová mapa' if synthetic else 'Geometrie objektů'}</span></div>
      <div class="map-stage"><svg id="property-map" viewBox="0 0 900 540" role="group" aria-label="Mapa objektů. Objekty lze vybrat klávesnicí nebo v seznamu pod mapou." xmlns="http://www.w3.org/2000/svg">
      <defs><pattern id="map-grid" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M36 0H0V36" fill="none" stroke="#d8ded8" stroke-width=".7"/></pattern></defs>
      <rect width="900" height="540" fill="url(#map-grid)"/><g id="map-features">{"".join(shapes)}</g>
      <g class="north-mark" transform="translate(846,45)"><path d="M0 8L-8 30L0 25L8 30Z"/><text x="0" y="0">S</text></g>
      <g class="map-scale" transform="translate(26,502)"><path d="M0 -5V0H{pixels:.2f}V-5"/><text x="0" y="19">Přibližně {scale_label} · výchozí výřez</text></g>
      </svg><div class="map-controls" aria-label="Ovládání mapy"><button type="button" data-map-action="in" aria-label="Přiblížit mapu">+</button><button type="button" data-map-action="out" aria-label="Oddálit mapu">−</button><button type="button" data-map-action="reset" aria-label="Obnovit výřez mapy">↺</button></div>
      </div>
      <div class="object-keys">{"".join(buttons)}</div><div class="map-selection" aria-live="polite"><strong id="map-selected-title">Vyber objekt v mapě</strong><span id="map-selected-detail">Čísla propojují geometrii se seznamem objektů.</span></div>
      <p class="map-caption">{_e(caption)}{' '+_e(' '.join(notes)) if notes else ''}</p>{'<p class="map-sources">Podklady: '+citations+'</p>' if citations else ''}
      <div class="map-caption object-inventory"><h3>Úplný soupis objektů</h3><ul class="identity-list">{rows}</ul></div>
    </section>'''


def _evidence(item, sources, documents):
    sid, did = item.get("source_id"), item.get("document_id")
    source = sources.get(sid, {}) if sid else documents.get(did, {})
    anchor = _anchor("source" if sid else "document", sid or did)
    title = source.get("title", "Podklad není uveden")
    quote = f'<blockquote>{_e(item.get("quote"))}</blockquote>' if item.get("quote") else ""
    date = f'<span class="evidence-date">Ověřeno {_e(_date(item.get("observed_at")))}</span>' if item.get("observed_at") else ""
    return f'<div class="evidence-item" id="{_anchor("evidence", item.get("id"))}"><div class="evidence-source"><a href="#{anchor}">{_e(title)}</a>{date}</div><p class="locator">{_e(_locator(item.get("locator")))}</p>{quote}</div>'


def _finding(item, index, evidence, sources, documents, objects):
    status = item.get("status") if item.get("status") in STATUS else "unverified"
    severity = item.get("severity") if item.get("severity") in SEVERITY else "info"
    topic = str(item.get("topic", ""))
    title = item.get("title", "Nález")
    evs = [evidence[e] for e in item.get("evidence_ids", []) if e in evidence]
    # Evidence may support several findings: keep unique anchors in the global evidence register.
    evlinks = "".join(f'<li><a href="#{_anchor("evidence", e.get("id"))}">{_e((sources.get(e.get("source_id")) or documents.get(e.get("document_id")) or {}).get("title", "Podklad"))}</a><span>{_e(_locator(e.get("locator")))}</span>{"<blockquote>"+_e(e.get("quote"))+"</blockquote>" if e.get("quote") else ""}</li>' for e in evs)
    evidence_panel = f'<details class="evidence-details"><summary>Důkazy a podklady <span>{len(evs):02d}</span></summary><ol>{evlinks}</ol></details>' if evs else '<p class="no-evidence">Závěr zatím nemá přiřazený důkaz.</p>'
    labels = [objects[o].get("label", o) for o in item.get("object_ids", []) if o in objects]
    related = '<p class="related-objects">'+_e(" · ".join(labels))+'</p>' if labels else ''
    nxt = f'<div class="next-step"><span>Další krok</span><p>{_e(item.get("next_step"))}</p></div>' if item.get("next_step") else ''
    search = " ".join(str(item.get(k,"")) for k in ("title","topic","summary","next_step")) + " " + " ".join(str(x) for x in labels)
    return f'''<article class="finding-card" id="{_anchor('finding',item.get('id'))}" data-status="{status}" data-topic="{_e(topic)}" data-search="{_e(search)}">
      <div class="finding-number">{index:02d}</div><div class="finding-body"><div class="finding-meta">{_badge(status)}<span class="severity severity-{severity}">{SEVERITY[severity]}</span><span class="topic">{_e(TOPICS.get(topic,topic))}</span></div>
      <h3>{_e(title)}</h3>{related}<p class="finding-summary">{_e(item.get('summary'))}</p>{evidence_panel}{nxt}</div></article>'''


def render_html(case: dict) -> str:
    """Return a complete UTF-8 HTML document with embedded CSS and JavaScript."""
    meta = case.get("case", {})
    css = (ASSETS / "report.css").read_text(encoding="utf-8")
    js = (ASSETS / "report.js").read_text(encoding="utf-8")
    script_hash = base64.b64encode(hashlib.sha256(js.encode("utf-8")).digest()).decode("ascii")
    csp = f"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{script_hash}'; img-src data:; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    sources = {s.get("id"): s for s in case.get("sources", [])}
    documents = {d.get("id"): d for d in case.get("documents", [])}
    evidence = {e.get("id"): e for e in case.get("evidence", [])}
    objects = {o.get("id"): o for o in case.get("objects", [])}
    findings = case.get("findings", [])
    counts = Counter(f.get("status") for f in findings)
    open_count = sum(counts[s] for s in ("missing","unverified","not_covered"))
    synthetic = meta.get("mode") == "synthetic"
    sharing = "Přehled ke sdílení" if meta.get("sharing") == "public-reviewed" else "Soukromý pracovní přehled"
    title = meta.get("title") or "Přehled nemovitosti"
    notice = '<div class="model-notice"><strong>Modelový příklad</strong><span>Fiktivní objekty, geometrie a nálezy ukazují postup. Nejde o prověření skutečné nemovitosti.</span></div>' if synthetic else ''
    summary = meta.get("summary") or "Případ je založený. Doplň podklady a zaznamenej, které otázky se podařilo ověřit."
    actionable = [f for f in findings if f.get("status") in {"missing", "conflict", "unverified", "not_covered"}]
    priority = {"high": 0, "medium": 1, "info": 2}
    top_items = sorted(actionable, key=lambda f: priority.get(f.get("severity"), 2))[:3]
    attention = "".join(f'<li><a href="#{_anchor("finding", f.get("id"))}">{_e(f.get("title"))}</a><span>{_e(STATUS.get(f.get("status"),"Neověřeno"))}</span></li>' for f in top_items)
    attention = attention or '<li><span>Nejdřív ověř identitu objektu a rozsah dostupných podkladů.</span></li>'
    topic_values = sorted(set(str(f.get("topic", "")) for f in findings if f.get("topic")))
    options = ''.join(f'<option value="{_e(t)}">{_e(TOPICS.get(t,t))}</option>' for t in topic_values)
    filter_buttons = '<button type="button" class="filter active" data-status-filter="all" aria-pressed="true">Vše <span>'+str(len(findings))+'</span></button>'
    filter_buttons += ''.join(f'<button type="button" class="filter" data-status-filter="{s}" aria-pressed="false">{label} <span>{counts[s]}</span></button>' for s,label in STATUS.items() if counts[s])
    cards = ''.join(_finding(f,i,evidence,sources,documents,objects) for i,f in enumerate(findings,1)) or '<div class="empty-state"><h3>Nálezy zatím nejsou zapsané</h3><p>Vyber konkrétní otázku, otevři příslušný podklad a zaznamenej výsledek s citací.</p></div>'
    next_cards=[]
    for i,item in enumerate(case.get("next_documents", []),1):
        status = 'Doručeno' if item.get('status')=='received' else 'K získání'
        url = _link(item.get('source_url'), 'Kde dokument získat', 'document-link') if _url(item.get('source_url')) else ''
        relation = f'<a class="related-finding" href="#{_anchor("finding",item.get("for_finding"))}">Související nález ↑</a>' if item.get("for_finding") else ''
        next_cards.append(f'<article class="request-card"><div class="request-top"><span class="request-number">{i:02d}</span><span class="request-status">{status}</span></div><h3>{_e(item.get("title"))}</h3><p>{_e(item.get("reason"))}</p><div class="request-links">{url}{relation}</div></article>')
    next_section = f'<section class="section" id="dalsi-kroky"><div class="section-heading"><div><div class="section-eyebrow">03 / Pokračování</div><h2>Co získat jako další</h2></div><p>Každý požadavek má konkrétní důvod.</p></div><div class="request-grid">{"".join(next_cards)}</div></section>' if next_cards else ''
    evidence_rows=''.join(_evidence(e,sources,documents) for e in case.get('evidence',[]))
    evidence_section=f'<section class="section evidence-register" id="dukazy"><div class="section-heading"><div><div class="section-eyebrow">04 / Důkazy</div><h2>O co se přehled opírá</h2></div><p>{len(evidence)} záznamů s lokátorem</p></div>{evidence_rows}</section>' if evidence_rows else ''
    source_rows=[]
    for s in case.get('sources',[]):
        data_date = f'<span>Stav dat: {_e(_date(s.get("data_date")))}</span>' if s.get('data_date') else '<span>Datace podkladu neuvedena</span>'
        source_rows.append(f'<article class="source-card" id="{_anchor("source",s.get("id"))}"><div class="source-provider">{_e(s.get("provider") or "Zdroj")}</div><h3>{_link(s.get("url"),s.get("title"))}</h3><p>{_e(s.get("scope"))}</p><div class="source-dates"><span>Otevřeno: {_e(_date(s.get("accessed_at")))}</span>{data_date}</div></article>')
    doc_rows=[]
    complete={'complete':'Úplný podle evidence případu','partial':'Částečný dokument','unknown':'Úplnost neověřena'}
    seals={'not_checked':'Pečeť neověřena','present_unverified':'Pečeť přítomná, neověřena','verified':'Pečeť ověřena','invalid':'Neplatná pečeť'}
    for d in case.get('documents',[]):
        doc_rows.append(f'<article class="source-card document-card" id="{_anchor("document",d.get("id"))}"><div class="source-provider">Dodaný dokument · {_e(d.get("kind") or "druh neuveden")}</div><h3>{_e(d.get("title"))}</h3><p>{_e(complete.get(d.get("completeness"),"Úplnost neověřena"))} · {_e(seals.get(d.get("seal_status"),"Pečeť neověřena"))}</p><div class="source-dates"><span>Stav evidence: {_e(_date(d.get("register_state_at")))}</span><span>Vydáno: {_e(_date(d.get("issued_at")))}</span><span>Stran: {_e(d.get("pages", "neuvedeno"))}</span></div></article>')
    source_section=f'<section class="section" id="zdroje"><div class="section-heading"><div><div class="section-eyebrow">05 / Podklady</div><h2>Zdroje a dokumenty</h2></div><p>Odkazy se otevírají až po kliknutí.</p></div><div class="source-grid">{"".join(source_rows+doc_rows)}</div></section>' if source_rows or doc_rows else ''
    right_rows=[]
    for right in case.get('rights',[]):
        benefits=', '.join(str(objects.get(k,{}).get('label',k)) for k in right.get('beneficiary_object_ids',[])) or 'neuvedeno'
        burdens=', '.join(str(objects.get(k,{}).get('label',k)) for k in right.get('burdened_object_ids',[])) or 'neuvedeno'
        share=right.get('share') or {}
        fraction=f'<span class="share">Podíl {_e(share.get("numerator"))}/{_e(share.get("denominator"))}</span>' if share else ''
        refs=''.join(f'<a href="#{_anchor("evidence",e)}">Důkaz {i+1}</a> ' for i,e in enumerate(right.get('evidence_ids',[])))
        right_rows.append(f'<article class="right-card"><h3>{_e(right.get("type"))}</h3><p>{_e(right.get("description"))}</p><dl><div><dt>Ve prospěch</dt><dd>{_e(benefits)}</dd></div><div><dt>Zatěžuje</dt><dd>{_e(burdens)}</dd></div></dl>{fraction}<div class="right-evidence">{refs}</div></article>')
    rights_section=f'<section class="section" id="vztahy"><div class="section-heading"><div><div class="section-eyebrow">Právní vazby</div><h2>Práva mezi objekty</h2></div></div><div class="rights-grid">{"".join(right_rows)}</div></section>' if right_rows else ''
    logs=[]
    loglabels={'ok':'Zpracováno','empty':'Prázdná odpověď','blocked':'Přístup zablokován','error':'Chyba zdroje','planned':'Naplánováno'}
    for l in case.get('research_log',[]):
        logs.append(f'<li><time>{_e(_date(l.get("at")))}</time><div><strong>{_e(loglabels.get(l.get("status"),l.get("status")))}</strong><p>{_e(l.get("query"))}</p><span>{_e(l.get("note"))}</span></div></li>')
    log_section=f'<details class="research-log"><summary>Postup a rozsah dohledávání <span>{len(logs)} kroků</span></summary><ol>{"".join(logs)}</ol></details>' if logs else ''
    source_nav='<a href="#zdroje">Podklady</a>' if source_section else ''
    next_nav='<a href="#dalsi-kroky">Další kroky</a>' if next_section else ''
    scope=f'<p class="scope-note"><strong>Rozsah prověření</strong> {_e(meta.get("scope_note"))}</p>' if meta.get('scope_note') else ''
    return f'''<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{_e(csp)}"><meta name="color-scheme" content="light"><title>{_e(title)} — Katastr a souvislosti</title><style>{css}</style></head><body>
    <a class="skip-link" href="#obsah">Přejít k přehledu</a><header class="masthead"><a class="brand" href="#prehled" aria-label="Katastr a souvislosti, úvod"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M3 6L15 3L32 9L30 28L17 33L4 26Z M15 3L17 33 M4 18L31 17"/></svg><span>KATASTR<span>A SOUVISLOSTI</span></span></a><div class="header-actions"><span class="sharing-label">{sharing}</span><button class="print-button" id="print-report" type="button">Vytisknout / PDF <span aria-hidden="true">↗</span></button></div></header>
    <nav class="section-nav" aria-label="Sekce přehledu"><a href="#prehled">Přehled</a><a href="#mapa">Nemovitost</a><a href="#nalezy">Nálezy</a>{next_nav}{source_nav}</nav>
    <main id="obsah"><section class="hero" id="prehled">{notice}<div class="hero-eyebrow">PŘEHLED NEMOVITOSTI <span>•</span> {_e(meta.get('locality') or 'Místo k upřesnění')}</div><div class="hero-title-row"><h1>{_e(title)}</h1><div class="report-date"><span>Datum přehledu</span><strong>{_e(_date(meta.get('as_of')))}</strong></div></div><div class="hero-context"><span>{_e(meta.get('purpose') or 'Účel k upřesnění')}</span>{'<span>'+_e(meta.get('region'))+'</span>' if meta.get('region') else ''}</div><p class="hero-summary">{_e(summary)}</p>{scope}
    <div class="summary-stats" aria-label="Počty nálezů podle stavu"><div><strong>{counts['supported']:02d}</strong><span>Doložené nálezy</span></div><div><strong>{counts['conflict']:02d}</strong><span>Rozpory v podkladech</span></div><div><strong>{open_count:02d}</strong><span>Otevřené otázky</span></div><p>Počty popisují stav rešerše.<br>Nejde o hodnocení bezpečnosti nemovitosti.</p></div></section>
    <div class="overview-grid">{_map(case)}<aside class="attention-card"><div class="section-eyebrow">Před dalším rozhodnutím</div><h2>Čemu se věnovat<br>jako první</h2><ol>{attention}</ol><div class="attention-foot"><span class="small-label">Práce s důkazy</span><p>U každého nálezu rozlišujeme přečtený údaj, jeho význam a to, co ještě zbývá doložit.</p></div></aside></div>
    <section class="section" id="nalezy"><div class="section-heading"><div><div class="section-eyebrow">02 / Zjištění</div><h2>Nálezy a otevřené otázky</h2></div><p id="finding-count" aria-live="polite">{len(findings)} nálezů v přehledu</p></div><div class="filter-bar"><div class="filter-buttons" aria-label="Filtrovat podle stavu">{filter_buttons}</div><div class="search-row"><label class="search-field"><span>Hledat v nálezech</span><input id="finding-search" type="search" placeholder="Např. přístup, parcela, voda…" autocomplete="off"></label><label class="topic-field"><span>Oblast</span><select id="topic-filter"><option value="all">Všechny oblasti</option>{options}</select></label></div></div><div class="findings">{cards}</div><p id="no-filter-results" class="empty-state" hidden>Tomuto filtru neodpovídá žádný nález. Zkus jiný stav, oblast nebo hledaný výraz.</p></section>
    {rights_section}{next_section}{evidence_section}{source_section}{log_section}
    </main><footer class="page-footer"><div><strong>Katastr a souvislosti</strong><span>Doložené údaje. Viditelné mezery. Konkrétní další krok.</span></div><p>{_e(case.get('schema_version','property-case/1.0'))} · Sestaveno {_e(_date(meta.get('created_at')))}<br>Podklady mohou popisovat různé časové stavy; rozhodující datace je uvedena u každého z nich.</p></footer><script>{js}</script></body></html>'''


def render_markdown(case: dict) -> str:
    """Readable textual export with the same findings, sources and uncertainties."""
    c = case.get('case', {})
    lines = [f"# {_md(c.get('title') or 'Přehled nemovitosti')}", "", "**Katastr a souvislosti**", ""]
    if c.get('mode') == 'synthetic':
        lines += ["> **MODELOVÝ PŘÍKLAD.** Fiktivní objekty, geometrie a nálezy; nejde o prověření skutečné nemovitosti.", ""]
    lines += [f"**Místo:** {_md(c.get('locality'))}  ", f"**Účel:** {_md(c.get('purpose'))}  ", f"**Datum přehledu:** {_md(_date(c.get('as_of')))}  ", f"**Sdílení:** {'Přehled ke sdílení' if c.get('sharing')=='public-reviewed' else 'Soukromý pracovní přehled'}", "", _md(c.get('summary')), ""]
    if c.get('scope_note'):
        lines += [f"**Rozsah prověření:** {_md(c['scope_note'])}", ""]
    lines += ["## Nemovitost", ""]
    geometry_records = _geometry_records(case)
    for record in geometry_records:
        o = record['object']
        lines += [f"- **{_md(o.get('label'))}** — {_md(_object_detail(o))}", f"  {_md(record['note'])}"]
        if o.get('geometry_note'):
            lines += [f"  {_md(o['geometry_note'])}"]
    if not any(record['state'] == 'available' for record in geometry_records):
        lines += ["", _md(_geometry_summary(geometry_records))]
    lines += ["", "## Nálezy", ""]
    for i,f in enumerate(case.get('findings',[]),1):
        lines += [f"### {i}. {_md(f.get('title'))}", "", f"**{STATUS.get(f.get('status'),'Neověřeno')} · {SEVERITY.get(f.get('severity'),'Souvislost')}**", "", _md(f.get('summary')), ""]
        if f.get('evidence_ids'):
            lines += ["Důkazy: " + ", ".join(f"[{_md(e)}](#{_anchor('evidence',e)})" for e in f['evidence_ids']), ""]
        else:
            lines += ["Závěr zatím nemá přiřazený důkaz.", ""]
        if f.get('next_step'):
            lines += [f"**Další krok:** {_md(f['next_step'])}", ""]
    if case.get('rights'):
        lines += ["## Právní vazby", ""]
        objects = {o.get('id'): o for o in case.get('objects',[])}
        for r in case['rights']:
            ben=', '.join(str(objects.get(o,{}).get('label',o)) for o in r.get('beneficiary_object_ids',[])) or 'neuvedeno'
            bur=', '.join(str(objects.get(o,{}).get('label',o)) for o in r.get('burdened_object_ids',[])) or 'neuvedeno'
            lines += [f"### {_md(r.get('type'))}", "", _md(r.get('description')), "", f"- Ve prospěch: {_md(ben)}", f"- Zatěžuje: {_md(bur)}"]
            if r.get('share'):
                lines += [f"- Podíl: {_md(r['share'].get('numerator'))}/{_md(r['share'].get('denominator'))}"]
            lines += ["Důkazy: " + ", ".join(_md(e) for e in r.get('evidence_ids',[])), ""]
    if case.get('next_documents'):
        lines += ["## Co získat jako další", ""]
        for n in case['next_documents']:
            lines += [f"### {_md(n.get('title'))}", "", _md(n.get('reason')), "", f"Stav: {'doručeno' if n.get('status')=='received' else 'k získání'}", ""]
            u = _url(n.get('source_url'))
            if u:
                lines += [f"[Oficiální místo získání](<{u}>)", ""]
    if case.get('evidence'):
        lines += ["## Důkazy", ""]
        for e in case['evidence']:
            lines += [f'<a id="{_anchor("evidence",e.get("id"))}"></a>', f"### {_md(e.get('id'))}", "", f"Podklad: {_md(e.get('source_id') or e.get('document_id'))} · {_md(_locator(e.get('locator')))}", ""]
            if e.get('quote'):
                lines += ["> " + _md(e['quote']), ""]
            if e.get('observed_at'):
                lines += ["Ověřeno: "+_md(_date(e['observed_at'])), ""]
    if case.get('sources'):
        lines += ["## Zdroje", ""]
        for s in case['sources']:
            u=_url(s.get('url')); title=_md(s.get('title'))
            lines += [f"### {_md(s.get('id'))} — {title}", "", f"[{title}](<{u}>)" if u else title, "", _md(s.get('scope')), "", f"Poskytovatel: {_md(s.get('provider'))} · Otevřeno: {_md(_date(s.get('accessed_at')))} · Stav dat: {_md(_date(s.get('data_date')))}", ""]
    if case.get('documents'):
        lines += ["## Dodané dokumenty", ""]
        for d in case['documents']:
            lines += [f"### {_md(d.get('id'))} — {_md(d.get('title'))}", "", f"Druh: {_md(d.get('kind'))} · Stran: {_md(d.get('pages'))} · Stav evidence: {_md(_date(d.get('register_state_at')))} · Vydáno: {_md(_date(d.get('issued_at')))}", "", f"Úplnost: {_md(d.get('completeness'))} · Pečeť: {_md(d.get('seal_status'))}", ""]
    if case.get('research_log'):
        lines += ["## Postup dohledávání", ""]
        for l in case['research_log']:
            lines += [f"- {_md(_date(l.get('at')))} · {_md(l.get('status'))} · {_md(l.get('query'))}. {_md(l.get('note'))}"]
        lines += [""]
    lines += ["---", "", "Počty nálezů popisují stav rešerše, nikoli bezpečnost nemovitosti. Datace jednotlivých podkladů se může lišit.", ""]
    return "\n".join(lines)


def export_geojson(case: dict) -> dict:
    """Export geometry and object labels only, never documents or personal rights."""
    features=[]
    for obj,_,_ in _usable_objects(case):
        properties={k:copy.deepcopy(obj[k]) for k in ('id','label','type','registry_id','geometry_note','source_ids') if k in obj}
        if obj.get('cadastral_area'):
            properties['cadastral_area']=copy.deepcopy(obj['cadastral_area'])
        if obj.get('parcel'):
            properties['parcel']=copy.deepcopy(obj['parcel'])
        features.append({'type':'Feature','id':str(obj.get('id','')),'geometry':copy.deepcopy(obj['geometry']),'properties':properties})
    meta=case.get('case',{})
    return {'type':'FeatureCollection','features':features,'metadata':{'case_id':meta.get('id'),'mode':meta.get('mode'),'as_of':meta.get('as_of'),'crs':'WGS84 / longitude, latitude','note':'Modelová geometrie, nikoli skutečná parcelní mapa.' if meta.get('mode')=='synthetic' else 'Geometrie podkladů případu; přesnost posuzuj podle původního zdroje.'}}
