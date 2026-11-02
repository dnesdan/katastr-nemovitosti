"""Evidence integrity, malformed input, public exports and snapshot comparisons."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

SKILL = Path(os.environ.get("KATASTR_SKILL_ROOT", Path(__file__).resolve().parents[1] / "skills/katastr-nemovitosti"))
sys.path.insert(0, str(SKILL / "scripts"))
import case_model as model

try:
    import jsonschema
except ImportError:
    jsonschema = None


def complete_case():
    c=model.new_case("Prověření pozemku", "Modelová obec")
    c['case'].update(id='modelovy-pripad',mode='synthetic',as_of='2026-11-02')
    c['sources']=[{'id':'s1','title':'Veřejný podklad','url':'https://services.cuzk.gov.cz/','provider':'ČÚZK','accessed_at':'2026-11-02','scope':'Zdroj pro modelový postup.','access':'public','public':True}]
    c['objects']=[{'id':'p1','type':'parcel','label':'Modelová parcela','cadastral_area':{'code':'999999','name':'Modelové území'},'parcel':{'number':'123/4','series':'land'},'geometry':{'type':'Polygon','coordinates':[[[16,49],[16.01,49],[16.01,49.01],[16,49.01],[16,49]]]},'geometry_note':'Modelová geometrie.','source_ids':['s1']}]
    c['documents']=[{'id':'d1','title':'Výpis dodaný uživatelem','kind':'LV','sha256':'a'*64,'pages':2,'register_state_at':'2026-10-29T12:00:00Z','issued_at':'2026-10-30','imported_at':'2026-11-02','completeness':'partial','seal_status':'not_checked','public':False,'inspection':{'path':'/private/original.pdf','text':'Private content','attachments':[{'path':'/private/attachment.xml'}]}}]
    c['evidence']=[{'id':'e1','source_id':'s1','locator':{'note':'Modelová plocha'},'quote':'Ukázka','public':True},{'id':'e2','document_id':'d1','locator':{'page':2,'section':'C','bbox':[10,20,100,150]},'quote':'Soukromý údaj','public':False}]
    c['findings']=[{'id':'f1','title':'Modelový doložený nález','topic':'identity','status':'supported','severity':'info','summary':'Ukazuje důkazní vazbu.','object_ids':['p1'],'evidence_ids':['e1'],'next_step':'','public':True},{'id':'f2','title':'Právní otázka','topic':'rights','status':'unverified','severity':'high','summary':'Podklad je částečný.','object_ids':['p1'],'evidence_ids':['e2'],'next_step':'Získat úplný výpis.','public':True}]
    c['rights']=[{'id':'r1','type':'Podíl','description':'Modelový zlomek','beneficiary_object_ids':['p1'],'burdened_object_ids':[],'share':{'numerator':1,'denominator':8},'evidence_ids':['e2'],'public':True}]
    c['next_documents']=[{'id':'n1','title':'Úplný výpis','reason':'Doplnit chybějící části.','source_url':'https://dpn.cuzk.gov.cz/','for_finding':'f2','priority':'high','status':'needed','public':True}]
    c['research_log']=[{'at':'2026-11-02','source_id':'s1','query':'Modelový postup','status':'planned','note':'Není skutečnou prověrkou.'}]
    return c


class CaseModelTests(unittest.TestCase):
    def test_new_cases_have_unique_ids_and_valid_empty_research_state(self):
        a=model.new_case('Dům','Brno');b=model.new_case('Dům','Brno')
        self.assertNotEqual(a['case']['id'],b['case']['id'])
        self.assertEqual(model.validate_case(a),[])
        self.assertEqual(a['case']['sharing'],'private')
        self.assertEqual(a['findings'],[])

    def test_new_case_rejects_nontext_and_blank_identity(self):
        for args in [(None,'Brno'),('Dům',[]),(' ','Brno'),('Dům',' '),('Dům','Brno',' ')]:
            with self.subTest(args=args),self.assertRaises(ValueError):model.new_case(*args)

    def test_complete_fixture_valid(self):
        self.assertEqual(model.validate_case(complete_case()),[])

    def test_invalid_field_types_return_errors_without_crashing(self):
        values=[None,True,False,0,1.25,[],{},[[]],{'x':[]},'']
        original=complete_case()
        for collection in model.COLLECTIONS:
            for field in original[collection][0]:
                for value in values:
                    with self.subTest(collection=collection,field=field,value=value):
                        c=copy.deepcopy(original);c[collection][0][field]=value
                        self.assertIsInstance(model.validate_case(c),list)
        for key in original:
            for value in values:
                c=copy.deepcopy(original);c[key]=value
                self.assertIsInstance(model.validate_case(c),list)

    def test_non_json_cycles_invalid_unicode_and_extreme_numbers_rejected(self):
        for value in [math.inf,math.nan,10**5000,b'bytes',set(), '\ud800']:
            c=complete_case();c['documents'][0]['inspection']['bad']=value
            self.assertTrue(model.validate_case(c))
        c=complete_case();c['documents'][0]['inspection']['cycle']=c
        self.assertTrue(model.validate_case(c))
        c=complete_case();c[1]='non-text key'
        self.assertTrue(model.validate_case(c))
        c=complete_case();c['case'][1]='non-text key'
        self.assertTrue(model.validate_case(c))

    def test_optional_dates_reject_falsey_wrong_types_and_invalid_calendar(self):
        for value in [False,0,[],{},'2026-02-30','20261102','2026-11-02T10:00:00']:
            c=complete_case();c['documents'][0]['issued_at']=value
            self.assertTrue(model.validate_case(c),str(value))
        for value in [None,'','2026-11-02','2026-11-02T10:00:00+01:00']:
            c=complete_case();c['documents'][0]['issued_at']=value
            self.assertEqual(model.validate_case(c),[])

    def test_identity_needs_cadastral_code_series_and_number(self):
        for field in ['parcel','cadastral_area']:
            c=complete_case();del c['objects'][0][field]
            self.assertTrue(model.validate_case(c))
        for number in ['0','001','123/0','123/04','st. 22','12/3/4',123]:
            c=complete_case();c['objects'][0]['parcel']['number']=number
            self.assertTrue(model.validate_case(c))

    def test_same_parcel_number_in_different_area_or_series_remains_distinct(self):
        for change in ['area','series']:
            c=complete_case();p=copy.deepcopy(c['objects'][0]);p['id']='p2'
            if change=='area':p['cadastral_area']['code']='888888'
            else:p['parcel']['series']='building'
            c['objects'].append(p)
            self.assertEqual(model.validate_case(c),[])

    def test_duplicate_actual_parcel_identity_rejected_even_with_distinct_ids(self):
        c=complete_case();p=copy.deepcopy(c['objects'][0]);p['id']='different-id';c['objects'].append(p)
        self.assertTrue(any('duplicitní parcelní' in e for e in model.validate_case(c)))

    def test_duplicate_and_cross_collection_ids_rejected(self):
        c=complete_case();c['documents'][0]['id']='s1'
        self.assertTrue(any('duplicitní id' in e for e in model.validate_case(c)))

    def test_supported_and_conflict_need_concrete_existing_evidence(self):
        for status in ['supported','conflict']:
            c=complete_case();c['findings'][0].update(status=status,evidence_ids=[])
            self.assertTrue(model.validate_case(c))
            c['findings'][0]['evidence_ids']=['absent']
            self.assertTrue(model.validate_case(c))
        c=complete_case();c['findings'][0].update(status='missing',evidence_ids=[])
        self.assertEqual(model.validate_case(c),[])

    def test_evidence_exactly_one_origin_and_useful_locator(self):
        c=complete_case();c['evidence'][0]['document_id']='d1'
        self.assertTrue(model.validate_case(c))
        for locator in [{},{'note':''},{'bbox':[0,0,1,1]},{'page':0},{'page':True},{'page':2,'bbox':[10,10,0,0]}]:
            c=complete_case();c['evidence'][0]['locator']=locator
            self.assertTrue(model.validate_case(c),str(locator))

    def test_page_locator_must_fit_original_document_but_attachment_is_separate(self):
        c=complete_case();c['evidence'][1]['locator']['page']=3
        self.assertTrue(any('počet stran' in e for e in model.validate_case(c)))
        c['evidence'][1]['locator']['attachment']='attached-document.pdf'
        self.assertEqual(model.validate_case(c),[])

    def test_exact_share_not_float_or_bool_and_not_above_one(self):
        for share in [{'numerator':1.0,'denominator':3},{'numerator':True,'denominator':3},{'numerator':1,'denominator':0},{'numerator':4,'denominator':3},{'numerator':0,'denominator':3}]:
            c=complete_case();c['rights'][0]['share']=share
            self.assertTrue(model.validate_case(c))
        c=complete_case();c['rights'][0]['share']={'numerator':1,'denominator':3}
        self.assertEqual(model.validate_case(c),[])

    def test_unknown_fields_do_not_disappear_silently(self):
        for container in ['case','findings','objects']:
            c=complete_case();row=c[container] if container=='case' else c[container][0]
            row['invented_extension']='value'
            self.assertTrue(model.validate_case(c))

    def test_real_missing_geometry_is_allowed_but_geometry_needs_note(self):
        c=complete_case();c['objects'][0]['geometry']=None;del c['objects'][0]['geometry_note']
        self.assertEqual(model.validate_case(c),[])
        c=complete_case();del c['objects'][0]['geometry_note']
        self.assertTrue(model.validate_case(c))

    def test_geometry_rejects_projection_mix_open_ring_nonfinite_and_huge_int(self):
        for g in [{'type':'Point','coordinates':[-600000,-1100000]},{'type':'Point','coordinates':[10**400,49]},{'type':'Point','coordinates':[16,math.nan]},{'type':'Polygon','coordinates':[[[16,49],[17,49],[17,50],[16,50]]]}]:
            self.assertTrue(model.geometry_errors(g))
        self.assertEqual(model.geometry_errors({'type':'MultiPoint','coordinates':[[16,49],[17,50]]}),[])
        self.assertEqual(model.geometry_errors({'type':'MultiLineString','coordinates':[[[16,49],[17,50]]]}),[])

    def test_suspicious_urls_and_invalid_ports_rejected(self):
        for url in ['javascript:alert(1)','file:///tmp/x','https://user:password@example.org/','https://example.org:99999/','https://example.org/<x>','https://example.org\\x','https://example.org/\x7f']:
            self.assertFalse(model.safe_url(url),url)
        self.assertTrue(model.safe_url('https://services.cuzk.gov.cz/wms/local?x=1&y=2'))
        c=complete_case();c['next_documents'][0]['source_url']=False
        self.assertTrue(model.validate_case(c))

    def test_public_export_requires_explicit_review(self):
        with self.assertRaises(ValueError):model.public_case(complete_case())

    def test_public_export_prunes_private_dependencies_without_downgrading_claims(self):
        c=complete_case();c['case']['sharing']='public-reviewed';before=copy.deepcopy(c)
        out=model.public_case(c)
        self.assertEqual([f['id'] for f in out['findings']],['f1'])
        self.assertEqual([e['id'] for e in out['evidence']],['e1'])
        self.assertEqual(out['documents'],[])
        self.assertEqual(out['rights'],[])
        self.assertEqual(out['next_documents'],[])
        self.assertEqual(out['research_log'],[])
        self.assertEqual(c,before)
        self.assertEqual(model.validate_case(out),[])

    def test_reviewed_document_metadata_never_carries_inspection_payload(self):
        c=complete_case();c['case']['sharing']='public-reviewed'
        c['documents'][0]['public']=True;c['evidence'][1]['public']=True
        out=model.public_case(c)
        self.assertEqual(len(out['documents']),1)
        self.assertNotIn('inspection',out['documents'][0])
        self.assertNotIn('/private/',json.dumps(out))
        self.assertEqual(out['rights'][0]['share'],{'numerator':1,'denominator':8})

    def test_public_false_and_missing_are_never_opt_in(self):
        c=complete_case();c['case']['sharing']='public-reviewed';del c['sources'][0]['public']
        out=model.public_case(c)
        self.assertEqual(out['sources'],[])
        self.assertEqual(out['evidence'],[])
        self.assertEqual(out['findings'],[])
        self.assertEqual(out['objects'][0]['source_ids'],[])

    def test_comparison_tracks_new_evidence_without_claiming_registry_event(self):
        older=complete_case();newer=copy.deepcopy(older)
        newer['case']['as_of']='2026-11-03'
        newer['documents'][0]['register_state_at']='2026-11-03'
        newer['evidence'][0]['quote']='Jiná pozorovaná hodnota'
        newer['findings'][0]['status']='conflict'
        comparison=model.compare_cases(older,newer)
        self.assertEqual(comparison['changes']['documents']['changed'],['d1'])
        self.assertEqual(comparison['changes']['evidence']['changed'],['e1'])
        self.assertEqual(comparison['changes']['findings']['changed'],['f1'])
        self.assertIn('neprokazuje',comparison['note'])
        self.assertEqual(older['evidence'][0]['quote'],'Ukázka')

    def test_comparison_refuses_unrelated_cases(self):
        with self.assertRaises(ValueError):model.compare_cases(model.new_case('A','Brno'),model.new_case('B','Praha'))

    def test_reader_rejects_duplicate_keys_nonfinite_and_large_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'case.json'
            for text in ['{"case":{},"case":{}}','{"value":NaN}','{"value":Infinity}']:
                p.write_text(text)
                with self.assertRaises(ValueError):model.read_case(p)
            with p.open('wb') as stream:stream.truncate(20*1024*1024+1)
            with self.assertRaises(ValueError):model.read_case(p)

    @unittest.skipIf(jsonschema is None,'Optional jsonschema package is not installed')
    def test_schema_is_valid_and_matches_runtime_good_cases(self):
        schema=json.loads((SKILL/'schema.json').read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        validator=jsonschema.Draft202012Validator(schema)
        cases=[complete_case(),model.new_case('Dům','Brno')]
        c=complete_case();c['case']['sharing']='public-reviewed';cases.append(model.public_case(c))
        c=complete_case();c['documents'][0]['issued_at']=None;cases.append(c)
        for c in cases:
            self.assertEqual(model.validate_case(c),[])
            self.assertEqual(list(validator.iter_errors(c)),[])

    @unittest.skipIf(jsonschema is None,'Optional jsonschema package is not installed')
    def test_schema_rejects_structural_errors_while_runtime_checks_references(self):
        schema=json.loads((SKILL/'schema.json').read_text());validator=jsonschema.Draft202012Validator(schema)
        mutants=[]
        for change in ['both_origins','missing_proof','float_share','wrong_case','empty_locator','parcel_identity']:
            c=complete_case()
            if change=='both_origins':c['evidence'][0]['document_id']='d1'
            elif change=='missing_proof':c['findings'][0]['evidence_ids']=[]
            elif change=='float_share':c['rights'][0]['share']['numerator']=0.3
            elif change=='wrong_case':c['case']['as_of']=False
            elif change=='empty_locator':c['evidence'][0]['locator']={}
            elif change=='parcel_identity':del c['objects'][0]['cadastral_area']
            mutants.append(c)
        for c in mutants:
            self.assertTrue(list(validator.iter_errors(c)))
            self.assertTrue(model.validate_case(c))
        c=complete_case();c['findings'][0]['evidence_ids']=['does-not-exist']
        self.assertEqual(list(validator.iter_errors(c)),[])
        self.assertTrue(model.validate_case(c))


if __name__=='__main__':
    unittest.main()
