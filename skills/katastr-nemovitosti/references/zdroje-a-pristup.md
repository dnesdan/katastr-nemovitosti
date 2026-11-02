# Zdroje, přístup a územní směrování

Stav dokumentace ověřen 2. listopadu 2026. Strojově čitelný [katalog 28 zdrojů](source-catalogue.json) rozlišuje vlastní adaptér, ruční průzkum a dokument dodaný uživatelem. Živý úspěch jednoho dotazu neověřuje každou funkci portálu ani jeho dostupnost v budoucnu.

## Pořadí práce

1. RÚIAN pro kandidáty a vazby adresy/stavby/území; potvrdit správný objekt.
2. ČÚZK WFS pro přesnou identitu a geometrii parcely, WMS pro mapový výřez.
3. Dodaný LV a relevantní listiny pro konkrétní práva; rozlišit objekt výpisu a čas stavu.
4. Podle cíle územní plán, sítě, voda, ochrana přírody a památek, geologie a další témata.
5. Historické skilly až po ověření současné identity; historické číslo nemusí označovat dnešní parcelu.

Používat kód katastrálního území, obec, ORP a kraj skutečné nemovitosti. Žádný český kraj není výchozí a žádný místní geoportál není celostátní.

## Čtyři přístupové režimy

| Režim | Použití |
|---|---|
| Veřejné podporované rozhraní | Přibalené malé klienty; limity, cache a záznam původu |
| Interaktivní web | Ruční průzkum podle pravidel portálu; např. Nahlížení do KN nelze tímto klientem těžit |
| Registrace/placený výstup | Uživatel získá přesně požadovaný dokument; AI neprovádí jeho Bank iD přihlášení |
| Oprávnění k dokumentu | Stavební spis, soukromé smlouvy či jiné podklady: nejprve ověřit, zda je má uživatel k dispozici |

[Nahlížení](https://nahlizenidokn.cuzk.gov.cz/) uvádí interaktivní použití a zákaz automatizovaného získávání. [API KN](https://api-kn.cuzk.gov.cz/PodminkyUzivani) má vlastní registraci, ApiKey a podmínky; neobsahuje osobní údaje. Tento balík nemá přihlášený konektor. [DPN](https://dpn.cuzk.gov.cz/) umožňuje jednorázové výstupy, vybrané z nich s prokázáním identity. NIA přihlášení a cena výstupu jsou samostatné otázky. Žádný krok nesmí naznačovat, že Bank iD zpřístupní každý cizí dokument.

## Výběr podle tématu

| Téma | Zdroje | Co hledat a čím výsledek omezit |
|---|---|---|
| Identita a mapa | RÚIAN, služby ČÚZK | Potvrzená vazba objektů; polygon místo pouhého adresního bodu; přesnost mapy |
| Práva | LV, sbírka listin | Přesný objekt, čas, oddíl, záznam, řízení a listina; práva ve prospěch i zatížení |
| Územní plán | NGÚP, obec, ORP, kraj | Účinné úplné znění a změny; text i mapa; podmínky konkrétního záměru |
| Přístup a sítě | ČÚZK, DMVS/DTM, obec, správci | Fyzická cesta a právní titul odděleně; průběh sítě odděleně od kapacity a souhlasu |
| Povodně | HEIS/VÚV, příslušný vodoprávní podklad | Úředně vyhlášená zóna versus model a pojišťovací mapa; datace a rozsah |
| Příroda/památky | AOPK, NPÚ | Plocha ochrany i konkrétní vyhlášení; individuální versus územní ochrana |
| Podloží a zátěže | ČGS, SEKM | Evidované jevy a jejich podrobnosti; neexistence záznamu není důkaz bezpečnosti |
| Zemědělská půda | SPÚ, VÚMOP, LPIS | BPEJ, užívání, bloky, společná zařízení, odvodnění; vlastnictví a užívání odděleně |
| Okolí | Hlukové mapy MZd, EIA/SEA, úřední desky | Pokrytí a rok modelu; stav záměru, ne pouze jeho výskyt ve vyhledávání |
| Internet a energie | ČTÚ, dodaný PENB | Období vykázaných dat, konkrétní adresa; správná budova a verze průkazu |

## Důležité aktuální rozdíly

- [MMR](https://mmr.gov.cz/cs/ministerstvo/stavebni-pravo/digitalizace-uzemniho-planovani) uvádí povinné používání NGÚP až od 1. července 2027. V současném přechodném období hledat i lokálně. Ani později nepovažovat výpadek portálu za neexistenci plánu.
- [DMVS](https://cuzk.gov.cz/DMVS/Poskytovani-dat.aspx) má veřejné mapy, dotazy a některé datové balíčky. Veřejné WFS území správců není úplná otevřená vektorová kopie všech sítí. Další výdeje mohou vyžadovat registraci či doložený účel.
- [ČÚZK](https://www.cuzk.gov.cz/Aplikace-DP-do-KN/Aplikace-DP-do-KN/Archiv-DP.aspx) oznámil na 4. listopadu 2026 novou sestavu LV NTŘ 3.0, u společného výstupu s XML přílohou PDF. Ověřit skutečný formát souboru; zdejší XML inspekce není úplný NTŘ parser.
- [MPO](https://mpo.gov.cz/cz/energetika/uspory-energie/uspory-v-praxi/prukazy-energeticke-narocnosti-budov/prukaz-energeticke-narocnosti-budovy--277417/) uvádí, že individuální PENB nejsou univerzálně veřejná data. Vyžádat relevantní originál od vlastníka.

## Při problému se zdrojem

Zapsat přesný zdroj, dotaz, čas a důvod. Použít `blocked`, `error`, `empty` či `planned` podle skutečnosti. Alternativní oficiální zdroj lze použít, pokud má vlastní veřejný přístup a nejde o obcházení odmítnutého oprávnění. Výsledky přihlášených služeb ani cookies nesdílet do veřejného reportu.

Jazyk výstupu: „Tento zdroj se nepodařilo ověřit“ nebo „vrstva toto území nepokrývá“, nikoli „zde žádné omezení není“.
