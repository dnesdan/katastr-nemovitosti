# Syntetické dokumenty

Oba soubory jsou vytvořené pro testy. **Nejsou úředním výpisem, nepopisují skutečnou nemovitost a neobsahují osobní údaje.** Čísla jsou pouze zkušební tokeny; nesmějí sloužit jako vstup k dohledávání reálných vlastníků.

- `synthetic-lv-scan.pdf`: jedna obrazová stránka. Obsahuje označení částečného výpisu, modelovou parcelu a podíl. Nemá textovou vrstvu. Na obrázku je stránkování „Strana 1 z 2“.
- `synthetic-lv-attachments.pdf`: čitelný text a vložené XML s vlastním testovacím kořenovým elementem `SyntheticExample`. XML není vzorem oficiálního schématu NTŘ.

Skutečný místní průchod Poppler + Tesseract 2. listopadu 2026 rozpoznal sken, označení částečného výpisu a kandidáty `st. 12/3` a `1/8`. Prostředí mělo anglický model, což inspektor výslovně ohlásil. OCR zaměnilo text zápatí za „Strana 122“; inspektor ho neopravil odhadem. To ukazuje důvod povinné vizuální kontroly rozhodujících údajů.

Základní testy tyto binární soubory nepotřebují: malé PDF sestavují do dočasného adresáře pomocí pypdf. Fixture soubory jsou určeny pro opakovatelný ruční či integrační průchod, zejména volitelné OCR.
