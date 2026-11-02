# Příklady

`uhersky-brod-verejna-data` je malá skutečná rešerše veřejné identity a geometrie parcely. Právní stav a územní rizika v ní nejsou prověřeny; výstup je explicitně nechává otevřené.

`brno-byt-model` a `vysocina-pozemek-model` jsou smyšlené učební případy. Každý HTML/Markdown výstup je označuje. Podklady v `podklady/` jsou vlastní syntetické dokumenty, nikoli úřední výpisy nebo zjištění o skutečných vlastnících.

Každý případ má JSON, HTML, Markdown a GeoJSON. HTML funguje po otevření místního souboru, bez serveru a bez síťových požadavků. Tisk otevře úplnou podobu s důkazy. Modelové podklady a exporty lze obnovit pomocí `python3 tools/build_examples.py`; pro tuto vývojovou operaci jsou potřeba ReportLab a lokální TTF s češtinou (KATASTR_DEMO_FONT). Generátor neprovádí žádné internetové dotazy.

Živé zdrojové operace jsou odděleně zaznamenány v `docs/live-source-checks.json`. Seznam scénářů pro 14 krajů v `prenositelnost.md` je plán dalších zkoušek, nikoli 14 hotových prověrek.
