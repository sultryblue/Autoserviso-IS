# Automobilių serviso darbų ir užsakymų valdymo informacinė sistema

Mokomasis informacinės sistemos prototipas, sukurtas studijų dalykui **„Verslo informacinės sistemos kūrimas“**.

## Reikalavimai

Programai paleisti reikalingas **Python 3**. Papildomų Python paketų diegti nereikia – naudojama standartinė Python biblioteka.

## Paleidimas Windows aplinkoje

1. Parsisiųskite arba išskleiskite projekto failus.
2. Paleiskite `paleisti_windows.bat` arba komandų eilutėje vykdykite:

   ```text
   python main.py
   ```

3. Naršyklėje atverkite:

   ```text
   http://127.0.0.1:8765
   ```

Pirmo paleidimo metu `servisas.db` sukuriama automatiškai ir užpildoma demonstraciniais duomenimis.

## Demonstracinės paskyros

Visų demonstracinių paskyrų slaptažodis:

```text
Demo2026!
```

Prisijungimo vardai:

- `klientas` – Klientas
- `vadybininkas` – Vadybininkas
- `mechanikas` – Mechanikas A
- `mechanikas2` – Mechanikas B
- `vadovas` – Vadovas

## Išorinės paslaugos

Mokėjimų ir pranešimų paslaugos prototipe **imituojamos**. Tikri mokėjimai neatliekami, o tikri SMS ar el. laiškai nesiunčiami. Kortelės duomenys sistemoje nesaugomi.

## Testai

Serverio ir duomenų bazės testai:

```text
python test_system.py
```

UI logikos testams reikalingas **Node.js** (naudojami tik jo standartiniai moduliai, todėl `npm install` nereikia):

```text
node test_ui.js
```

Patikrintoje projekto versijoje praėjo **457/457 serverio ir DB patikros** bei **26/26 UI logikos patikros**.

## Pastaba

Sistema skirta vietiniam mokomajam demonstravimui. Realiam diegimui reikėtų HTTPS, realių išorinių paslaugų integracijų, atsarginių kopijų ir kitų gamybinės aplinkos nustatymų.
