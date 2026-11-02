#!/usr/bin/env python3
"""Optional real-browser acceptance check; opens local examples, never the web."""
from pathlib import Path
import argparse
import json
import tempfile


def main():
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--screenshots',action='store_true')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--print-dir',type=Path,help='Volitelně uchovat tiskové PDF pro vizuální kontrolu')
    args=parser.parse_args()
    result={'scope':'Local file HTML only; no external page visited','examples':[]}
    with tempfile.TemporaryDirectory(prefix='katastr-print-') as tmp, sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        result['browser']=browser.version
        page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
        page.emulate_media(reduced_motion='reduce')
        remote=[];errors=[]
        page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http://','https://')) else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        for source in sorted((root/'examples').glob('*.html')):
            case=json.loads(source.with_suffix('.json').read_text(encoding='utf-8'))
            page.set_viewport_size({'width':1440,'height':1050})
            page.goto(source.resolve().as_uri())
            assert not errors,errors
            assert not remote,remote
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Desktop overflow'
            missing_anchors=page.eval_on_selector_all('a[href^="#"]','nodes=>nodes.map(n=>n.getAttribute("href").slice(1)).filter(id=>id&&!document.getElementById(decodeURIComponent(id)))')
            assert not missing_anchors,missing_anchors
            assert page.locator('.finding-card').count()==len(case['findings'])
            for obj in case['objects']:
                assert obj['label'] in page.locator('body').inner_text(),obj['id']
            if page.locator('#property-map').count():
                before=page.locator('#property-map').get_attribute('viewBox')
                page.locator('[data-map-action="in"]').click()
                assert page.locator('#property-map').get_attribute('viewBox')!=before
                page.locator('[data-map-action="reset"]').click()
                assert page.locator('#property-map').get_attribute('viewBox')==before
                page.locator('.object-key').first.click()
                assert page.locator('.object-key').first.get_attribute('aria-pressed')=='true'
            filt=page.locator('[data-status-filter="missing"]')
            if filt.count():
                filt.click()
                assert page.locator('.finding-card:visible').count()==sum(f['status']=='missing' for f in case['findings'])
            page.locator('[data-status-filter="all"]').click()
            page.locator('#finding-search').fill('nenaleznutelny-retezec-XYZ')
            assert page.locator('.finding-card:visible').count()==0
            assert page.locator('#no-filter-results').is_visible()
            page.locator('#finding-search').fill('')
            assert page.locator('.finding-card:visible').count()==len(case['findings'])
            if args.screenshots and source.stem=='brno-byt-model':
                page.evaluate('document.activeElement.blur(); window.scrollTo({top:0,behavior:"instant"})')
                page.screenshot(path=str(root/'docs/nahled-reportu.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Mobile overflow'
            if args.screenshots and source.stem=='brno-byt-model':
                page.evaluate('document.activeElement.blur(); window.scrollTo({top:0,behavior:"instant"})')
                page.screenshot(path=str(root/'docs/nahled-mobil.png'))
            page.set_viewport_size({'width':1440,'height':1050})
            if filt.count():filt.click()
            hidden_before=page.locator('.finding-card[hidden]').count()
            pdf=(args.print_dir or Path(tmp))/(source.stem+'.pdf')
            pdf.parent.mkdir(parents=True,exist_ok=True)
            page.pdf(path=str(pdf),format='A4',print_background=True,prefer_css_page_size=True)
            pages=PdfReader(pdf).pages
            text=' '.join(' '.join((p.extract_text() or '').split()) for p in pages)
            for finding in case['findings']:
                assert ' '.join(finding['title'].split()) in text,('Missing printed finding',finding['id'])
            for ev in case['evidence']:
                if ev.get('quote'):
                    assert ' '.join(ev['quote'].split()) in text,('Missing printed evidence',ev['id'])
            assert page.locator('.finding-card[hidden]').count()==hidden_before,'Print did not restore filter'
            assert not errors,errors
            assert not remote,remote
            result['examples'].append({'file':source.name,'desktop_width':1440,'mobile_width':390,'horizontal_overflow':False,'missing_anchors':[],'javascript_errors':[],'external_requests':0,'findings':len(case['findings']),'pdf_pages':len(pages),'printed_all_findings':True,'printed_all_evidence_quotes':True,'print_restored_filter':True})
        browser.close()
    rendered=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(rendered,encoding='utf-8')
    print(rendered)

if __name__=='__main__':main()
