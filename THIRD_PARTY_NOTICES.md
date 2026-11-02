# Původ a externí práva

Vlastní implementace, dokumentace a syntetické příklady jsou pod MIT licencí repozitáře.

## Převzatý kód

`http_client.py` a části WMS/RÚIAN postupů v `sources.py` navazují na MIT projekt [dnesdan/pamet-krajiny](https://github.com/dnesdan/pamet-krajiny), Copyright (c) 2026 Contributors to the Czech research skills. Licenční text je zachován v LICENSE. Implementace byla rozšířena a znovu testována pro tento balíček.

## Metodická návaznost

Rodokmen (sarsonj), Paměť rodu (thejanhromek) a Dějiny domu (vzoha) poskytly zkušenosti popsané v references/navaznosti.md a původním auditu všech PR. Jejich licenčně vyňaté soubory playbook.md nebyly převzaty. Odkaz na otevřený PR neznamená, že jeho funkce je zde přibalena nebo vydána upstreamem.

## Veřejná data

Skutečný příklad Uherského Brodu vychází z malých veřejných odpovědí ČÚZK: RÚIAN, INSPIRE WFS a WMS. U každého zjištění je poskytovatel, URL, lokátor a čas. Data a mapové podklady se řídí podmínkami poskytovatele; MIT programu jim neuděluje novou licenci. Veřejný příklad neobsahuje vlastníky ani soukromé listiny. Mapový rastr není přibalen; report kreslí citovanou parcelní geometrii.

Další položky katalogu jsou odkazy a vlastní stručné popisy, nikoli zrcadla databází. Před přebíráním větších dat, fotografií a dokumentů ověřit konkrétní licenci a rozsah povoleného použití.

## Závislosti

Jádro a report mají jen Python standardní knihovnu. Volitelný pypdf má vlastní licenci. Testovací jsonschema, PyYAML, ReportLab, Playwright, Poppler a Tesseract nejsou vendorizované. Syntetické PDF vytvořil generátor tools/build_examples.py; vložený podmnožinový font DejaVu Sans se řídí licencí DejaVu (viz [LICENSES/DejaVu.txt](LICENSES/DejaVu.txt)). Testovací PDF nepřebírají skutečné listiny ani osobní údaje.
