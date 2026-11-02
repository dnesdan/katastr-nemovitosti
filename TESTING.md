# Ověření verze 0.1.0

Ověřeno 2. listopadu 2026. Výsledky rozlišují offline testy, živé veřejné dotazy, kontrolu prohlížečem a nezávislý průchod skillem. Přihlášené API KN, WSDP, Bank iD ani placené nákupy nebyly provedeny.

## Automatické testy

**161 testů prošlo**, bez přeskočených testů v ověřeném prostředí.

| Oblast | Testů | Co rozhoduje |
|---|---:|---|
| Datový model a JSON Schema | 27 | Identita parcely, přesné podíly, typy, datace, vazby, geometrie, selektivní veřejný export |
| CLI integrační průchody | 20 | Skutečné subprocess init/inspect/import/validate/report, nepřepisování originálů, výstupní cesty, soukromý režim, mapové sidecary |
| Dokumenty | 33 | PDF/XML/text, přílohy, částečnost, prázdné/zašifrované PDF, neověřené pečeti, OCR snapshot, limity a chyby |
| HTTP | 23 | Cache, rozestupy, blokace, přesměrování, velikost, čtení pomalé odpovědi, veřejné cíle |
| Zdrojové adaptéry | 29 | Kandidáti, přesná identita, GML/GeoJSON, řady parcel, WMS osy, obrazová validace, bezpečný zápis mapy a metadat |
| Report a export | 29 | HTML/Markdown/GeoJSON, citace, XSS, URL, CSP, úplný soupis objektů, přesné datace, rozsáhlá geometrie |

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 tools/verify.py
```

Runtime jádra nevyžaduje testovací závislosti. Dvě schema kontroly se bez `jsonschema` přeskočí; PDF testy vyžadují `pypdf`. Report je závislý pouze na standardní knihovně. Testy proběhly v Linuxu / Pythonu 3.12; zde se netvrdí spuštění na Windows nebo macOS.

Přibalený `tools/verify.py` ověřuje metadata skillu, odkazy, schema, čtyři případy včetně šablony, 28 zdrojů a samostatnost HTML. Oficiální kontrola skill-creator potvrdila platnost metadat balíčku.

## Živé veřejné služby

**Šest malých operací prošlo** přes veřejné oficiální zdroje. Přesné URL, časy, hash odpovědí a reprodukční operace jsou v [docs/live-source-checks.json](docs/live-source-checks.json).

| Operace | Výsledek |
|---|---|
| RÚIAN katastrální území | Uherský Brod, kód 772984 |
| RÚIAN adresa | Brněnská radnice, adresní místo 19095597 |
| RÚIAN budova | Stavební objekt 18945341 se skutečnou MultiPolygon geometrií |
| INSPIRE WFS GetParcel | Parcela 1, k. ú. 772984, reference 772984-1, identifikátor CP.2793846742 a polygon |
| WMS capabilities | Katastrální WMS 1.3.0, vrstva KN, EPSG:4326 |
| WMS výřez | Skutečný PNG 800 × 600, rozměry a obsah vizuálně zkontrolované |

Tím je ověřena konkrétní operace v konkrétním čase. Nejde o plošnou kontrolu každé položky katalogu, současného právního stavu, územního plánu nebo rizik parcely. Výsledek výměry v ukázce je deklarovaný atribut odpovědi WFS, nikoli nové měření.

## Skutečné OCR

Poppler + Tesseract zpracovaly [syntetický sken](tests/fixtures/documents/synthetic-lv-scan.pdf). Správně se přečetlo označení částečného výpisu a kandidáti `st. 12/3`, `1/8`. Prostředí nemělo český model; inspektor to výslovně oznámil. OCR chybně přečetlo „Strana 1 z 2“ jako „Strana 122“. Hodnota nebyla automaticky opravena odhadem. Vizuální kontrola v nezávislém průchodu správně rozlišila jednu fyzickou stránku a deklarovanou chybějící druhou stránku.

Regrese pro změnu originální cesty ověřila, že OCR renderuje přesně bajty použité pro SHA-256. Skutečné Poppler/Tesseract byly po opravě znovu použity; originál zůstal nezměněn. Tyto kroky se nemají zaměňovat za test všech druhů katastrálních listin nebo české rukopisné OCR.

## Vizuální a funkční kontrola

Tři veřejné ukázky byly otevřeny v místním Chromium **136.0.7103.25** (Playwright 1.52.0): desktop **1440 px**, mobil **390 px**. [Strojový výsledek](docs/ui-checks.json), [desktop screenshot](docs/nahled-reportu.png), [mobilní screenshot](docs/nahled-mobil.png).

Ověřeno:

- Žádné vodorovné přetečení, chyba JavaScriptu nebo neplatná vnitřní kotva.
- Všechny objekty zůstávají ve viditelném přehledu včetně jednotky bez geometrie.
- Výběr objektu, zoom/reset mapy, filtry a vyhledávání.
- **Nula externích síťových požadavků při otevření a ovládání reportu.**
- Tisk se zapnutým filtrem zahrnuje všechny nálezy i citované texty a po dokončení obnoví původní filtr.
- Tiskové výstupy mají 5 stran (Brno model), 5 stran (Uherský Brod) a 4 strany (Vysočina model).

Volitelná reprodukce vyžaduje vlastní instalaci Playwright a příslušný prohlížeč:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
python3 tools/check_ui.py --out docs/ui-checks.json
```

`--screenshots` obnoví zveřejněné náhledy. Prohlížeč otevírá pouze místní soubory; žádné přihlášené relace nejsou potřeba. Publikované screenshoty jsou skutečný render reportů, nikoli generovaná ilustrace.

## Nezávislé kontroly a opravy

Dva nezávislé code review průchody doplnily reprodukce mimo původní testy. Následné opakování potvrdilo opravy:

- Průběžný deadline čtení HTTP těla; dokumentace nepředstírá pevný celkový limit DNS a hlaviček.
- Neúplná odkazovaná GML kolekce se nevydává za celý polygon.
- Souběžně vzniklá mapa ani její metadata se potichu nepřepisují.
- Text OCR a hash vždy pocházejí ze stejných bajtů originálu.
- Falešný krátký PNG je odmítnut; JPEG má pravdivě omezený stav kontroly hlaviček, nikoli plné dekódování.
- Objekt bez geometrie nemizí ze smíšeného HTML.
- Kód katastru a registrační ID se neztrácejí z přehledu.
- Přesné časy a UTC offset zůstávají oddělené.
- Polygon s 20 002 body zůstává úplný v GeoJSON; vizuální limit je výslovně vysvětlen.

Samostatné review CLI opravilo mimo jiné označení plného soukromého reportu, `--force` mapy se sidecarem a ochranu původních vstupů. Žádný z uvedených reprodukovaných nálezů nezůstal při závěrečném retestu otevřený.

## Nezávislý průchod skillem

Další agent dostal pouze skill, syrový syntetický sken a běžnou otázku na nemovitost, podíl, omezení a příjezd. Bez předané očekávané odpovědi:

- Správně rozpoznal modelový dokument, částečnost a chybějící stránku.
- Uchoval surové OCR a samostatné vizuální ověření.
- Nevymyslel vlastníka ani vazbu podílu, právní omezení, přístup či geometrii.
- Vytvořil validovaný případ, 12 nálezů, 8 důkazů a konkrétní další kroky.
- Připravil HTML, Markdown a tiskový výstup; ověřil desktop/mobil/tisk bez sítě.

Jde o jeden nezávislý průchod obtížným dokumentovým případem. Seznam zadání pro 14 krajů je plán rozšířeného ověření, nikoli 14 dokončených prověrek.

## Co se netvrdí

Neproběhlo přihlášení Bank iD, platba, provoz API KN/WSDP, kryptografická validace pečetí, úplný NTŘ parser ani automatická právní prověrka všech zdrojů. PDF parser má aplikační limity; pro nedůvěryhodné velké dávky je vhodná další procesní izolace a limity prostředků. Mapový výsledek není geodetické vytyčení. Lokální ověření nespouštělo GitHub Actions a repozitář neobsahuje CI workflow.
