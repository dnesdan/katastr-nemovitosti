# Uherský Brod · parcela 1

**Katastr a souvislosti**

**Místo:** Uherský Brod  
**Účel:** Ukázka dohledání skutečné identity a mapové geometrie z veřejných služeb  
**Datum přehledu:** 2\. 11\. 2026  
**Sdílení:** Přehled ke sdílení

Veřejné služby ČÚZK potvrdily parcelu 1 v katastrálním území Uherský Brod \(772984\) a vrátily její polygon\. Právní stav, územní plán, právní přístup a povodňové souvislosti tento příklad neprověřoval\.

**Rozsah prověření:** Skutečný malý dotaz do RÚIAN, WFS a WMS dne 2\. 11\. 2026\. Příklad slouží k ověření identifikace a mapového výstupu\. Neobsahuje vlastníky, LV, soukromé listiny ani posouzení vhodnosti koupě nebo stavby\. Čas stažení není datem měření hranic\.

## Nemovitost

- **Parcela 1 · k\.ú\. Uherský Brod** — Parcela · 1 · k\. ú\. Uherský Brod · kód k\. ú\. 772984 · ID v registru CP\.2793846742
  Geometrie je součástí podkladů\.
  Skutečný polygon z INSPIRE WFS ČÚZK, prvek CP\.2793846742\. Deklarované osy EPSG:4326 převedeny do GeoJSON \[délka, šířka\]\. Přesnost hranic není tímto dotazem stanovena; zobrazení nenahrazuje vytyčení\. Zdroj © ČÚZK\.

## Nálezy

### 1. Parcela je jednoznačně identifikovaná

**Doloženo · Souvislost**

RÚIAN uvádí katastrální území Uherský Brod pod kódem 772984\. Přesný WFS dotaz na pozemkovou parcelu 1 vrátil jediný prvek CP\.2793846742 s referencí 772984-1\.

Důkazy: [ev-ku](#evidence-69bdf5adde6dc57a), [ev-identita](#evidence-d0a89da83072094a)

### 2. Mapa zobrazuje skutečný vrácený polygon

**Doloženo · Souvislost**

Geometrie v reportu pochází z odpovědi WFS\. Samostatně získaný a prohlédnutý WMS výřez obsahuje označení parcely 1\. Žádná okolní vlastnická či přístupová práva z mapy nevyvozujeme\.

Důkazy: [ev-geometrie](#evidence-089da2d86d9b4867), [ev-mapa](#evidence-82bc96981d148e13)

### 3. WFS uvádí výměru 765 m²

**Doloženo · Souvislost**

Hodnota 765 m² je deklarovaný atribut cp:areaValue v této odpovědi WFS\. Není výsledkem plošného měření v reportu ani náhradou úplného LV\.

Důkazy: [ev-vymera](#evidence-b9ebafebf1c12a0b)

### 4. Pro právní stav chybí list vlastnictví

**Chybí podklad · Zásadní pro rozhodnutí**

Tento příklad nezískával LV ani listiny\. Vlastníci, podíly, omezení a případná řízení proto nejsou vyhodnoceny\.

Závěr zatím nemá přiřazený důkaz.

**Další krok:** Získat úplný aktuální LV pro identifikovanou parcelu; následně určit relevantní listiny\.

### 5. Územní plán nebyl prověřen

**Neověřeno · K dořešení**

Nebyl dohledán účinný územní plán ani jeho regulativy pro tento polygon\. Z absence kontroly neplyne žádný závěr o stavební možnosti\.

Závěr zatím nemá přiřazený důkaz.

**Další krok:** Dohledat platný plán města, účinné změny, legendu a text pro dotčenou plochu\.

### 6. Právní přístup zůstává otevřený

**Neověřeno · K dořešení**

Mapový výřez nebyl doplněn podklady k právu přístupu\. Viditelné linie v mapě samy tuto otázku neuzavírají\.

Závěr zatím nemá přiřazený důkaz.

**Další krok:** Určit zamýšlenou přístupovou trasu a podle LV a dalších příslušných podkladů prověřit oprávnění k jejímu užívání\.

### 7. Povodňové souvislosti nebyly kontrolovány

**Neověřeno · K dořešení**

Žádná povodňová vrstva ani příslušný dokument nebyly pro tuto parcelu vyhodnoceny\. Výsledek je neověřeno, nikoli mimo záplavové území\.

Závěr zatím nemá přiřazený důkaz.

**Další krok:** Porovnat celý polygon s aktuálním oficiálním podkladem záplavových území a ověřit jeho rozsah a datum\.

## Co získat jako další

### Úplný aktuální list vlastnictví

Doplnit právní stav parcely 1 v k\.ú\. Uherský Brod 772984\. Číslo LV se nesmí odhadovat z tohoto WFS dotazu\.

Stav: k získání

[Oficiální místo získání](<https://dpn.cuzk.gov.cz/>)

## Důkazy

<a id="evidence-69bdf5adde6dc57a"></a>
### ev-ku

Podklad: src-ruian-ku · oddíl JSON features\[0\]\.attributes · Pole kod a nazev; SHA256 odpovědi 46e492ff408fe3d97dc19bdef5ccff082085c251e7ea73e44a438d1dbbebaf94

> kod: 772984; nazev: Uherský Brod

Ověřeno: 2\. 11\. 2026 · 11:34:00 UTC

<a id="evidence-d0a89da83072094a"></a>
### ev-identita

Podklad: src-wfs-parcela · oddíl wfs:member/cp:CadastralParcel\[@gml:id="CP\.2793846742"\] · cp:label a cp:nationalCadastralReference; SHA256 odpovědi 69937026b144d80eefd77ce4032266f73bdb88b1de5f0a802d96199a35fadfe6

> label: 1; nationalCadastralReference: 772984-1

Ověřeno: 2\. 11\. 2026 · 11:34:55 UTC

<a id="evidence-089da2d86d9b4867"></a>
### ev-geometrie

Podklad: src-wfs-parcela · oddíl CP\.2793846742 / cp:geometry · Polygon s uzavřeným vnějším prstencem, převod pořadí os EPSG:4326 do GeoJSON\. Hash původní odpovědi je uveden u identifikace\.

Ověřeno: 2\. 11\. 2026 · 11:34:55 UTC

<a id="evidence-82bc96981d148e13"></a>
### ev-mapa

Podklad: src-wms-map · oddíl Vrstva KN, výřez mapy · vyznačená oblast stránky · Vizuálně zkontrolovaný výřez obsahuje popisek parcely 1\. Bbox je zde délka, šířka; SHA256 obrazu 309c3752862b61c44cdc266126f57dadbe1fbd390e3773f4a9af83c9e651d86d

Ověřeno: 2\. 11\. 2026 · 11:36:43 UTC

<a id="evidence-b9ebafebf1c12a0b"></a>
### ev-vymera

Podklad: src-wfs-parcela · oddíl CP\.2793846742 / cp:areaValue · Hodnota a jednotka převzaty přímo z odpovědi, nikoli spočteny z obrázku či WGS84 polygonu\.

> 765; uom: m2

Ověřeno: 2\. 11\. 2026 · 11:34:55 UTC

## Zdroje

### src-ruian-ku — RÚIAN · katastrální území Uherský Brod

[RÚIAN · katastrální území Uherský Brod](<https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer/7/query?f=json&where=UPPER%28nazev%29+LIKE+%27%25UHERSK%C3%9D+BROD%25%27&outFields=%2A&outSR=4326&returnGeometry=false&returnCentroid=true&orderByFields=nazev+ASC%2Ckod+ASC&resultRecordCount=4>)

Jeden kandidát katastrálního území podle doslovného názvu; nejde o právní data\.

Poskytovatel: Český úřad zeměměřický a katastrální · Otevřeno: 2\. 11\. 2026 · 11:34:00 UTC · Stav dat: neuvedeno

### src-wfs-parcela — INSPIRE WFS · parcela 1 v k\.ú\. 772984

[INSPIRE WFS · parcela 1 v k\.ú\. 772984](<https://services.cuzk.gov.cz/wfs/inspire-CP-wfs.asp?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&STOREDQUERY_ID=GetParcel&UPPER_ZONING_ID=772984&TEXT=1&SRSNAME=http%3A%2F%2Fwww.opengis.net%2Fdef%2Fcrs%2FEPSG%2F0%2F4326&COUNT=2>)

Jeden přesný dotaz GetParcel: identifikátor, popisek, deklarovaná výměra a geometrie\. Bez vlastníků a omezení práv\.

Poskytovatel: Český úřad zeměměřický a katastrální · Otevřeno: 2\. 11\. 2026 · 11:34:55 UTC · Stav dat: neuvedeno

### src-wms-map — Katastrální mapa · jednotlivý výřez WMS

[Katastrální mapa · jednotlivý výřez WMS](<https://services.cuzk.gov.cz/wms/local-km-wms.asp?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=KN&STYLES=&BBOX=49.02708%2C17.642749%2C49.027986%2C17.643795&WIDTH=800&HEIGHT=600&FORMAT=image%2Fpng&TRANSPARENT=FALSE&CRS=EPSG%3A4326>)

Vrstva KN, WMS 1\.3\.0, EPSG:4326, obraz 800 × 600 pixelů\. Datum stažení nevyjadřuje datum měření hranice\.

Poskytovatel: Český úřad zeměměřický a katastrální · Otevřeno: 2\. 11\. 2026 · 11:36:43 UTC · Stav dat: neuvedeno

---

Počty nálezů popisují stav rešerše, nikoli bezpečnost nemovitosti. Datace jednotlivých podkladů se může lišit.
