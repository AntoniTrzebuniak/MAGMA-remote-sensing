import fsspec
import rasterio

tif_gcs_path = "gs://magma-remote-sensing-2026/satellites/snow2024comp.tif"

# fsspec otwiera strumień bez pobierania całego pliku na raz
with fsspec.open(tif_gcs_path, "rb") as f:
    with rasterio.open(f) as dataset:
        print("Połączono pomyślnie przez fsspec!")
        print("Wymiary:", dataset.width, "x", dataset.height)
        print("Kanały:", dataset.count)
        band1 = dataset.read(1)
        print("Kształt macierzy:", band1.shape)