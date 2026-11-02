"""Offline report behavior, geometry, evidence and adversarial content tests."""
import base64
import copy
import hashlib
from html.parser import HTMLParser
import math
import os
from pathlib import Path
import re
import sys
import unittest

SKILL = Path(os.environ.get("KATASTR_SKILL_ROOT", Path(__file__).resolve().parents[1] / "skills/katastr-nemovitosti"))
sys.path.insert(0, str(SKILL / "scripts"))
import report


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.ids = []
        self.anchors = []
        self.resources = []
        self.events = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.anchors.append(attrs["href"])
        if attrs.get("src") or (tag == "link" and attrs.get("href")):
            self.resources.append(attrs.get("src") or attrs.get("href"))
        self.events += [k for k in attrs if k.startswith("on")]


def sample():
    return {
        "schema_version": "property-case/1.0",
        "case": {"id":"demo", "title":"Dům a přístupová cesta", "purpose":"Prověřit dostupné podklady před koupí",
            "locality":"Modelová obec", "region":"Česká republika", "created_at":"2026-11-02T10:00:00Z", "as_of":"2026-10-29T12:00:00Z", "mode":"synthetic", "summary":"Přístup vyžaduje doplnění listiny.", "scope_note":"Fiktivní případ pro ukázku postupu.", "sharing":"private"},
        "objects":[
            {"id":"p1","type":"parcel","label":"Zahrada","cadastral_area":{"code":"999999","name":"Modelové území"},"parcel":{"number":"123/4","series":"land"},"geometry":{"type":"Polygon","coordinates":[[[16.61,49.20],[16.611,49.20],[16.611,49.2008],[16.61,49.2008],[16.61,49.20]]]},"geometry_note":"Fiktivní geometrie.","source_ids":["s1"]},
            {"id":"p2","type":"parcel","label":"Dům","parcel":{"number":"22","series":"building"},"geometry":{"type":"Point","coordinates":[16.6105,49.2004]},"source_ids":["s1"]},
        ],
        "sources":[{"id":"s1","title":"Modelový mapový podklad","url":"https://services.cuzk.gov.cz/","provider":"ČÚZK – odkaz pro orientaci","accessed_at":"2026-11-02T10:00:00Z","scope":"Zdroj formátu, nikoli důkaz o skutečné parcele.","access":"public","public":True}],
        "documents":[{"id":"d1","title":"Modelový částečný výpis","kind":"LV","sha256":"a"*64,"pages":1,"register_state_at":"2026-10-29T12:00:00Z","issued_at":"2026-10-30T12:00:00Z","imported_at":"2026-11-02T10:00:00Z","completeness":"partial","seal_status":"present_unverified","public":False,"inspection":{"path":"/secret/original.pdf"}}],
        "evidence":[{"id":"e1","source_id":"s1","locator":{"note":"modelová plocha"},"quote":"Vzor podkladu.","observed_at":"2026-11-02T10:00:00Z","public":True},{"id":"e2","document_id":"d1","locator":{"page":1,"section":"C","attachment":"listina.pdf"},"quote":"Služebnost průchodu.","public":False}],
        "findings":[{"id":"f1","title":"Přístup vyžaduje doplnění","topic":"access","status":"missing","severity":"high","summary":"Zatím je doložen pouze tvar cesty.","object_ids":["p1"],"evidence_ids":["e1"],"next_step":"Získat listinu s rozsahem oprávnění.","public":True},{"id":"f2","title":"Identita v podkladu","topic":"identity","status":"supported","severity":"info","summary":"V modelovém podkladu je odpovídající označení.","object_ids":["p2"],"evidence_ids":["e1","e2"],"next_step":"","public":True}],
        "rights":[{"id":"r1","type":"Služebnost","beneficiary_object_ids":["p2"],"burdened_object_ids":["p1"],"share":{"numerator":1,"denominator":8},"description":"Modelová vazba.","evidence_ids":["e2"],"public":False}],
        "next_documents":[{"id":"n1","title":"Podkladová listina","reason":"Určí rozsah práva.","source_url":"https://dpn.cuzk.gov.cz/","for_finding":"f1","priority":"high","status":"needed","public":True}],
        "research_log":[{"at":"2026-11-02T10:00:00Z","source_id":"s1","query":"Modelový dotaz","status":"planned","note":"Živá parcela nebyla zkoumána."}],
    }


class ReportTests(unittest.TestCase):
    def test_self_contained_czech_document_has_no_external_resources(self):
        text=report.render_html(sample())
        dom=Document(text)
        self.assertIn('<html lang="cs">',text)
        self.assertEqual(dom.resources,[])
        self.assertEqual(dom.events,[])
        self.assertEqual(sum(t=='script' for t,_ in dom.tags),1)
        self.assertIn("connect-src &#x27;none&#x27;",text)
        self.assertIn("@media print",text)

    def test_csp_exact_script_hash(self):
        text=report.render_html(sample())
        script=re.search(r"<script>(.*?)</script>",text,re.S).group(1)
        digest=base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertIn("sha256-"+digest,text)

    def test_xss_in_narratives_attributes_and_ids_stays_text(self):
        case=sample()
        payload='\"><img src=x onerror=alert(1)><script>alert(2)</script>&'
        case['case']['title']=payload
        case['case']['summary']=payload
        case['objects'][0]['label']=payload
        case['findings'][0]['title']=payload
        case['findings'][0]['id']=payload
        case['findings'][0]['topic']=payload
        case['next_documents'][0]['for_finding']=payload
        case['evidence'][0]['quote']=payload
        case['evidence'][0]['locator']['note']=payload
        text=report.render_html(case)
        dom=Document(text)
        self.assertFalse(any(t=='img' for t,_ in dom.tags))
        self.assertEqual(sum(t=='script' for t,_ in dom.tags),1)
        self.assertFalse(dom.events)
        self.assertIn('&lt;img',text)
        self.assertNotIn('<script>alert(2)',text)

    def test_unsafe_urls_are_not_links(self):
        for url in ['javascript:alert(1)','data:text/html,<b>X</b>','file:///etc/passwd','//evil.example/x',' https://evil.example','https://a\n.example','https://user:secret@example.org/','https://example.org/\\x','https://example.org/<x>']:
            with self.subTest(url=url):
                case=sample()
                case['sources'][0]['url']=url
                case['next_documents'][0]['source_url']=url
                dom=Document(report.render_html(case))
                self.assertNotIn(url,dom.anchors)
                self.assertTrue(all(a.startswith('#') or a.startswith('https://') for a in dom.anchors))

    def test_external_links_have_safe_rel(self):
        dom=Document(report.render_html(sample()))
        for tag,attrs in dom.tags:
            if tag=='a' and attrs.get('href','').startswith('https://'):
                self.assertEqual(attrs.get('rel'),'noopener noreferrer')

    def test_all_internal_anchors_resolve_once(self):
        dom=Document(report.render_html(sample()))
        self.assertEqual(len(dom.ids),len(set(dom.ids)))
        for ref in dom.anchors:
            if ref.startswith('#'):
                self.assertIn(ref[1:],dom.ids,ref)

    def test_private_document_path_and_inspection_payload_not_exposed(self):
        case=sample()
        case['documents'][0]['inspection']['hidden_personal_data']='DO-NOT-RENDER'
        text=report.render_html(case)
        self.assertNotIn('/secret/original.pdf',text)
        self.assertNotIn('DO-NOT-RENDER',text)
        self.assertIn('Modelový částečný výpis',text)

    def test_model_and_private_notices_are_prominent(self):
        text=report.render_html(sample())
        self.assertIn('class="model-notice"',text)
        self.assertIn('Soukromý pracovní přehled',text)
        self.assertIn('Modelová geometrie. Nejde o skutečnou parcelní mapu',text)
        self.assertLess(text.index('class="model-notice"'),text.index('class="hero-title-row"'))

    def test_research_case_uses_no_synthetic_label(self):
        case=sample();case['case']['mode']='research';case['case']['sharing']='public-reviewed'
        text=report.render_html(case)
        self.assertNotIn('<strong>Modelový příklad</strong>',text)
        self.assertIn('Přehled ke sdílení',text)

    def test_evidence_presents_page_section_attachment_and_dates(self):
        text=report.render_html(sample())
        self.assertIn('strana 1 · oddíl C · příloha listina.pdf',text)
        self.assertIn('Stav evidence: 29. 10. 2026',text)
        self.assertIn('Vydáno: 30. 10. 2026',text)
        self.assertIn('Pečeť přítomná, neověřena',text)
        self.assertIn('Částečný dokument',text)

    def test_no_geometry_has_compact_identity_not_empty_map(self):
        case=sample()
        for obj in case['objects']:obj['geometry']=None
        text=report.render_html(case)
        self.assertNotIn('id="property-map"',text)
        self.assertIn('Geometrie zatím není doložena',text)
        self.assertIn('class="identity-list"',text)

    def test_mixed_geometry_keeps_every_object_with_explicit_geometry_state(self):
        case=sample()
        case['objects'][1]['label']='Nezmapovaná související jednotka'
        case['objects'][1]['geometry']=None
        text=report.render_html(case)
        dom=Document(text)
        self.assertIn('id="property-map"',text)
        inventory=[attrs for tag,attrs in dom.tags if 'data-geometry-state' in attrs]
        self.assertEqual([row['data-geometry-state'] for row in inventory],['available','missing'])
        self.assertIn('Nezmapovaná související jednotka',text)
        self.assertIn('Geometrie není dodána; objekt není zobrazen v mapě.',text)
        self.assertIn('Geometrie je zobrazena v mapě.',text)
        markdown=report.render_markdown(case)
        self.assertIn('Nezmapovaná související jednotka',markdown)
        self.assertIn('Geometrie není dodána',markdown)

    def test_full_cadastral_and_registry_identity_in_visible_inventory_and_markdown(self):
        case=sample()
        case['objects'][0]['registry_id']='CZ-CP-123456789'
        text=report.render_html(case)
        inventory=re.search(r'<div class="map-caption object-inventory">(.*?)</div>',text,re.S).group(1)
        self.assertIn('kód k. ú. 999999',inventory)
        self.assertIn('ID v registru CZ-CP-123456789',inventory)
        self.assertIn('123/4',inventory)
        self.assertIn('st. 22',inventory)
        markdown=report.render_markdown(case)
        self.assertIn('999999',markdown)
        self.assertIn('CZ-CP-123456789',markdown)
        self.assertEqual(report.export_geojson(case)['features'][0]['properties']['registry_id'],'CZ-CP-123456789')

    def test_timestamps_preserve_time_precision_and_timezone_without_conversion(self):
        case=sample()
        case['documents'][0]['register_state_at']='2026-11-02T09:14:35.1200+01:00'
        case['documents'][0]['issued_at']='2026-11-02T13:02:07Z'
        text=report.render_html(case)
        self.assertIn('Stav evidence: 2. 11. 2026 · 09:14:35.1200 UTC+01:00',text)
        self.assertIn('Vydáno: 2. 11. 2026 · 13:02:07 UTC',text)
        markdown=report.render_markdown(case)
        self.assertIn('09:14:35',markdown)
        self.assertIn('UTC\\+01:00',markdown)
        self.assertIn('13:02:07 UTC',markdown)
        self.assertEqual(report._date('2026-11-02T08:04:03-03:30'),'2. 11. 2026 · 08:04:03 UTC-03:30')
        self.assertEqual(report._date('2026-11-02'),'2. 11. 2026')

    def test_case_date_is_labeled_as_report_date_not_all_evidence_state(self):
        text=report.render_html(sample())
        self.assertIn('<span>Datum přehledu</span>',text)
        self.assertNotIn('Rozhodný stav',text)
        markdown=report.render_markdown(sample())
        self.assertIn('**Datum přehledu:**',markdown)
        self.assertNotIn('Rozhodný stav',markdown)

    def test_large_valid_polygon_kept_in_geojson_and_explicit_preview_limit(self):
        case=sample()
        ring=[[16+0.01*math.cos(i*2*math.pi/20001),49+0.01*math.sin(i*2*math.pi/20001)] for i in range(20001)]
        ring.append(ring[0][:])
        case['objects'][0]['geometry']={'type':'Polygon','coordinates':[ring]}
        case['objects'][1]['geometry']=None
        text=report.render_html(case)
        self.assertNotIn('id="property-map"',text)
        self.assertIn('data-geometry-state="preview_limited"',text)
        self.assertIn('20 002 bodů',text)
        self.assertIn('přesahuje limit 20 000 bodů',text)
        self.assertNotIn('Geometrie zatím není doložena',text)
        exported=report.export_geojson(case)
        self.assertEqual(len(exported['features']),1)
        self.assertEqual(exported['features'][0]['geometry']['coordinates'][0],ring)
        self.assertEqual(len(exported['features'][0]['geometry']['coordinates'][0]),20002)
        self.assertNotIn('Geometrie zatím není doložena',report.render_markdown(case))

    def test_large_polygon_does_not_hide_when_another_object_has_small_geometry(self):
        case=sample()
        ring=[[16+0.01*math.cos(i*2*math.pi/20001),49+0.01*math.sin(i*2*math.pi/20001)] for i in range(20001)]
        ring.append(ring[0][:])
        case['objects'][0]['geometry']={'type':'Polygon','coordinates':[ring]}
        text=report.render_html(case)
        self.assertIn('id="property-map"',text)
        dom=Document(text)
        inventory=[attrs['data-geometry-state'] for tag,attrs in dom.tags if 'data-geometry-state' in attrs]
        self.assertEqual(inventory,['preview_limited','available'])
        self.assertEqual(len(report.export_geojson(case)['features']),2)

    def test_invalid_geometry_is_described_as_invalid_not_absent(self):
        case=sample()
        for obj in case['objects']:obj['geometry']={'type':'Point','coordinates':[-600000,-1100000]}
        text=report.render_html(case)
        self.assertIn('data-geometry-state="invalid"',text)
        self.assertIn('Dodanou geometrii nelze zobrazit',text)
        self.assertNotIn('Geometrie zatím není doložena',text)

    def test_invalid_geometry_is_omitted(self):
        for geometry in [{'type':'Point','coordinates':[math.inf,49]},{'type':'Point','coordinates':[16,91]},{'type':'Point','coordinates':[True,49]},{'type':'Polygon','coordinates':[[[16,49],[17,49],[17,50]]]},{'type':'LineString','coordinates':[[16,49]]}]:
            with self.subTest(geometry=geometry):
                case=sample();case['objects']=case['objects'][:1];case['objects'][0]['geometry']=geometry
                self.assertEqual(report.export_geojson(case)['features'],[])
                self.assertNotIn('id="property-map"',report.render_html(case))

    def test_polygon_holes_and_multiple_polygons_preserved(self):
        case=sample()
        rings=[[[16,49],[16.01,49],[16.01,49.01],[16,49.01],[16,49]],[[16.002,49.002],[16.003,49.002],[16.003,49.003],[16.002,49.003],[16.002,49.002]]]
        case['objects']=case['objects'][:1]
        case['objects'][0]['geometry']={'type':'MultiPolygon','coordinates':[rings]}
        text=report.render_html(case)
        self.assertIn('fill-rule="evenodd"',text)
        self.assertEqual(report.export_geojson(case)['features'][0]['geometry']['coordinates'][0],rings)

    def test_line_and_point_map_produce_finite_geometry(self):
        case=sample()
        case['objects'][0]['geometry']={'type':'MultiLineString','coordinates':[[[16,49],[16.01,49.01]],[[16.02,49.02],[16.03,49.03]]]}
        text=report.render_html(case)
        self.assertIn('fill="none"',text)
        self.assertIn('<circle',text)
        self.assertNotRegex(text,r'(?:nan|inf),')

    def test_map_controls_and_keyboard_semantics(self):
        dom=Document(report.render_html(sample()))
        map_objects=[a for t,a in dom.tags if 'map-object' in a.get('class','').split()]
        self.assertEqual(len(map_objects),2)
        for obj in map_objects:
            self.assertEqual(obj['tabindex'],'0')
            self.assertEqual(obj['role'],'button')
            self.assertIn('aria-label',obj)
        self.assertEqual(len([a for t,a in dom.tags if 'data-map-action' in a]),3)

    def test_supported_and_missing_filters_distinct(self):
        dom=Document(report.render_html(sample()))
        filters=[a.get('data-status-filter') for t,a in dom.tags if 'data-status-filter' in a]
        self.assertEqual(set(filters),{'all','supported','missing'})
        cards=[a for t,a in dom.tags if 'finding-card' in a.get('class','').split()]
        self.assertEqual([c['data-status'] for c in cards],['missing','supported'])

    def test_renderers_do_not_mutate_case(self):
        case=sample();before=copy.deepcopy(case)
        report.render_html(case);report.render_markdown(case);report.export_geojson(case)
        self.assertEqual(case,before)

    def test_geojson_is_copy_and_omits_legal_personal_records(self):
        case=sample()
        obj=report.export_geojson(case)
        self.assertEqual(obj['type'],'FeatureCollection')
        self.assertEqual(len(obj['features']),2)
        self.assertEqual(obj['metadata']['mode'],'synthetic')
        self.assertNotIn('rights',obj)
        self.assertNotIn('documents',obj)
        self.assertNotIn('address',obj['features'][0]['properties'])
        obj['features'][0]['geometry']['coordinates'][0][0][0]=0
        self.assertEqual(case['objects'][0]['geometry']['coordinates'][0][0][0],16.61)

    def test_empty_case_produces_usable_starter_report(self):
        case={"schema_version":"property-case/1.0","case":{"title":"Začátek"}}
        text=report.render_html(case)
        self.assertIn('Nálezy zatím nejsou zapsané',text)
        self.assertIn('Geometrie zatím není doložena',text)
        self.assertNotIn('id="zdroje"',text)
        self.assertNotIn('href="#zdroje"',text)
        self.assertEqual(report.export_geojson(case)['features'],[])

    def test_markdown_has_all_evidence_and_hard_cases(self):
        text=report.render_markdown(sample())
        self.assertIn('MODELOVÝ PŘÍKLAD',text)
        self.assertIn('## Právní vazby',text)
        self.assertIn('Podíl: 1/8',text)
        self.assertIn('## Důkazy',text)
        self.assertIn('## Dodané dokumenty',text)
        self.assertIn('partial',text)
        self.assertNotIn('/secret/original.pdf',text)

    def test_markdown_escapes_active_html_and_markdown_links(self):
        case=sample();case['case']['title']='[x](javascript:alert(1)) <script>alert(1)</script>'
        case['sources'][0]['url']='javascript:alert(1)'
        text=report.render_markdown(case)
        self.assertNotIn('<script>',text)
        self.assertNotIn('[x](javascript',text)
        self.assertIn('&lt;script&gt;',text)

    def test_all_statuses_have_clear_labels_no_overall_score(self):
        case=sample()
        case['findings']=[dict(case['findings'][0],id=s,status=s) for s in report.STATUS]
        text=report.render_html(case)
        for label in report.STATUS.values():self.assertIn(label,text)
        self.assertNotIn('87 %',text)
        self.assertIn('Nejde o hodnocení bezpečnosti nemovitosti',text)


if __name__ == '__main__':
    unittest.main()
