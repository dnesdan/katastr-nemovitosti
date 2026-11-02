import base64
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
from urllib.parse import parse_qs, urlsplit

SKILL = Path(os.environ.get('KATASTR_SKILL_ROOT', str(Path(__file__).resolve().parents[1] / 'skills/katastr-nemovitosti')))
sys.path.insert(0, str(SKILL / 'scripts'))
import sources
from http_client import FetchError, FetchResult

class Client:
    def __init__(self, responses): self.responses=list(responses);self.urls=[]
    def fetch(self,url,refresh=False):
        self.urls.append(url)
        value=self.responses.pop(0)
        data,mime=value if isinstance(value,tuple) else (value,'application/xml')
        if isinstance(data,dict):data=json.dumps(data).encode();mime='application/json'
        return FetchResult(data,mime,url,'2026-11-02T12:00:00+00:00')

CAPS=b'''<WMS_Capabilities version="1.3.0" xmlns="http://www.opengis.net/wms" xmlns:xlink="http://www.w3.org/1999/xlink"><Service><Title>Mapa</Title></Service><Capability><Request><GetMap><Format>image/png</Format><DCPType><HTTP><Get><OnlineResource xlink:href="https://services.cuzk.gov.cz/wms/test"/></Get></HTTP></DCPType></GetMap></Request><Layer queryable="1"><CRS>EPSG:4326</CRS><CRS>CRS:84</CRS><Layer><Name>parcely</Name><Title>Parcely</Title></Layer></Layer></Capability></WMS_Capabilities>'''

POLYGON='<cp:geometry><gml:Polygon srsName="http://www.opengis.net/def/crs/EPSG/0/4326" srsDimension="2"><gml:exterior><gml:LinearRing><gml:posList>49 17 49 17.001 49.001 17.001 49 17</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon></cp:geometry>'

def png(width=16,height=16,pixel_bytes=None):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    pixels=pixel_bytes if pixel_bytes is not None else (b'\x00'+b'\xff\xff\xff'*width)*height
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')

def wfs(geometry=POLYGON, *, matched=1, returned=1, label='st. 99/3'):
    feature=f'<wfs:member><cp:CadastralParcel gml:id="CP.123"><cp:label>{label}</cp:label><cp:nationalCadastralReference>774858-{label}</cp:nationalCadastralReference><cp:areaValue uom="m2">120</cp:areaValue>{geometry}</cp:CadastralParcel></wfs:member>' if returned else ''
    return f'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:cp="http://inspire.ec.europa.eu/schemas/cp/4.0" xmlns:gml="http://www.opengis.net/gml/3.2" numberMatched="{matched}" numberReturned="{returned}" timeStamp="2026-11-02T12:00:00Z">{feature}</wfs:FeatureCollection>'.encode()

class SourceTests(unittest.TestCase):
    def test_ruian_candidates_never_autoselected_and_limit_clear(self):
        c=Client([{'features':[{'attributes':{'kod':1,'adresa':'Brno, test 1'},'geometry':{'x':16.6,'y':49.2}}, {'attributes':{'kod':2,'adresa':'Brno, test 2'}}]}])
        r=sources.ruian(c,'Brno',limit=1)
        self.assertIsNone(r['selected']);self.assertTrue(r['truncated']);self.assertEqual(r['returned_count'],1)
        self.assertEqual(r['candidates'][0]['registry_point']['coordinates'],[16.6,49.2])

    def test_ruian_literal_quote_cannot_break_where(self):
        c=Client([{'features':[]}]);sources.ruian(c,"D'Artagnan",kind='municipality')
        self.assertIn("D''ARTAGNAN",parse_qs(urlsplit(c.urls[0]).query)['where'][0])

    def test_ruian_wildcard_or_boolean_limit_refused(self):
        for query,limit in [('Br%',2),('Brno',True),('Brno',0),('Brno',51)]:
            with self.assertRaises(ValueError):sources.ruian(Client([]),query,limit=limit)

    def test_ruian_provider_error_is_not_empty(self):
        with self.assertRaises(FetchError):sources.ruian(Client([{'error':{'message':'Too many requests'}}]),'Brno')
        with self.assertRaises(FetchError):sources.ruian(Client([{}]),'Brno')

    def test_ruian_empty_scope_is_explicit(self):
        r=sources.ruian(Client([{'features':[]}]),'Vybraná obec')
        self.assertEqual(r['status'],'empty');self.assertTrue(r['limitations'])

    def test_ruian_rejects_wrong_spatial_range(self):
        with self.assertRaises(FetchError):sources.ruian(Client([{'features':[{'attributes':{'kod':1},'geometry':{'x':-600000,'y':-1100000}}]}]),'Brno')

    def test_building_is_exact_and_geojson_polygon(self):
        geometry={'type':'Polygon','coordinates':[[[16,49],[16.1,49],[16.1,49.1],[16,49]]]}
        r=sources.ruian_building(Client([{'type':'FeatureCollection','features':[{'type':'Feature','properties':{'kod':123},'geometry':geometry}]}]),'123')
        self.assertEqual(r['records'][0]['geometry'],geometry)
        self.assertIsNone(r['selected'])

    def test_building_mismatched_id_or_crs_fails(self):
        data={'type':'FeatureCollection','features':[{'properties':{'kod':124},'geometry':None}]}
        with self.assertRaises(FetchError):sources.ruian_building(Client([data]),'123')
        data={'type':'FeatureCollection','features':[],'crs':{'properties':{'name':'EPSG:5514'}}}
        with self.assertRaises(FetchError):sources.ruian_building(Client([data]),'123')

    def test_wms_inheritance_and_canonical_url(self):
        r=sources.wms(Client([CAPS]),'https://services.cuzk.gov.cz/wms/test?LAYERS=wrong&REQUEST=GetMap')
        self.assertEqual(r['layers'][0]['crs'],['CRS:84','EPSG:4326'])
        self.assertTrue(r['layers'][0]['queryable'])
        self.assertNotIn('LAYERS=',r['request_url'])

    def test_wms_axis_order(self):
        p=sources.map_parameters('x',[16,49,17,50],'1.3.0','EPSG:4326',800,600,'image/png')
        self.assertEqual(p['BBOX'],'49,16,50,17')
        p=sources.map_parameters('x',[16,49,17,50],'1.1.1','EPSG:4326',800,600,'image/png')
        self.assertEqual(p['BBOX'],'16,49,17,50')

    def test_wms_refuses_bad_bbox_dimensions_and_implicit_projection(self):
        for bbox in ([16,49,16,50],[float('nan'),49,17,50],[16,49,17,91]):
            with self.assertRaises(ValueError):sources.map_parameters('x',bbox,'1.3.0','EPSG:4326',800,600,'image/png')
        with self.assertRaises(ValueError):sources.map_parameters('x',[-600000,-1100000,-599000,-1099000],'1.3.0','EPSG:5514',800,600,'image/png')
        with self.assertRaises(ValueError):sources.map_parameters('x',[16,49,17,50],'1.3.0','EPSG:4326',True,600,'image/png')

    def test_wms_exceptions_and_entities_not_layers(self):
        for xml in [b'<ServiceExceptionReport><ServiceException>Denied</ServiceException></ServiceExceptionReport>',b'<!DOCTYPE x [<!ENTITY a "bad">]><x>&a;</x>', '<!DOCTYPE x [<!ENTITY a "bad">]><x>&a;</x>'.encode('utf-16')]:
            with self.assertRaises(FetchError):sources.parse_wms(xml)

    def test_wms_map_does_not_save_html_as_image(self):
        c=Client([CAPS,(b'<html>denied</html>','text/html')])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'map.png'
            with self.assertRaises(FetchError):sources.wms_map(c,'https://services.cuzk.gov.cz/wms/test','parcely',[16,49,17,50],path)
            self.assertFalse(path.exists())

    def test_wms_map_does_not_follow_advertised_other_host(self):
        c=Client([CAPS.replace(b'https://services.cuzk.gov.cz/wms/test',b'https://evil.example/map')])
        with tempfile.TemporaryDirectory() as d, self.assertRaises(FetchError):
            sources.wms_map(c,'https://services.cuzk.gov.cz/wms/test','parcely',[16,49,17,50],Path(d)/'map.png')
        self.assertEqual(len(c.urls),1)

    def test_wfs_polygon_uses_declared_axis_order(self):
        r=sources.parse_wfs_parcels(wfs())
        self.assertEqual(r['records'][0]['geometry']['coordinates'][0][0],[17.0,49.0])
        self.assertEqual(r['records'][0]['area_unit'],'m2')
        self.assertEqual(r['status'],'ok')

    def test_wfs_keeps_polygon_hole(self):
        interior='<gml:interior><gml:LinearRing><gml:posList>49.0001 17.0001 49.0001 17.0002 49.0002 17.0002 49.0001 17.0001</gml:posList></gml:LinearRing></gml:interior>'
        r=sources.parse_wfs_parcels(wfs(POLYGON.replace('</gml:Polygon>',interior+'</gml:Polygon>')))
        self.assertEqual(len(r['records'][0]['geometry']['coordinates']),2)

    def test_wfs_unknown_crs_keeps_identity_without_fake_geometry(self):
        r=sources.parse_wfs_parcels(wfs(POLYGON.replace('/4326','/5514')))
        self.assertIsNone(r['records'][0]['geometry']);self.assertTrue(r['records'][0]['geometry_warning'])

    def test_partial_multisurface_is_never_presented_as_complete_polygon(self):
        inner=POLYGON.removeprefix('<cp:geometry>').removesuffix('</cp:geometry>')
        for extra in ['<gml:surfaceMember xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#missing"/>',
                      '<gml:surfaceMember/>', '<gml:surfaceMember><gml:Surface><gml:patches/></gml:Surface></gml:surfaceMember>',
                      '<gml:surfaceMember><gml:OrientableSurface/></gml:surfaceMember>']:
            geometry='<cp:geometry><gml:MultiSurface><gml:surfaceMember>'+inner+'</gml:surfaceMember>'+extra+'</gml:MultiSurface></cp:geometry>'
            record=sources.parse_wfs_parcels(wfs(geometry))['records'][0]
            self.assertIsNone(record['geometry'])
            self.assertTrue(record['geometry_warning'])

    def test_complete_multisurface_keeps_all_members(self):
        inner=POLYGON.removeprefix('<cp:geometry>').removesuffix('</cp:geometry>')
        geometry='<cp:geometry><gml:MultiSurface>'+('<gml:surfaceMember>'+inner+'</gml:surfaceMember>')*2+'</gml:MultiSurface></cp:geometry>'
        record=sources.parse_wfs_parcels(wfs(geometry))['records'][0]
        self.assertEqual(record['geometry']['type'],'MultiPolygon')
        self.assertEqual(len(record['geometry']['coordinates']),2)
        self.assertFalse(record['geometry_warning'])

    def test_wfs_closed_ring_required(self):
        with self.assertRaises(FetchError):sources.parse_wfs_parcels(wfs(POLYGON.replace('49.001 17.001 49 17','49.001 17.001 49 18')))

    def test_wfs_empty_is_explicit_and_counts_checked(self):
        self.assertEqual(sources.parse_wfs_parcels(wfs(matched=0,returned=0))['status'],'empty')
        with self.assertRaises(FetchError):sources.parse_wfs_parcels(wfs(matched=0,returned=1))
        with self.assertRaises(FetchError):sources.parse_wfs_parcels(wfs().replace(b'numberReturned="1"',b'numberReturned="2"'))

    def test_wfs_entities_and_exception_documents_refused(self):
        for xml in [b'<!DOCTYPE x><x/>',b'<ExceptionReport><ExceptionText>Too broad</ExceptionText></ExceptionReport>',b'<html>login</html>']:
            with self.assertRaises(FetchError):sources.parse_wfs_parcels(xml)

    def test_parcel_series_is_part_of_exact_identity(self):
        c=Client([wfs()]);r=sources.parcel(c,'774858','99/3',series='building')
        q=parse_qs(urlsplit(c.urls[0]).query)
        self.assertEqual(q['TEXT'],['st. 99/3']);self.assertEqual(q['COUNT'],['2'])
        self.assertEqual(q['UPPER_ZONING_ID'],['774858']);self.assertEqual(r['series'],'building')

    def test_parcel_cannot_accept_different_identity(self):
        with self.assertRaises(FetchError):sources.parcel(Client([wfs()]),'772984','99/3',series='building')
        with self.assertRaises(FetchError):sources.parcel(Client([wfs()]),'774858','99/3',series='land')

    def test_invalid_parcel_inputs_do_not_send_network(self):
        for code,number,series in [('123','99','land'),('774858','st. 99','land'),('774858','99/0','land'),('774858','%','land'),('774858','99','unknown')]:
            c=Client([])
            with self.assertRaises(ValueError):sources.parcel(c,code,number,series)
            self.assertFalse(c.urls)

    def test_png_requires_chunks_crc_and_complete_bounded_pixels(self):
        self.assertEqual(sources.image_dimensions(png(),'image/png'),(16,16))
        fake=b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\x0dIHDR'+struct.pack('>II',16,16)+b'x'*5+b'IEND'
        self.assertEqual(len(fake),33)
        for data in [fake, png()[:-1], png()+b'trailing', png().replace(b'IDAT',b'JDAT'),
                     png(pixel_bytes=b'x'*20000), png(pixel_bytes=b'')]:
            with self.subTest(length=len(data)),self.assertRaises(FetchError):sources.image_dimensions(data,'image/png')

    def test_jpeg_without_scan_header_is_not_valid_image(self):
        # The old parser returned immediately from any SOF marker.
        fake=b'\xff\xd8\xff\xc0'+struct.pack('>H',17)+b'\x08'+struct.pack('>HH',16,16)+b'\x03'+b'\x01\x11\x00'*3+b'\xff\xd9'
        with self.assertRaises(FetchError):sources.image_dimensions(fake,'image/jpeg')

    def test_map_publication_never_overwrites_files_created_during_fetch(self):
        for collision in ('map','sidecar'):
            with self.subTest(collision=collision),tempfile.TemporaryDirectory() as d:
                path=Path(d)/'map.png';sidecar=Path(str(path)+'.json')
                target=path if collision=='map' else sidecar
                class RacingClient(Client):
                    def fetch(self,url,refresh=False):
                        result=super().fetch(url,refresh)
                        if result.content_type=='image/png':target.write_bytes(b'other writer')
                        return result
                c=RacingClient([CAPS,(png(),'image/png')])
                with self.assertRaises(FileExistsError):sources.wms_map(c,'https://services.cuzk.gov.cz/wms/test','parcely',[16,49,17,50],path,width=16,height=16)
                self.assertEqual(target.read_bytes(),b'other writer')
                self.assertFalse((sidecar if collision=='map' else path).exists())
                self.assertFalse(list(Path(d).glob('*.tmp')))

    def test_map_and_metadata_are_published_together_without_replace(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'map.png';c=Client([CAPS,(png(),'image/png')])
            r=sources.wms_map(c,'https://services.cuzk.gov.cz/wms/test','parcely',[16,49,17,50],path,width=16,height=16)
            self.assertEqual(path.read_bytes(),png())
            self.assertEqual(json.loads(Path(str(path)+'.json').read_text())['sha256'],r['sha256'])
            self.assertEqual(r['image_validation'],'png_chunks_crc_and_pixel_stream')

if __name__ == '__main__': unittest.main()
