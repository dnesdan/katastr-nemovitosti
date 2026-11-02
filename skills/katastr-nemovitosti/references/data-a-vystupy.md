# Data a výstupy

## Jeden případ, více časových stavů

Použít `property-case/1.0` a přibalený `schema.json`. Strukturu ověřuje JSON Schema, vazby a významové podmínky navíc `katastr.py validate`. Validace struktury nikdy nepotvrzuje věcnou správnost údajů.

| Kolekce | Obsah |
|---|---|
| case | Jedinečný případ, účel, lokalita, rozhodné datum, model/skutečná rešerše, soukromé/zkontrolované sdílení |
| objects | Parcela, budova, jednotka, adresa či území; identifikátory a volitelná GeoJSON geometrie |
| sources | Skutečně použitý zdroj, URL, poskytovatel, datum přístupu, datum dat a rozsah |
| documents | Hash originálu, typ, stránky, samostatné časy, úplnost, stav pečeti a soukromá inspekce |
| evidence | Konkrétní pozorování s lokátorem a odkazem na právě jeden zdroj nebo dokument |
| findings | Doložený nález, rozpor či neuzavřená otázka; význam pro záměr a další krok |
| rights | Orientované vztahy oprávněných/zatížených objektů; přesný zlomek a důkazy |
| next_documents | Dokument, proč jej potřebujeme, jak jej získat a kterou otázku řeší |
| research_log | Co se opravdu zkusilo, s jakým výsledkem, co je pouze plán |

Identifikátory zůstávají stabilní při doplňování případu. Parcelní identita je trojice kód katastru + číselná řada + číslo, nikoli pouhé číslo nebo adresa. Souřadnice mají pořadí `[longitude, latitude]`, EPSG:4326. Nekonvertovat neznámý systém pouhým prohozením os. Polygon musí mít uzavřené prstence; zachovat otvory a více částí.

## Příklad důkazu z dokumentu

```json
{
  "id": "dukaz-pristup",
  "document_id": "listina-pristup",
  "locator": {"page": 2, "section": "Článek III", "note": "Rozsah práva a označení zatížené parcely"},
  "quote": "Přesný krátký přepis relevantního místa po kontrole originálu.",
  "observed_at": "2026-11-02",
  "public": false
}
```

To je vzor struktury, nikoli citace skutečné listiny. Záznam `listina-pristup` musí existovat. Závěr připojit až po přečtení; přidat mu `evidence_ids: ["dukaz-pristup"]`. U mapy uvést vrstvu, ID prvku, souřadnicový systém a datum v lokátoru. Snímek celé webové stránky nestačí, pokud nelze určit konkrétní doklad.

## Čas a úplnost

- `register_state_at`: okamžik evidovaného stavu podle dokumentu.
- `issued_at`: vydání dokumentu.
- `imported_at`: místní import souboru.
- `accessed_at` a `data_date`: přístup k webovému zdroji a čas jeho dat.
- `case.as_of`: rozhodné datum přehledu, ne záruka, že každý zdroj je stejně nový.

Nedoložený čas ponechat prázdný a vysvětlit mezeru. Samotný soubor z dneška nedokazuje dnešní právní stav. Inspekce automaticky nepotvrzuje `complete` ani `verified` pečeť. Tyto hodnoty vyžadují samostatně doloženou kontrolu.

## Stavy a naléhavost

`status` vyjadřuje stav důkazu: supported / conflict / missing / not_covered / unverified. `severity` vyjadřuje význam otázky pro konkrétní záměr: high / medium / info. Nevyvozovat druhé pole mechanicky z prvního. Doložená existence záplavové vrstvy není stejný závěr jako nevhodnost koupě.

`next_documents` musí odkazovat na existující nález/otázku. Důvod nemá být „pro jistotu“, ale konkrétní: vymezení služebnosti, podíl společných částí, změna parcely nebo časový stav.

## HTML, Markdown, mapa a PDF

HTML je samostatný offline dokument s mapou vlastní geometrie, filtrem nálezů, zdroji a rozbalitelnými důkazy. Geometrická mapa nevkládá externí dlaždice, takže nezveřejňuje adresu síťovým požadavkem při otevření. Snímek veřejné WMS lze získat zvlášť pomocí `fetch map`; je nutné uchovat jeho metadata a podmínky použití. V první verzi se rastrový snímek automaticky nevkládá do geometrické mapy reportu.

Markdown slouží pro přenos a textovou kontrolu. GeoJSON obsahuje jen objekty, které mají geometrii; chybějící geometrii nevymýšlet. PDF vytvořit tiskem HTML. Ověřit poslední stránky, dlouhé citace, popisky a úplnost otevřených detailů. HTML s aktivním filtrem musí v tisku zachovat všechny nálezy a důkazy.

## Sdílení

Výchozí případ je soukromý. Pro veřejný výběr je potřeba obsahová kontrola `case.sharing = public-reviewed` i označení jednotlivých položek `public = true`. Filtr nepřepisuje soukromý vstup. Odstraní nevybrané zdroje/dokumenty/důkazy a závislé závěry, interní inspekce a výzkumný deník. Neanonymizuje texty, adresy ani geometrii. Zvlášť prověřit název a souhrn případu, všechny objekty a vybrané citace. Originály a přílohy se automaticky neexportují.

Porovnání dvou verzí `compare` ukazuje změny uložených záznamů stejného případu; samo o sobě nedokazuje, že došlo k právnímu převodu.
