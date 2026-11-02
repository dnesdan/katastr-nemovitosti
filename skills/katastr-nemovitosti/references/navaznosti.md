# Návaznosti a původ postupů

Katastr a souvislosti rozšiřuje české badatelské skilly o současnou identitu nemovitostí, dokumenty a územní podklady. Formát `property-case/1.0` je samostatný; nepředpokládat automatický import historických dossierů.

| Projekt | Použitelná návaznost |
|---|---|
| [Paměť krajiny](https://github.com/dnesdan/pamet-krajiny) | Historické mapy, voda, cesty, zaniklá místa. Síťové a WMS postupy tohoto projektu navazují na jeho MIT jádro. |
| [Dějiny podniku a řemesla](https://github.com/dnesdan/dejiny-podniku-a-remesla) | Starší provozy v areálu, výrobní historie, rozdíl podnik/provozovatel/vlastník pozemku. |
| [Dějiny domu](https://github.com/vzoha/dejiny-domu-skill) | Historie držby, gruntovní a pozemkové knihy, číslování, archivní mapy, místní zdroje. |
| [Rodokmen](https://github.com/sarsonj/rodokmen-skill) | Archivní portály a přesné citace snímků; dějiny rodiny, pokud jsou součástí zadání. |
| [Paměť rodu](https://github.com/thejanhromek/pamet-rodu) | Oddělení tvrzení a důkazu, konfliktů a pracovního/sdíleného výstupu. |
| [Rodová paměť](https://github.com/dnesdan/rodova-pamet) | Propojení rodinného bádání s doloženým historickým vlastnictvím. |

Předat jen ověřenou identitu, souřadnice s původem, čas a konkrétní důkazy. Současné číslo parcely nemusí mít historickou kontinuitu. Dřívější továrna je podnět k prověření starých zátěží, nikoli automatický důkaz kontaminace.

## Zkušenosti z upstream PR

Podkladem je [audit všech 25 PR původních projektů z 2. listopadu 2026](https://github.com/dnesdan/pamet-krajiny/blob/main/UPSTREAM.md) a jeho strojový seznam. Otevřený PR není vydaná funkce. Pro tento skill mají konkrétní význam:

- Rodokmen #7, #8, #22: neosiřelé vazby, konkrétní lokátor a správný snímek.
- #10: uživatelský případ mimo instalovaný balíček; aktualizace nesmí přepsat výzkum.
- #19: rozlišení místa a objektu, ověřená geometrie.
- #26, #42, #52, #59: přenosný skill a správné metadatové soubory.
- #46, #47: uchovat stav výzkumu a rozlišit zablokovaný zdroj od prázdného výsledku.
- #53, #60: sdílené omezení dotazů, cache, přenositelnost Windows/POSIX.
- #62: přechod k historickým pramenům podle vrchnosti a fondu.

Tento balík nepřebírá genealogické webové aplikace ani licenčně vyňaté `playbook.md`. Kód odvozený z Paměti krajiny zachovává MIT licenci. Licence programu nepokrývá externí mapy, snímky a dokumenty. Historické klienty upstreamu spouštět až po ověření aktuálních podmínek a konkrétního nástroje.
