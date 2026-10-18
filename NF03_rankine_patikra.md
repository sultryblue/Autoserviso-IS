# NF-03: likusi tiesioginės naršyklės ir serverio patikra

**Būklė: šis scenarijus dar neatliktas.** Dokumentuoti 24 Chromium bandymai patvirtina atvaizdavimą ir valdiklių pasiekiamumą, o 504 funkcinės patikros – programos taisykles. Šis lapas skirtas likusiam pilnam veiksmų atlikimui klaviatūra; faktinių rezultatų stulpelis pildomas atlikus bandymą.

## Paruošimas

Sustabdykite serverį ir pasidarykite `servisas.db` kopiją. Testuokite atskirą DB, pvz., `python main.py --db nf03_bandymu.db`. Jei šio failo dar nėra, programa parengs pradinį duomenų rinkinį. Demonstracinės DB netrinkite. Naudokite vietinį adresą `http://127.0.0.1:8765`.

Įrašykite datą, OS, naršyklę ir jos versiją, programos failų kontrolines sumas. Išbandykite 1360 ir 390 px **naršyklės turinio** plotį (ne vien fizinį monitoriaus dydį). 390 px galima nustatyti naršyklės kūrėjo priemonių įrenginio rodinyje. Po aplinkos paruošimo pagrindinius programos veiksmus atlikite be pelės: Tab, Shift+Tab, Enter, Space, Escape ir rodyklėmis.

## Veiksmai ir tikėtini rezultatai

| Nr. | Veiksmai | Tikėtinas rezultatas | Faktinis rezultatas |
|---|---|---|---|
| K1 | Klientui prisijungti; pakeisti savo kontaktą; pridėti automobilį. | Visi laukai ir mygtukai pasiekiami, fokusas matomas, išsaugoti duomenys lieka po puslapio atnaujinimo. | Neatlikta |
| K2 | Užregistruoti laisvą vizitą; pabandyti konfliktuojantį laiką. | Sėkmingas vizitas įrašomas; klaida paaiškinta; tinkama įvestis po klaidos neprarandama. | Neatlikta |
| K3 | Vadybininkui rasti klientą ir užsakymą, išvalyti bei įvesti nerandamą paiešką. | Atrenkami tinkami įrašai, išvalius atkuriamas sąrašas, neradimo tekstas aiškus. | Neatlikta |
| K4 | Priimti automobilį ir paskirti mechaniką diagnostikai. | Vienam vizitui vienas užsakymas; diagnostika skiriama atskiru veiksmu. | Neatlikta |
| K5 | Mechanikui įrašyti diagnostiką; vadybininkui sukurti netuščią sąmatą ir pateikti klientui. | Formos pasiekiamos; įrašas ir pateikta versija išlieka; tuščia versija neišsaugoma. | Neatlikta |
| K6 | Klientui priimti sprendimą; vadybininkui paskirti darbą; mechanikui pradėti, sustabdyti, tęsti ir užbaigti. | Leidžiami veiksmai pasiekiami klaviatūra; būsenos ir trukmė įrašomi. | Neatlikta |
| K7 | Klientui atlikti imituojamą mokėjimą arba darbuotojui registruoti vietinį atsiskaitymą. | Nereikia tikrų kortelės duomenų; laikomasi leistinos sumos; rezultatas matomas atnaujinus kortelę. | Neatlikta |
| K8 | Vadybininkui pažymėti paruoštu, registruoti perdavimą, uždaryti su pastaba; atskirai mėginti tuščią pastabą. | Tikrinamos baigties sąlygos; tuščia pastaba nepriimama; perdavimas ir uždarymas atskirti. | Neatlikta |
| K9 | Vadovui pakeisti suvestinės laikotarpį, peržiūrėti žurnalą bei pranešimų bandymus. | Filtrai pasiekiami; lentelės peržiūrimos klaviatūra, įskaitant slinktį siaurame lange. | Neatlikta |
| K10 | Atverti ir Escape uždaryti dialogą; patikrinti grįžusį fokusą ir klaidos pranešimą. | Fokusas lieka valdomas; nėra užstrigimo; aišku, kuri įvestis klaidinga. | Neatlikta |

Pakartokite abiem pločiams. Aptiktą problemą užrašykite konkrečiu langu, žingsniu ir ekrano nuotrauka. Pataisę kartokite paveiktą scenarijų. Įvykdžius šią patikrą D4 NF-03 statusą keiskite tik pagal išsaugotus faktinius rezultatus, o ne vien pagal šio plano egzistavimą.
