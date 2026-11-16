# Pobieranie EnMAP do bucketa — instrukcja dla zespołu

Skrypt `download.py` pobiera z serwera DLR tylko wycinki ROI (Reykjanes + 2 km),
zapisuje je jako COG i od razu wgrywa do `gs://magma-remote-sensing-2026/satellites/roi/`.
Na dysku nic nie zostaje. Lista plików jest w `manifest/download_manifest.csv` (w repo).

## Podział

| Kto | Co | Produkty |
|---|---|---|
| Jakub | P1 (dzień i noc) | 111 |
| Osoba A | P2 + P3, sceny **dzienne** | 110 |
| Osoba B | P2 + P3, sceny **nocne** | 92 |

`--owner jakub` w poleceniach to tylko etykieta w manifeście, nie konto. Wpisujecie ją wszyscy.

## 1. Jednorazowe przygotowanie

Tutorial wysłał Antek, konto EnMAP wspolne.

```
gcloud auth application-default login
```

**Kod i środowisko** (PowerShell w VS Code, w folderze repo)

```powershell
git pull
conda env create -f environment.yml
conda activate reykjanes
```

**Login EnMAP w środowisku** — cały argument w cudzysłowie, inaczej PowerShell zapisze apostrofy razem z hasłem i się wywali:

```powershell
conda env config vars set "ENMAP_USERPWD=twoj_login:twoje_haslo"
conda deactivate
conda activate reykjanes
```


## 2. Test na jednym produkcie

Osoba A:

```powershell
python .\download.py --owner jakub --priority P2,P3 --sensor enmap --day-night day --limit 1
```

Osoba B:

```powershell
python .\download.py --owner jakub --priority P2,P3 --sensor enmap --day-night night --limit 1
```

## 3. Właściwe pobieranie (przyk;ladowo na dwie osoby)

Osoba A:

```powershell
python .\download.py --owner jakub --priority P2,P3 --sensor enmap --day-night day --enmap-workers 2
```

Osoba B:

```powershell
python .\download.py --owner jakub --priority P2,P3 --sensor enmap --day-night night --enmap-workers 2
```


## 4. Co znaczą komunikaty

| W terminalu | Znaczenie | Co zrobić |
|---|---|---|
| `> plik` | start pobierania | nic |
| `  plik: pobrano w … s` | wycinek gotowy | nic |
| `  plik: w buckecie` | plik wgrany, usunięty z dysku | nic |
| `  plik: Read failed … ponawiam` | serwer DLR nie oddał fragmentu pliku; skrypt sam ponawia | nic, to częste |
| `poza ROI, pomijam` | kafel nie ma wspólnych pikseli z ROI | nic |
| `N plików nie pobrano` | część plików nie przeszła po wszystkich próbach | uruchom to samo polecenie jeszcze raz |
