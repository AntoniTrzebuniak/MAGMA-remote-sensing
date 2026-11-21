# Weryfikacja `eruptions.csv`: Fagradalsfjall 2021, Meradalir 2022, Litli-Hrútur 2023 + erupcje po 5.08.2025

Weryfikacja: 2026-11-21. Plik dotyczy `Reykjanes_data_inventory/eruptions.csv` (gałąź `Reykjanes_inventory`).

**Linki do vedur.is (stan na 21.11.2026):** 17.11.2026 IMO uruchomiło nowy serwis vedur.is, a stare adresy `www.vedur.is/um-vi/frettir/...` zwracają 404. Stare artykuły są dostępne pod tą samą ścieżką w domenie **`eldri.vedur.is`** („Eldri vedur.is”). Angielskie artykuły na `en.vedur.is` ładują się, ale bez treści, a komunikaty VONA (`.../vona?nr=...`) nie istnieją już w żadnej wersji serwisu. Dlatego tam, gdzie się dało, podaję islandzkie odpowiedniki z `eldri.vedur.is` (otwarte i sprawdzone 21.11.2026), a VONA oznaczam jako „archiwalne, obecnie niedostępne”. Do pracy polecam dodatkowo zrobić zrzuty w Wayback Machine (https://web.archive.org/), bo `eldri.vedur.is` może kiedyś zniknąć.

**Strefa czasowa:** Islandia przez cały rok używa UTC (GMT), bez czasu letniego. Czas lokalny podawany przez IMO i GVP („All times are local”) jest więc równy UTC.

**Definicja `end` w CSV:** ostatni dzień, w którym wypływała lawa (koniec efuzji). To **nie** jest data oficjalnego ogłoszenia końca przez IMO. Daty ogłoszeń są podane osobno poniżej.

## TL;DR

1. Dla wszystkich trzech erupcji obecne wartości `start` i `end` w CSV są **poprawne** jako daty (dzień rozpoczęcia i ostatni dzień efuzji). W pliku nie trzeba zmieniać żadnej daty.
2. Format CSV ma rozdzielczość dobową, a `select_scenes.add_phase` traktuje dzień startu i końca w całości jako „eruption”. Przez to **3 produkty w obecnym manifeście mają złą etykietę** (szczegóły w sekcji 5):
   - EnMAP 2023-07-10 13:57 UTC ma etykietę P3, ale to **przed** startem erupcji (16:40 UTC), więc powinien być „background”.
   - EnMAP 2023-08-05 23:04 UTC ma etykietę P3, ale to **po** końcu efuzji (ok. południa), więc powinien być „cooling” (P1).
   - Landsat 8 2021-09-05 22:32 UTC ma etykietę P3, ale to **w trakcie 8,5-dniowej pauzy** (2–11.09.2021), bez wypływu lawy.
3. W 2021 roku była **jedna** przerwa dłuższa niż 3 dni: od 2 września (ostatni wypływ przed pauzą) do 11 września (wznowienie). Wszystkie inne pauzy w lipcu–sierpniu 2021 trwały najwyżej ok. 35 h.
4. **Po 5.08.2025 na Reykjanes nie było nowej erupcji** ani intruzji. Potwierdzają to aktualizacje IMO z 27.10.2026 i 10.11.2026: trwa wypiętrzanie w Svartsengi, a kolejna intruzja to „najbardziej prawdopodobny scenariusz”. Oś czasu IMO (sprawdzona 21.11.2026) nie ma nowszych wpisów niż 10.11.2026.

## 1. Fagradalsfjall 2021 (Geldingadalir)

| Pole | Wartość | Źródło |
|---|---|---|
| **Start** | **2021-03-19, ok. 20:45 UTC** (czas przyjęty przez IMO) | IMO, wiadomości o erupcji 2021 („Eldgos hófst við Fagradalsfjall í Geldingadal, um kl. 20:45 í kvöld”), https://eldri.vedur.is/um-vi/frettir/skjalfti-m57-a-reykjanesi ; IMO, rocznica erupcji („Þann 19. mars kl 20:45 opnaðist sprunga”), https://eldri.vedur.is/um-vi/frettir/ar-lidid-fra-upphafi-eldgossins-vid-fagradalsfjall ; raport roczny IMO 2021 (PDF), https://eldri.vedur.is/media/vedurstofan-utgafa-2022/VI_arsskyrsla_2021-vef.pdf . Angielski komunikat IMO z 20.03.2021 („At around 20:45 UTC today, 19 March…”) jest obecnie pusty na en.vedur.is. |
| **Pauza > 3 dni** | **ostatni wypływ przed pauzą: 2021-09-02; wznowienie: 2021-09-11.** | GVP/USGS Weekly Report 1–7.09.2021 (erupcja „paused on 2 September”, para i gaz z krateru 2–7.09), https://volcano.si.edu/showreport.cfm?gvpvar=GVP.WVAR20210901-371032. Wznowienie 11.09: Lava visibly returned on 11 September, https://volcano.si.edu/showreport.cfm?wvar=GVP.WVAR20210908-371032 |
| Inne pauzy lipiec–sierpień | tylko kilkugodzinne do ok. 35 h, żadna nie przekracza 3 dni | Barsotti i in. 2023 (faza IV-a). Charakter epizodyczny potwierdza też Soubestre i in. 2025, *JGR Solid Earth*, https://doi.org/10.1029/2024JB029380 + sprawdzilem wpisy na stronie dla tych dat https://volcano.si.edu/volcano.cfm?vn=371032#July2021 |
| **End (koniec efuzji)** | **2021-09-18, wieczorem** (dokładnej godziny brak w źródłach) | GVP BGVN 47:09 („lava effusion had stopped during the evening of 18 September 2021”, za Instytutem Nauk o Ziemi), https://doi.org/10.5479/si.gvp.bgvn202209-371032 ; IMO, 17.11.2021 („Frá 18. september til dagsins í dag hefur ekki sést í hraunflæði frá gígnum”), https://eldri.vedur.is/um-vi/frettir/enntha-ovissa-um-goslok-vid-fagradalsfjall ; IMO, 18.10.2021 (obniżenie kodu lotniczego do żółtego, brak lawy od 18.09), https://eldri.vedur.is/um-vi/frettir/uppfaert-mat-a-elgosinu-vid-fagradalsfjall ; raport roczny IMO 2021 (jeden aktywny krater od 2.05 do końca erupcji 18.09) ; Pedersen i in. (fotogrametria, 19.03–18.09.2021), https://par.nsf.gov/servlets/purl/10356472 |
| Ogłoszenie końca przez IMO | **2021-12-18** (po 3 miesiącach bez lawy). Media (AFP) podały to 2021-12-20. | IMO, 18.12.2021, „Ekkert hraunflæði í þrjá mánuði við Fagradalsfjall” (erupcja, która zaczęła się 19.03, trwała dokładnie 6 miesięcy; „þessum tiltekna atburði … er lokið”) |
| Wartość w CSV | `2021-03-19,2021-09-18`, **poprawna** | — |

Uwagi:
- Wariant z podziałem na dwa wiersze (opcjonalny, nie wprowadziłem go do CSV): `Fagradalsfjall 2021a,2021-03-19,2021-09-02` i `Fagradalsfjall 2021b,2021-09-11,2021-09-18`. Przy obecnym `add_phase` scena z 5.09 dostałaby wtedy etykietę „cooling” (P1) zdarzenia 2021a. To też nie jest czyste stygnięcie, bo lawa wróciła 6 dni później. Proponuję raczej oznaczyć ją ręcznie lub wykluczyć (sekcja 5).

## 2. Meradalir 2022

| Pole | Wartość | Źródło |
|---|---|---|
| **Start** | **2022-08-03, 13:18 (UTC wg kamer)** | IMO, wiadomości o erupcji 2022 („virðist kvika hafa komið upp á yfirborð kl 13:18”, według kamer), https://eldri.vedur.is/um-vi/frettir/eldgos-a-reykjanesskaga |
| **End (koniec efuzji)** | **2022-08-21, tremor ustał tuż przed 06:00 UTC** | IMO, „Latest news on the eruption at Reykjanes peninsula”, aktualizacja z 23.08.2022: „The eruption in Meradalir, which commenced on the 3rd of August, ceased to issue lava on the 21 of August. Volcanic tremor started to decrease steadily from the 18th and stopped completely during the night of 21st.” Strona IMO jest obecnie pusta, dostęp przez Internet Archive: https://web.archive.org/web/20231222142725/https://en.vedur.is/about-imo/news/a-new-eruption-has-started-at-fagradalsfjall ; GVP BGVN 47:09 (tremor ustał tuż przed 0600 21.08, równocześnie z gęstym pióropuszem z krateru), https://doi.org/10.5479/si.gvp.bgvn202209-371032 |
| Ogłoszenie końca przez IMO | **2022-09-15**: kod lotniczy zielony, „Since the 21st of August, no new lava has been released…”. Osobnego komunikatu „eruption over” nie znalazłem. Iceland Monitor 29.08.2022 pisał, że IMO jeszcze nie ogłosiło końca. | IMO, VONA nr 394 (archiwalne, obecnie niedostępne); GVP BGVN 47:09 (żółty 22.08, zielony 15.09), https://doi.org/10.5479/si.gvp|
| Wartość w CSV | `2022-08-03,2022-08-21`, **poprawna** | — |

Uwagi: Skoro efuzja skończyła się ok. 06:00 UTC, przyszłe sceny z 21.08 po tej godzinie należałoby uznać za „cooling”.

## 3. Litli-Hrútur 2023

| Pole | Wartość | Źródło |
|---|---|---|
| **Start** | **2023-07-10, 16:40 UTC** | IMO, „The activity in the Reykjanes Peninsula has entered a new phase”, aktualizacja z 10.07.2023, 18:30: „At 16:40 today, 10 July, a minor volcanic eruption began close to Litli Hrútur in Reykjanes Peninsula, situated between Fagradalsfjall and Keilir mountains.” Strona IMO jest obecnie pusta, dostęp przez Internet Archive: https://web.archive.org/web/20240101090207/https://en.vedur.is/about-imo/news/earthquake-activity-in-fagradalsfjall-area ; GVP, https://volcano.si.edu/volcano.cfm?vn=371032 |
| **End (koniec efuzji)** | **2023-08-05, około południa UTC** (w połowie dnia tremor na stacji „hrv” wrócił do tła sprzed erupcji; IES: aktywność „completely disappeared after noon on August 5”) | IMO, „Kaflaskil í eldvirkninni á Reykjanesskaga” (8–10.08.2023: „Um miðjan dag, laugardaginn 5. ágúst … órói … kominn aftur í svipaða bakgrunnsvirkni og fyrir gos … Engin virkni hefur verið í gígnum síðan þá”; ostatnie sygnały termalne w satelicie wieczorem 6.08), https://eldri.vedur.is/um-vi/frettir/landris-hefur-maelst-vid-fagradalsfjall-sidan-i-april ; IES przez Iceland Monitor, https://icelandmonitor.mbl.is/news/news/2023/10/04/the_eruption_this_year_was_around_one_third_larger_ |
| Uzupełnienie | Aktywność ostatnio widziana 5.08. Anomalię termalną w kraterze wykryto w satelicie jeszcze 6.08. Kod lotniczy obniżono do żółtego 5.08 o 17:06. | GVP, profil Fagradalsfjall (BGVN 48:09 i raporty tygodniowe), https://volcano.si.edu/volcano.cfm?vn=371032 |
| Ogłoszenie końca przez IMO | **2023-08-15** (spotkanie monitoringowe IMO, komunikat „Goslokum lýst yfir við Litla-Hrút”); kod lotniczy zielony w VONA 2023-08-16 (10 dni bez aktywności, tremor na poziomie tła) | IMO, 15.08.2023, „Óbreytt staða í Öskju”, https://eldri.vedur.is/um-vi/frettir/obreytt-stada-i-oskju ; IMO, VONA nr 473 z 16.08.2023 (archiwalne, obecnie niedostępne) |
| Wartość w CSV | `2023-07-10,2023-08-05`, **poprawna** | — |

Uwagi:
- Anomalia termalna z 6.08 to stygnący krater, a nie efuzja.

## 4. Erupcje na Reykjanes po 5.08.2025

| Data | Stan | Źródło |
|---|---|---|
| 2025-08-05 | Koniec 9. erupcji na Sundhnúkur (od 16.07.2025): „Eldgosinu sem hófst 16. júlí er lokið”. **Wartość `Sundhnukur 9,2025-07-16,2025-08-05` w CSV jest zgodna.** | IMO, 5.08.2025, „Níunda gosinu á Sundhnúksgígaröðinni lokið”, https://eldri.vedur.is/um-vi/frettir/kvikuhlaup-er-hafid-a-sundhnuksgigarodinni |
| 19.08.2025 – 10.11.2026 | **Oficjalna oś czasu IMO w nowym serwisie** („Staðan á Reykjanesskaga”). Od erupcji z lipca 2025 tylko wpisy o wypiętrzaniu, akumulacji magmy i ocenie zagrożenia, bez żadnej erupcji ani intruzji. Ostatni wpis: 10.11.2026, 16:02, „Landris mælist áfram við Svartsengi”. | https://www.vedur.is/atburdir/landris-og-kvikusofnun-vid-svartsengi/ (sprawdzone 21.11.2026) |

**Wniosek:** od 5.08.2025 do co najmniej 10–11.11.2026 nie było nowej erupcji ani intruzji. Oś czasu IMO sprawdzona 21.11.2026 nie ma wpisu nowszego niż 10.11.2026, a IMO publikuje tam każdą zmianę sytuacji, więc nic nie wskazuje na erupcję także w okresie 11–21.11.2026. Sprawdzilem tez GVP i znalazlem zadnej nowej erupcji. Przed zamknięciem CSV sprawdź oś czasu IMO: https://www.vedur.is/atburdir/landris-og-kvikusofnun-vid-svartsengi/.

## 5. Wpływ na manifest (sprawdzone na `origin/Reykjanes_inventory`)

`add_phase` w `select_scenes.py` oznacza jako „eruption” przedział `[start 00:00, end + 1 dzień)` w UTC. Przy rozdzielczości dobowej CSV daje to błędy na granicach. Przeszukałem `out/landsat.csv`, `out/enmap.csv` i `manifest/download_manifest.csv` pod kątem dni granicznych oraz pauzy z 2021 roku:

| Produkt | Czas UTC | Obecna etykieta | Poprawna | Dlaczego |
|---|---|---|---|---|
| `ENMAP01-____L1C/L2A-DT0000027902_20230710T135749Z` (dzień) | 2023-07-10 13:57 | eruption / P3 | **background / P2** (dokładniej: scena tuż przed erupcją) | erupcja zaczęła się o 16:40 UTC |
| `ENMAP01-____L1C-DT0000028349_20230710T2330…` (noc) | 2023-07-10 23:30 | eruption / P3 | eruption / P3 ✔ | po starcie |
| `LC09_L1TP_067229_20230710_20230711_02_T1` (noc) | 2023-07-10 22:25 | eruption / P3 | eruption / P3 ✔ | po starcie |
| `ENMAP01-____L1C-DT0000033800_20230805T2304…` (noc) | 2023-08-05 23:04 | eruption / P3 | **cooling / P1** | efuzja ustała około południa 5.08. Kilkanaście godzin po końcu to bardzo cenny punkt początkowy krzywej stygnięcia. |
| `ENMAP01-…DT0000033792_20230805T1331…` (dzień) | 2023-08-05 13:31 | (nie trafił do manifestu, prawdopodobnie przez filtr chmur) | niejednoznaczny | ok. 1–1,5 h po „południu”; w praktyce koniec efuzji |
| `LC08_L1GT_068229_20210905_20210916_02_T2` (noc) | 2021-09-05 22:32 | eruption / P3 | **osobna kategoria: pauza** (ani P3, ani czysty P1) | 3 dni po zatrzymaniu efuzji, 6 dni przed jej wznowieniem |
| `LC08_L1GT_221015_20210905…` (dzień) | 2021-09-05 12:52 | (nie trafił do manifestu) | j.w. | j.w. |

Jak to naprawić bez zmiany formatu CSV (do decyzji zespołu):
1. **Najprościej:** po wygenerowaniu manifestu ręcznie nadpisać `phase/priority` dla powyższych 3 produktów (albo dodać plik z wyjątkami).
2. **Porządniej:** dodać do CSV kolumny `start_utc` i `end_utc` z godziną (np. `2023-07-10T16:40`, `2023-08-05T12:00`) i porównywać w `add_phase` znaczniki czasu zamiast dni. To zmienia format pliku, więc tylko za zgodą zespołu.
3. Pauzę 3–10.09.2021 dodać jako osobny wpis albo wykluczyć ją z P1 i P3.
