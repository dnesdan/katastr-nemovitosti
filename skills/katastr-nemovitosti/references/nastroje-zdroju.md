# Nástroje pro veřejné zdroje

## Obsah

- [Rozsah a přístup](#rozsah-a-přístup)
- [Identifikace adresy a budovy](#identifikace-adresy-a-budovy)
- [Přesná parcela a geometrie](#přesná-parcela-a-geometrie)
- [WMS vrstvy a mapový výřez](#wms-vrstvy-a-mapový-výřez)
- [Síťové chování a chyby](#síťové-chování-a-chyby)
- [Rozšíření a oficiální dokumentace](#rozšíření-a-oficiální-dokumentace)

## Rozsah a přístup

Modul `scripts/sources.py` poskytuje malé čtecí adaptéry. Získává kandidáty RÚIAN, budovu podle kódu, jednu přesně identifikovanou parcelu přes WFS a jednotlivé mapové výřezy WMS. Vrací původ dotazu, skutečný čas získání odpovědi, hash odpovědi a informaci o použití cache. Žádný výsledek sám neobsahuje právní prověrku. Záznam převést do případu až po kontrole identity a obsahu.

Webové Nahlížení se automaticky nestahuje. Umožňuje interaktivní použití a pro automatizaci odkazuje na oficiální API. API KN, WSDP a přihlašování nejsou součástí tohoto síťového klienta. Soukromé údaje doplnit z uživatelova výpisu a listin; nepředávat přihlašovací údaje ani ApiKey do veřejného klienta.

## Identifikace adresy a budovy

Základ služby: `https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer`.

```python
from http_client import HttpClient
from sources import ruian, ruian_building

client = HttpClient(cache_dir="pracovni-pripad/cache")
kandidati = ruian(client, "Uherský Brod", kind="cadastral", limit=5)
adresy = ruian(client, "Dominikánské náměstí 196/1", kind="address", limit=5)
# Nevybírat první výsledek automaticky. Po ověření adresy použít skutečnou
# hodnotu attributes.stavebniobjekt:
# budova = ruian_building(client, str(overeny_kod))
```

Podporované druhy pro `ruian`:

| `kind` | Výsledek | Co z něj nevyvozovat |
|---|---|---|
| `address` | Adresní bod, kód a vazba na stavební objekt | Rozsah vlastnictví ani hranici parcely |
| `cadastral` | Kandidáti katastrálních území | Že stejné parcelní číslo v jiné oblasti označuje stejný objekt |
| `municipality` | Kandidáti obcí a jejich správní identifikátory | Totožnost dnešního a historického území |
| `part` | Kandidáti částí obcí | Samostatnost stavby či jednotky |

Dotaz je doslovná část názvu/adresy, bez zástupných znaků, 2–200 znaků. Maximum je 50 kandidátů. `truncated: true` znamená, že výčet není úplný a zadání je třeba zúžit. `selected` zůstává `null`. Adresní bod není parcelní polygon; u obce a katastru je vrácený bod jen reprezentativním bodem.

`ruian_building(client, code, refresh=False)` bere ověřený číselný kód jako řetězec. Vrací zveřejněné atributy a případnou GeoJSON geometrii v pořadí délka, šířka. Pokud služba nepotvrdí souřadnicový systém nebo vrátí jiný kód, nástroj skončí chybou. Přítomnost stavebního objektu v RÚIAN není dokladem povoleného využití či titulu k vlastnictví.

## Přesná parcela a geometrie

```python
from sources import parcel

# Šestimístný kód katastru nejprve ověřit v RÚIAN.
# Příklad obecného volání: hodnoty dosadit z konkrétního zadání.
data = parcel(client, cadastral_code=overeny_kod_katastru,
              number=overene_parcelni_cislo, series="land")
```

`series="building"` označuje stavební číselnou řadu (`st.`), `series="land"` pozemkovou. Samotné číslo zůstává řetězcem, například `99/3`. Nedovozovat číselnou řadu jen z toho, zda na pozemku stojí budova.

Adaptér používá oficiální WFS 2.0 `GetParcel` s parametry `UPPER_ZONING_ID` a `TEXT`. Požadavek omezí na dva prvky; vícenásobný výsledek zůstává k rozlišení. Uchovává vrácenou referenci parcely, identifikátor prvku, popisek, deklarovanou výměru a její jednotku, čas odpovědi a případnou geometrii.

Parser zpracuje přímé GML polygony i plošné části s lineárními prstenci, včetně děr a více polygonů. Z deklarovaného EPSG:4326 přehodí oficiální pořadí os do GeoJSON délka, šířka; neprovádí reprojekci. Neznámý CRS, křivková geometrie, odkazovaný nebo nepodporovaný člen kolekce vytvoří `geometry: null` a vysvětlení. Rozpoznaná část se nikdy nevydává za úplný polygon. Neuzavřený prstenec, chybné souřadnice nebo nekonzistentní počty vyvolají chybu. Z geometrie se nepočítá náhradní právně závazná výměra.

Výstup WFS nemá vlastníky ani úplný právní stav. Obsahuje mapové podklady, jejichž přesnost závisí na původu měření. Geometrie je vhodná pro orientační průniky a dohledání dalších zdrojů; pro vytyčení hranice je potřeba odpovídající geodetický postup.

## WMS vrstvy a mapový výřez

```python
from sources import wms, wms_map, CADASTRAL_WMS_URL

vrstvy = wms(client, CADASTRAL_WMS_URL, version="1.3.0")
# Vybrat přesný název z vrstvy.layers. Bbox níže je pouze vzor tvaru.
# wms_map(client, CADASTRAL_WMS_URL, "KN", bbox=[min_lon,min_lat,max_lon,max_lat],
#         out="pracovni-pripad/mapa.png", width=960, height=640,
#         version="1.3.0", crs="EPSG:4326")
```

Vrácené capabilities obsahují názvy a popisy vrstev, podporované souřadnicové systémy, styly a obrazové formáty. CRS a styly se správně dědí z nadřazené vrstvy. Bounding box ve výsledku capabilities je výslovně označen jako nativní pořadí os služby.

`wms_map` přijímá bbox zeměpisných souřadnic vždy jako `min_lon,min_lat,max_lon,max_lat`. Pro WMS 1.3.0 a EPSG:4326 pořadí v požadavku sám obrátí podle standardu. Pro EPSG:5514 je podporováno pouze WMS 1.1.1 a vstupní easting/northing v metrech. Systém se nezjišťuje odhadem podle velikosti čísel.

Nástroj před stažením prověří existenci vrstvy, podporu CRS a formátu. Obrázek je omezen na 16–1024 pixelů na rozměr. Uloží PNG/JPEG a sousední `mapa.png.json` se zdrojem, bbox, datem stažení a hashem. Oba soubory připraví před publikací; výhradní vytvoření cílových cest chrání i před souborem vzniklým během stahování. Při kolizi druhého cíle odstraní pouze vlastní nově vytvořený první soubor. Nejde o atomickou transakci dvou cest vůči pádu procesu; nikdy však nepřepisuje existující cíle. Vrácenou HTML chybu nebo XML hlášku nevydává za obrázek.

U PNG se kontrolují délky chunků, CRC, povinné části, omezený zlib pixelový stream a řádkové filtry. U JPEG jsou kontrolovány pouze hlavičky rámce/skenu, markery a rozměry; úplné dekódování obrazových dat neprovádí standardní knihovna tohoto nástroje. Pole `image_validation` tento rozdíl zachovává. JPEG před použitím ještě otevřít v dekodéru nebo vizuálně ověřit. Ani strukturální validace PNG nenahrazuje kontrolu, zda mapa skutečně zobrazuje požadované místo a správnou vrstvu.

Mapu případně vložit do reportu lokálně až po ověření licence, datace a rozsahu. Samotný HTML report nepřipojuje živé mapové služby. Obrázek bez data vrstvy neoznačovat jako aktuální stav v terénu.

## Síťové chování a chyby

Klient používá HTTPS a ověření TLS, zachovává systémovou proxy a nevkládá cookies ani přihlašovací hlavičky. Má výslovný seznam známých domén; příležitostný další oficiální server lze přidat přes `HttpClient(allowed_hosts=...)` až po ověření konkrétního zdroje a podmínek. Seznam je přesný, nikoli pravidlo „všechny poddomény“. Přesměrování na jiný host se nepřijímá automaticky.

Pro další hosty i běžný přístup se ověřuje, že DNS nevrací soukromé nebo zvláštní adresy. Pokud prostředí umožňuje DNS pouze přes zděděnou HTTPS proxy, tato cesta se připouští jen pro vestavěné oficiální hosty. Jde o omezený klient veřejných služeb, nikoli náhradu síťové izolace prostředí.

| Situace | Chování |
|---|---|
| Úspěšná úplná odpověď | Uložit cache a původní čas získání; standardní TTL 24 hodin |
| `refresh=True` | Vyžádat novou odpověď, ale respektovat přístupové blokace |
| HTTP 401/403 | Zastavit, uložit čekací stav hostu; nezkoušet obcházení přihlášení |
| HTTP 429/503 | Zastavit, respektovat `Retry-After`, žádné automatické opakování |
| Neplatná či částečná odpověď | Chyba; neukládat jako úspěšný výsledek |
| Platný prázdný výsledek | Označit `empty` pouze pro tento dotaz, nikoli „nemovitost bez rizika“ |
| Vyčerpaný čas, velikost nebo DNS | Chyba a neověřený stav dané kontroly |

Výchozí timeout je 25 sekund, limit těla 8 MB, minimální odstup mezi požadavky na host 1 sekunda. Tělo standardní HTTP odpovědi se čte po jednotlivých bufferech (`read1`) a před každým čtením se dostupnému socketu nastaví zbývající časový rozpočet. Nejde o tvrdý strop celého volání: DNS, navázání spojení a zpracování hlaviček závisejí také na systému a timeoutu transportu. Klient nevytváří vlákna pokračující po návratu chyby. Cache a hostový zámek fungují mezi procesy. Hostový zámek se nemaže jako způsob vynucení přístupu. Žádné automatické stránkování, hromadné stahování parcel nebo opakování blokovaných požadavků není implementováno.

## Rozšíření a oficiální dokumentace

Ověřeno při přípravě 2. listopadu 2026. Změny portálů kontrolovat před větším použitím.

- [RÚIAN REST – vrstvy a rozhraní](https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer)
- [Vrstva adresních míst](https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer/1)
- [Vrstva stavebních objektů](https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer/3)
- [Mapový server ČÚZK a seznam služeb](https://services.cuzk.gov.cz/)
- [WFS Parcely – popis dotazů a CRS](https://services.cuzk.gov.cz/doc/inspire-cp-download.pdf)
- [WMS 1.3.0 – oficiální specifikace OGC](https://portal.ogc.org/files/?artifact_id=14416)
- [API KN – podmínky použití](https://api-kn.cuzk.gov.cz/PodminkyUzivani)
- [Nahlížení – podmínky a odkaz na API](https://nahlizenidokn.cuzk.gov.cz/)

API KN může být budoucím samostatným adaptérem po vyřešení držitele klíče, licenčních podmínek a provozních testů. Tento balík předání klíče ani přihlášení nepožaduje a netvrdí, že autentizované rozhraní otestoval.
