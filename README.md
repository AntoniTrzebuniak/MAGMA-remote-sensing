# MAGMA-remote-sensing
Separacja wewnętrznego strumienia geotermalnego od wymuszenia słonecznego na stygnących polach lawowych półwyspu Reykjanes Fuzja danych hiperspektralnych VSWIR (EnMAP, PRISMA), wieloczasowych obserwacji termalnych TIR (Landsat 8/9) oraz modelowania cyklu dobowego (DTC) i walidacji InSAR/DEM

# Konfiguracja dostępu do Google Cloud Storage (MAGMA Remote Sensing)

Przewodnik szybkiego startu dla członków zespołu. Pozwala skonfigurować środowisko tak, aby pobierać i analizować dane rastrowe bezpośrednio z chmury w Pythonie bez ręcznego ściągania plików na dysk.

- **ID Projektu:** `magma-513619`
- **Nazwa Bucketa:** `gs://magma-remote-sensing-2026`
- **Region:** `europe-central2` (Warszawa)
    

## 1. Instalacja Google Cloud CLI

W folderze `./assets` w repozytorium znajduje się oficjalny instalator dla Windows.

1. Uruchom plik `./assets/GoogleCloudSDKInstaller.exe`.
2. Podczas instalacji:
    - Zostaw zaznaczoną opcję **Bundled Python**.
    - Upewnij się, że dodano narzędzie do scieżki systemowej PATH (działa automatycznie, ale power shell miewa problemy więc używajcie z cmd)
        
3. Po zakończeniu instalacji **zrestartuj całkowicie VS Code / terminal**, aby załadować nowe ścieżki środowiskowe.
    
> **Weryfikacja instalacji:**
> 
> Otwórz nowy terminal w VS Code (`Ctrl + ~`) lub cmd i wpisz:
> 
> 
> ```{PowerShell}
> gcloud --version
> ```
> 
> Jeśli widzisz wersję `Google Cloud SDK`, instalacja powiodła się.

## 2. Jednorazowa autoryzacja (ADC)

Uwierzytelnianie odbywa się bez plików kluczy JSON – korzystamy z mechanizmu Application Default Credentials (ADC).
Wpisz w terminalu:

```
gcloud auth application-default login
```

1. W przeglądarce otworzy się okno logowania Google.
2. Zaloguj się kontem Google, któremu został nadany dostęp do projektu.
3. Zaakceptuj uprawnienia.

Po powrocie do terminala zobaczysz komunikat o pomyślnym zapisaniu poświadczeń w pliku `application_default_credentials.json`.

Następnie ustaw aktywny projekt:

```
gcloud config set project magma-513619
```

## Żebyście mogli skorzystać z projektu w gcloud musicie dać mi swoje maile od kont google żebym was dodał

## 3. Przydatne komendy CLI (Test działania)

Sprawdź w terminalu, czy masz bezpośredni dostęp do zasobnika i plików:

- **Sprawdzenie aktywnego konta i projektu:**
    
    ```
    gcloud auth list
    gcloud config get-value project
    ```
    
- **Podgląd informacji o buckecie:**
    
    ```
    gcloud storage buckets list
    ```
    
- **Wylistowanie plików w zasobniku:**
    
    ```
    gcloud storage ls --long gs://magma-remote-sensing-2026/satellites/
    ```
    
- **Wgranie własnego pliku do chmury:**
    
    ```
    gcloud storage cp ./twoj_plik.tif gs://magma-remote-sensing-2026/satellites/twoj_plik.tif
    ```
    
- **Pobranie pliku z chmury na dysk lokalny:**
    
    ```
    gcloud storage cp gs://magma-remote-sensing-2026/satellites/snow2024comp.tif ./pobrany_plik.tif
    ```
    

## 4. Instalacja bibliotek w Pythonie

W swoim środowisku wirtualnym (`venv` / `conda`) zainstaluj wymagane pakiety:

PowerShell

```
pip install google-cloud-storage gcsfs fsspec rasterio xarray
```

## 5. Uruchomienie testu w repozytorium
W repozytorium znajduje się gotowy skrypt testowy: `test_gcs.py`

Uruchom go w terminalu lub przyciskiem w VS Code.
Jeśli odczyta plik i zobaczysz wymiary macierzy znaczy, że działa
