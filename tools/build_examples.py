#!/usr/bin/env python3
"""Rebuild explicitly fictional teaching examples; never query real owners."""
from pathlib import Path
import hashlib
import json
import os
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get('KATASTR_SKILL_ROOT', ROOT / 'skills/katastr-nemovitosti'))
sys.path.insert(0, str(SKILL / 'scripts'))
from case_model import require_valid, public_case
from report import render_html, render_markdown, export_geojson

DATE = '2026-11-02'
EXAMPLES = ROOT / 'examples'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def model_pdf(name, pages):
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = Path(os.environ.get('KATASTR_DEMO_FONT', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    if not font.is_file():
        raise SystemExit('Nastav KATASTR_DEMO_FONT na lokální TTF podporující češtinu.')
    pdfmetrics.registerFont(TTFont('DemoSans', str(font)))
    out = EXAMPLES / 'podklady' / name
    out.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out), pagesize=(595.28,841.89), invariant=1)
    c.setTitle('Syntetické učební podklady - žádná skutečná nemovitost')
    c.setAuthor('Katastr a souvislosti / testovací podklady')
    for index, (title, sections) in enumerate(pages,1):
        c.setFillColor(HexColor('#fff9ed')); c.rect(0,0,595.28,841.89,fill=1,stroke=0)
        c.setFillColor(HexColor('#a45c15')); c.setFont('DemoSans',11)
        c.drawString(44,797,'MODELOVÉ PODKLADY / NEJDE O ÚŘEDNÍ LISTINU')
        c.setFillColor(HexColor('#173e3d')); c.setFont('DemoSans',20)
        c.drawString(44,751,title)
        c.setFont('DemoSans',10)
        c.drawString(44,724,'Fiktivní situace pro ověření postupu. Bez údajů skutečných osob.')
        y=674
        for heading, content in sections:
            c.setFont('DemoSans',12);c.setFillColor(HexColor('#173e3d'))
            c.drawString(44,y,heading);y-=25
            c.setFont('DemoSans',10);c.setFillColor(HexColor('#283b3c'))
            for line in textwrap.wrap(content,86):
                c.drawString(44,y,line);y-=17
            y-=27
        c.setFont('DemoSans',9);c.setFillColor(HexColor('#68716b'))
        c.drawString(44,39,f'Syntetický dokument / {DATE} / Strana {index} z {len(pages)}')
        c.showPage()
    c.save()
    return out


def base(identifier,title,purpose,locality,region,summary):
    return {'schema_version':'property-case/1.0','case':{'id':identifier,'title':title,'purpose':purpose,'locality':locality,'region':region,'created_at':DATE+'T10:00:00+01:00','as_of':DATE,'mode':'synthetic','summary':summary,'scope_note':'Syntetický učební případ. Všechny objekty, listiny, geometrie a nálezy jsou smyšlené; nejde o prověření reálné nemovitosti v uvedeném regionu.','sharing':'public-reviewed'},**{k:[] for k in ('objects','sources','documents','evidence','findings','rights','next_documents','research_log')}}


def document(case,path,identifier,title,pages):
    case['documents'].append({'id':identifier,'title':title,'kind':'synthetic-teaching-document','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages':pages,'register_state_at':'','issued_at':DATE,'imported_at':DATE+'T10:00:00+01:00','completeness':'unknown','seal_status':'not_checked','public':True})


def evidence(case,identifier,doc,page,section,quote):
    case['evidence'].append({'id':identifier,'document_id':doc,'locator':{'page':page,'section':section,'note':'Syntetický učební dokument; citace se nevztahuje k reálné nemovitosti.'},'quote':quote,'observed_at':DATE,'public':True})


def finding(case,identifier,title,topic,status,severity,summary,objects,ev,next_step=''):
    case['findings'].append(dict(id=identifier,title=title,topic=topic,status=status,severity=severity,summary=summary,object_ids=objects,evidence_ids=ev,next_step=next_step,public=True))


def request(case,identifier,title,reason,for_finding,url='https://dpn.cuzk.gov.cz/'):
    case['next_documents'].append(dict(id=identifier,title=title,reason=reason,source_url=url,for_finding=for_finding,priority='high',status='needed',public=True))


def polygon(points):
    return {'type':'Polygon','coordinates':[points+[points[0]]]}


def obj(identifier,kind,label,geometry=None):
    d={'id':identifier,'type':kind,'label':label,'cadastral_area':{'code':'000000','name':'Fiktivní katastr pro model'},'source_ids':[]}
    if geometry:
        d.update(geometry=geometry,geometry_note='Syntetická geometrie pro ukázku ovládání. Není mapou skutečné parcely ani podkladem pro měření.')
    return d


def build_brno():
    pdf=model_pdf('brno-modelove-podklady.pdf',[
      ('Byt, terasa a související podklady',[
        ('1. Modelový text inzerátu','Byt B-12 má vlastní terasu T a sklep S. Přístup je zajištěn přes dvůr D.'),
        ('2. Modelový výňatek z prohlášení','Terasa T je společnou částí domu vyhrazenou k výlučnému užívání vlastníku jednotky B-12. Podíl jednotky B-12 na společných částech činí 745/10000.'),
        ('3. Co tento model neobsahuje','Úplné prohlášení vlastníka a jeho změny nejsou přiloženy. Přesné vymezení sklepa S v tomto výňatku není uvedeno.')]),
      ('Rozsah předložených podkladů',[
        ('4. Modelový částečný výpis','V modelu byla dodána jen část B výpisu. Části B1, C a D nebyly dodány. Z tohoto soupisu nelze uzavřít kontrolu práv a omezení.'),
        ('5. Přístup','Geometrické schéma ukazuje dvůr D. Listina, která by vymezovala oprávnění průjezdu přes dvůr, není přiložena.'),
        ('6. Energetický podklad','PENB nebyl předložen. Tento model neobsahuje měření spotřeby ani odhad energetické třídy.')])])
    c=base('demo-brno-byt','Byt, terasa a právo přístupu','Příprava koupě bytu','Brno · modelová situace','Jihomoravský kraj','Model ukazuje, proč porovnat slib v inzerátu s vymezením jednotky a společných částí. Terasa je v podkladu popsána jako společná část; úplný právní stav, sklep a průjezd zatím nejsou doloženy.')
    c['objects']=[obj('dum','building','Modelový dům A',polygon([[16.6001,49.1951],[16.6007,49.1951],[16.6007,49.1955],[16.6001,49.1955]])),obj('terasa','area','Terasa T · model',polygon([[16.6007,49.19515],[16.60092,49.19515],[16.60092,49.1954],[16.6007,49.1954]])),obj('dvur','area','Dvůr D · model',polygon([[16.5999,49.19485],[16.60095,49.19485],[16.60095,49.19507],[16.5999,49.19507]])),obj('byt','unit','Jednotka B-12 · model')]
    c['objects'][-1]['registry_id']='MODEL-B12'
    document(c,pdf,'podklad-byt','Modelové podklady: byt a terasa',2)
    evidence(c,'ev-inzerat','podklad-byt',1,'1. Modelový text inzerátu','Byt B-12 má vlastní terasu T a sklep S. Přístup je zajištěn přes dvůr D.')
    evidence(c,'ev-terasa','podklad-byt',1,'2. Modelový výňatek z prohlášení','Terasa T je společnou částí domu vyhrazenou k výlučnému užívání vlastníku jednotky B-12.')
    evidence(c,'ev-podil','podklad-byt',1,'2. Modelový výňatek z prohlášení','Podíl jednotky B-12 na společných částech činí 745/10000.')
    evidence(c,'ev-neuplne','podklad-byt',2,'4. Modelový částečný výpis','V modelu byla dodána jen část B výpisu. Části B1, C a D nebyly dodány.')
    finding(c,'terasa-rozpor','Terasa: tvrzení inzerátu vyžaduje opravu','rights','conflict','high','Modelový inzerát mluví o vlastní terase. Výňatek ji popisuje jako společnou část s výlučným užíváním. Tyto formulace nemají stejný význam.',['byt','terasa'],['ev-inzerat','ev-terasa'],'Doložit úplné prohlášení a jeho změny; přesný režim převzít i do popisu předmětu koupě.')
    finding(c,'pravni-stav','Úplný právní stav zůstává otevřený','rights','missing','high','Dodaná část výpisu neobsahuje části B1, C a D. Žádný závěr o absenci právních omezení z ní nevzniká.',['byt'],['ev-neuplne'],'Získat správný úplný aktuální výpis pro jednotku a relevantní související objekty.')
    finding(c,'pristup','Průjezd dvorem není doložen listinou','access','missing','high','Schéma ukazuje prostor dvora a inzerát tvrdí přístup. Podklad pro rozsah oprávnění průjezdu chybí.',['dvur','byt'],['ev-inzerat'],'Vyžádat podklad ke konkrétnímu tvrzenému oprávnění a případný geometrický plán.')
    finding(c,'spolecne-casti','Podíl na společných částech je uveden zvlášť','rights','supported','info','Modelový výňatek uvádí přesný podíl 745/10000. Nejde o podíl osoby na vlastnictví jednotky; ten by vyžadoval samostatný údaj.',['byt','dum'],['ev-podil'])
    finding(c,'sklep','Vymezení sklepa je potřeba doplnit','rights','unverified','medium','Modelové podklady nevymezují, zda sklep tvoří součást jednotky, společnou část, nebo samostatný objekt.',['byt'],[],'Doplnit příslušné vymezení a půdorys z úplného prohlášení vlastníka.')
    finding(c,'energie','Energetický průkaz nebyl dodán','energy','missing','info','Bez odpovídajícího PENB nelze z těchto podkladů uvést energetickou třídu.',['dum'],[],'Vyžádat průkaz odpovídající budově a aktuálnímu stavu.')
    c['rights']=[{'id':'podil-spolecne','type':'Podíl jednotky na společných částech (model)','beneficiary_object_ids':['byt'],'burdened_object_ids':[],'share':{'numerator':745,'denominator':10000},'description':'Modelová vazba podílu jednotky; nejde o zjištění o reálném vlastníkovi.','evidence_ids':['ev-podil'],'public':True}]
    request(c,'req-prohlaseni','Úplné prohlášení vlastníka','Rozhodne vymezení terasy, sklepa a společných částí.','terasa-rozpor')
    request(c,'req-lv','Úplný aktuální výpis','Doplní neviděné části a správný časový stav.','pravni-stav')
    request(c,'req-pristup','Podklad k právu průjezdu','Vymezí oprávněné a zatížené objekty a rozsah užívání.','pristup')
    return c


def build_vysocina():
    pdf=model_pdf('vysocina-modelove-podklady.pdf',[
      ('Pozemek a jeho užívání',[
        ('1. Modelový soupis','Modelová parcela P-1 je v tomto příkladu trvalý travní porost. Modelový spoluvlastnický podíl zkoumané osoby je 3/16. Nejde o údaje skutečného katastru.'),
        ('2. Modelový záznam užívání','V modelu LPIS je u dílu půdního bloku uveden uživatel Provozovatel A. Tento záznam neposkytuje vlastnický titul k modelové parcele P-1.'),
        ('3. Přístup a plánované zařízení','Podklad k pozemkovým úpravám v modelu obsahuje návrh cesty C. Potvrzení skutečné realizace a právní titul užívání nejsou dodány.'),
        ('4. Chybějící kontroly','V tomto příkladu nebyla provedena kontrola BPEJ, ochrany půdy, záplavových území ani místního územního plánu.')])])
    c=base('demo-vysocina-puda','Louka, uživatel a přístupová cesta','Porozumění zděděnému podílu','Vysočina · modelová situace','Kraj Vysočina','Model odděluje spoluvlastnický podíl od evidence užívání půdy. U návrhu cesty zůstává otevřená realizace i oprávnění přístupu; další územní vrstvy zatím nebyly prověřeny.')
    p=obj('pozemek','area','Modelový pozemek P-1',polygon([[15.520,49.395],[15.522,49.3954],[15.5216,49.3963],[15.5198,49.396]]))
    c['objects']=[p,obj('blok','area','Modelový půdní blok',polygon([[15.5221,49.39545],[15.5233,49.39565],[15.5230,49.3964],[15.5217,49.3963]])),obj('cesta','area','Navržená cesta C · model',{'type':'LineString','coordinates':[[15.5196,49.3948],[15.5235,49.3955]]})]
    document(c,pdf,'podklad-puda','Modelové podklady: půda a přístup',1)
    evidence(c,'ev-puda','podklad-puda',1,'1. Modelový soupis','Modelový spoluvlastnický podíl zkoumané osoby je 3/16.')
    evidence(c,'ev-uzivani','podklad-puda',1,'2. Modelový záznam užívání','V modelu LPIS je u dílu půdního bloku uveden uživatel Provozovatel A.')
    evidence(c,'ev-cesta','podklad-puda',1,'3. Přístup a plánované zařízení','Podklad k pozemkovým úpravám v modelu obsahuje návrh cesty C.')
    finding(c,'podil','Podíl je potřeba uchovat jako přesný zlomek','rights','supported','info','Modelový soupis uvádí 3/16. Podíl sám nevymezuje konkrétní fyzický výsek pozemku.',['pozemek'],['ev-puda'])
    finding(c,'uzivatel','Uživatel půdy není vlastnický údaj','agriculture','supported','medium','Modelová evidence užívání obsahuje Provozovatele A. Rozdílné jméno samo o sobě nemění vlastnictví popsané v jiném podkladu.',['pozemek','blok'],['ev-uzivani'])
    finding(c,'realizace','Navržená cesta nemusí být hotová','access','unverified','high','Máme modelový návrh cesty, nikoli doklad jejího provedení a režimu užívání.',['pozemek','cesta'],['ev-cesta'],'Dohledat stav realizace společného zařízení a příslušný titul přístupu.')
    finding(c,'bpej','Půdní podklady zatím nebyly ověřeny','agriculture','unverified','medium','BPEJ ani ochrana půdy nejsou v dostupných modelových podkladech zpracovány.',['pozemek'],[],'Prověřit SPÚ/VÚMOP pro potvrzenou skutečnou parcelu.')
    finding(c,'povoden','Povodňová kontrola není dokončená','water','unverified','medium','Absence provedené kontroly se nesmí změnit na tvrzení, že pozemek leží mimo záplavové území.',['pozemek'],[],'Porovnat skutečný polygon s příslušnými aktuálními podklady.')
    request(c,'req-cesta','Podklad k realizaci a užívání cesty','Rozliší návrh společného zařízení, jeho provedení a právní přístup.','realizace','https://spu.gov.cz/geoportal-spu')
    return c


def main():
    EXAMPLES.mkdir(exist_ok=True)
    for name,case in [('brno-byt-model',build_brno()),('vysocina-pozemek-model',build_vysocina())]:
        require_valid(case);write_json(EXAMPLES/(name+'.json'),case)
    for path in sorted(EXAMPLES.glob('*.json')):
        case=json.loads(path.read_text(encoding='utf-8'))
        if case.get('schema_version')!='property-case/1.0':continue
        reviewed=public_case(require_valid(case))
        path.with_suffix('.html').write_text(render_html(reviewed),encoding='utf-8')
        path.with_suffix('.md').write_text(render_markdown(reviewed),encoding='utf-8')
        path.with_suffix('.geojson').write_text(json.dumps(export_geojson(reviewed),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(path.name)

if __name__=='__main__':main()
