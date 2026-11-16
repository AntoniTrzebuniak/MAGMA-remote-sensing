import os
import time

import pandas as pd
import rasterio
import requests
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds
from shapely.geometry import shape

from download import AOI, ROOT

m = pd.read_csv(ROOT / "manifest" / "download_manifest.csv")
href = m[(m.sensor == "EnMAP") & m.href.str.contains("SPECTRAL_IMAGE")].href.iloc[0]
user, pwd = os.environ["ENMAP_USERPWD"].split(":", 1)
print(href.rsplit("/", 1)[-1])

r = requests.head(href, auth=(user, pwd), allow_redirects=True, timeout=60)
print("HTTP", r.status_code, "| rozmiar pliku:", round(int(r.headers.get("Content-Length", 0)) / 1e6), "MB",
      "| Accept-Ranges:", r.headers.get("Accept-Ranges"))

env = dict(GDAL_HTTP_USERPWD=f"{user}:{pwd}", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_CHUNK_SIZE="1048576")
with rasterio.Env(**env):
    t = time.time()
    with rasterio.open(href) as src:
        print(f"otwarcie: {time.time() - t:.1f} s")
        print("pasma:", src.count, "| rozmiar:", src.shape, "| typ:", src.dtypes[0],
              "| bloki:", src.block_shapes[0], "| interleave:", src.interleaving, "| kompresja:", src.compression)
        print("struktura:", src.tags(ns="IMAGE_STRUCTURE"))
        g = transform_geom("EPSG:32627", src.crs, AOI)
        win = from_bounds(*shape(g).bounds, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        print("okno ROI:", win.width, "x", win.height, "px")
        t = time.time()
        src.read(1, window=win)
        dt1 = time.time() - t
        t = time.time()
        src.read(list(range(2, 12)), window=win)
        dt10 = time.time() - t
        print(f"1 pasmo: {dt1:.1f} s | 10 kolejnych pasm: {dt10:.1f} s")
        print(f"szacunek całego obrazu ({src.count} pasm): ~{dt10 / 10 * src.count / 60:.0f} min")