# Automobilių serviso darbų ir užsakymų valdymo informacinė sistema

Mokomasis VISK prototipas su kliento, vadybininko, mechaniko ir vadovo rolėmis. Šio paketo kodo ir testavimo atskaitos data – 2026-10-16. Pinigai nepervedami, tikri SMS bei el. laiškai nesiunčiami.

## Paleidimas

Programai reikalingas Python 3. Testavimui naudotas Python 3.13.5; serverio paleidimui papildomų Python paketų nereikia. Išskleiskite archyvą ir komandas vykdykite kataloge `serviso_sistema`.

```text
python main.py
```

Windows aplinkoje taip pat galima paleisti `paleisti_windows.bat`. Naršyklėje atverkite `http://127.0.0.1:8765`; terminalą palikite veikiantį. Darbą baigus – Ctrl+C. Užimtam prievadui galima pasirinkti kitą:

```text
python main.py --port 8766
```

Pateiktame `servisas.db` jau yra išplėsti demonstraciniai duomenys. **Jo netrinkite norėdami atnaujinti programą.** Paleidimas į esamą DB įdiegia vizito kliento nekintamumo trigerį; istorinių pranešimų neperrašo. Neradusi DB programa sukuria pradinį mažesnį duomenų rinkinį, kuris nėra pateiktos išplėstos bazės pakaitalas.

Prieš atnaujindami savo kopiją sustabdykite serverį ir išsisaugokite turimą DB. Jei jūsų DB yra jūsų įvestų duomenų, nekeiskite jos šio paketo demonstracine baze. Ankstesnių jau padarytų neteisingų vizito kliento pakeitimų šis naujos apsaugos trigeris atgaline data netaiso.

## Demonstracinės paskyros

Visų penkių mokomųjų paskyrų slaptažodis – `Demo2026!`.

| Prisijungimas | Rolė |
|---|---|
| klientas | Klientas |
| vadybininkas | Vadybininkas |
| mechanikas | Mechanikas A |
| mechanikas2 | Mechanikas B |
| vadovas | Vadovas |

## Šio paketo pataisos

Esamo vizito klientas nekinta: redaguojant pasirenkamas tik kitas to paties kliento automobilis. Taisyklė tikrinama sąsajoje, HTTP serveryje ir DB. Naujos versijos juodraštis po pirmos sąmatos atmetimo palieka užsakymą „Derinamas“. Pirmas juodraštis ir jau vykdomo remonto papildymai išlaiko savo taisykles.

Pranešimo būsena rodoma „Perduotas tiekėjui (imitacija)“. Paieškai neradus atitikmenų rodoma „Pagal paieškos kriterijus įrašų nerasta.“, o visiškai tuščiam sąrašui lieka „Įrašų dar nėra.“ Kuriant paskyrą vartojamas „Pradinis slaptažodis“.

`users.name` ir `orders.closing_note` buvo esami laukai. Uždarymo pastaba privaloma; ji nepakeičia atskiro automobilio perdavimo įrašo. `payments.recorded_by` nurodo internetinį mokėjimą inicijavusį klientą arba vietinį mokėjimą registravusį darbuotoją.

## Automatinės patikros

```text
python test_system.py
node test_ui.js
python test_regressions.py
```

UI testams naudojami tik standartiniai Node.js moduliai (`npm install` nereikia). Dokumentuotoje aplinkoje naudotas Node.js v22.16.0.

Visą funkcinį rinkinį du kartus paleidžia:

```text
python run_checks.py --runs 2
```

| Rinkinys | Vieno paleidimo rezultatas |
|---|---:|
| HTTP ir DB (`test_system.py`) | 457/457 |
| UI logika (`test_ui.js`) | 33/33 |
| Papildomi HTTP/DB regresiniai atvejai (`test_regressions.py`) | 14/14 |
| **Funkcinis rinkinys** | **504/504** |

Abiejų 2026-10-16 paleidimų rezultatai išsaugoti `test_runs/20261016T082900Z/run1` ir `run2`. `summary.json` pateikia rezultatų grupes, laiką, aplinką, programos failų SHA-256 bei demonstracinės DB kontrolines sumas. Tai du to paties rinkinio paleidimai, ne 1008 skirtingi testai. RG atvejis gali turėti kelis teiginius ir tarpinius HTTP veiksmus; skaičiuojami testų ataskaitų įrašai, ne kiekviena kodo eilutė.

Užsakymų paieškos testas vykdo tikrą sąrašo filtrą su keliais įrašais. Tikrinamas skaitinis ID, visas `U-0001`, automobilis, klientas, neradimo atvejis ir paieškos išvalymas. Klientų paieška tikrinama pagal vardą ir telefoną. Testų nuorodos į reikalavimus pataisytos, keturių rolių prisijungimą tiesiogiai tikrina RG-13.

## Chromium atvaizdavimo ir klaviatūros pasiekiamumo patikra

Tai papildomas, **nuo funkcinio rinkinio atskirtas** bandymas. Reikalingas Playwright ir Chromium; tai nėra pačios programos priklausomybės.

```text
python -m pip install playwright
python -m playwright install chromium
python run_checks.py --runs 2 --browser
```

Jei naudojamas atskirai įdiegtas Chromium, jo vykdomąjį failą galima nurodyti aplinkos kintamuoju `BROWSER_EXECUTABLE`.

Dokumentuotoje Linux aplinkoje Chromium 144.0.7559.96 abiejuose paleidimuose praėjo **24/24** patikros (12 grupių po du pločius). Naudoti 1360×960 ir 390×844 px langai. Vienam paleidimui išsaugotas 81 atvaizdo matavimas, JSON ir PNG.

Naršyklė atvaizduoja tikrus programos HTML/CSS/JS, o skaitymui gauna iš realiai paleisto HTTP serverio su laikina DB užfiksuotus duomenis. Tikrinami matmenys, aktyvių valdiklių pasiekiamumas Tab, dialogų uždarymas Escape, paieškos įvedimas bei lentelių slinkimas rodykle. **Šiame atvaizdavimo teste naršyklės rašymo užklausos sąmoningai nevykdomos ir niekada neapsimetama, kad jos įrašytos.** HTTP/DB efektus tikrina atskiri funkciniai testai.

Pilnas aptarnavimo procesas vien klaviatūra per tiesioginę naršyklės ir serverio jungtį dar nepatvirtintas. NF-03 pagrįstas tik aprašytoje atvaizdavimo ir valdiklių pasiekiamumo apimtyje; tai nėra visų prieinamumo kriterijų sertifikavimas ar naujas Windows bandymas. Likusio bandymo planas – `NF03_rankine_patikra.md`.

## Duomenys ir įrodymai

Pateikta demonstracinė DB nepakeista: 23 užsakymai, 26 sąmatų versijos, 23 darbai, 24 mokėjimai, 62 pranešimai, 63 siuntimo bandymai, 268 žurnalo įrašai. Demonstracinės DB SHA-256:

```text
d520c70c1ba10e9b5dac21c38897f6685b72353ad01dc2ff10f0ff8fdc1cd967
```

Testai naudoja laikinas DB. Pateikta `test_runs` istorija leidžia atskirti du patikrintus paleidimus nuo vėlesnių bandymų. Rezultatų failai nėra ignoruojami `.gitignore`; `__pycache__`, laikini DB žurnalai ir paslapčių failai neįkeliami.

## Ribos

Sistema skirta vietiniam mokomajam demonstravimui. Apkrova su 10 000 užsakymų ir penkiais naudotojais, realus HTTPS, nustatyti kopijų / atkūrimo terminai bei tikri tiekėjai netikrinti. Vizito perplanavimo ir atšaukimo pranešimai, pradėto remonto perleidimas, grąžinimas nesukūrus sąmatos ir paskyros pakartotinis aktyvinimas nėra papildomai realizuoti šiame pakete. Kliento registracijos į praeitį ir būsimo vizito neatvykimo laiko ribos atskirai neįgyvendintos. Nekurkite fiktyvių darbų neaprašytam scenarijui apeiti.

Kodas ir šio archyvo įrodymai gali būti įkelti į projekto GitHub saugyklą. Šio paketo parengimas savaime nekeičia nuotolinės saugyklos turinio.
