import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from pystac_client import Client
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds
from shapely.geometry import mapping, shape

from common import OUT, ROI, save

PC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def read_roi(href):
    with rasterio.open(href) as src:
        g = transform_geom("EPSG:4326", src.crs, mapping(ROI))
        win = from_bounds(*shape(g).bounds, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        a = src.read(1, window=win)
        inside = geometry_mask([g], a.shape, src.window_transform(win), invert=True)
        return a[inside]


def landsat_qa(href):
    v = read_roi(planetary_computer.sign(href))
    ok = (v & 1) == 0
    if not ok.any():
        return np.nan, np.nan, 0.0
    v = v[ok]
    return ((v & 0b11110) > 0).mean(), ((v & 0b100000) > 0).mean(), ok.mean()


def enmap_qa(href):
    v = read_roi(href)
    ok = (v == 0) | (v == 1)
    if not ok.any():
        return np.nan, np.nan, 0.0
    return (v[ok] == 1).mean(), np.nan, ok.mean()


def run(fn, jobs, workers):
    def safe(href):
        try:
            return fn(href)
        except Exception as e:
            print("  !", href.split("?")[0].rsplit("/", 1)[-1], e)
            return np.nan, np.nan, np.nan
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(safe, [h for _, h in jobs]))


def scene_key(pid):
    return "_".join(pid.split("_")[k] for k in (0, 2, 3))


def landsat(a):
    df = pd.read_csv(OUT / "landsat.csv")
    day = df[(df.day_night == "day") & (df.scene_cloud <= a.max_scene_cloud) & (df.roi_cover > 0)]
    t0, t1 = df.datetime_utc.min()[:10], df.datetime_utc.max()[:10]
    items = Client.open(PC).search(collections=["landsat-c2-l2"], bbox=ROI.bounds,
                                   datetime=f"{t0}/{t1}", limit=500).items()
    qa = {scene_key(it.id): it.assets["qa_pixel"].href for it in items}
    jobs = [(i, qa[scene_key(p)]) for i, p in day.product_id.items() if scene_key(p) in qa]
    print(f"Landsat: {len(jobs)}/{len(day)} dziennych scen L2 na PC")
    for (i, _), r in zip(jobs, run(landsat_qa, jobs, a.workers)):
        df.loc[i, ["roi_cloud", "roi_snow", "roi_valid"]] = r
    save(df, "landsat.csv")


def enmap(a):
    if not os.environ.get("GDAL_HTTP_USERPWD"):
        print("enmap brak hasla ")
        return
    df = pd.read_csv(OUT / "enmap.csv")
    feats = json.loads((OUT / "enmap_L2A_items.geojson").read_text())["features"]
    hrefs = {}
    for f in feats:
        for k, asset in f["assets"].items():
            s = (k + asset["href"]).upper()
            if "QUALITY_CLOUD" in s and "SHADOW" not in s:
                hrefs[f["id"]] = asset["href"]
    jobs = [(i, hrefs[p]) for i, p in df.product_id.items() if p in hrefs and df.loc[i, "roi_cover"] > 0]
    print(f"EnMAP: {len(jobs)} kafli L2A z maską chmur nad ROI")
    for (i, _), r in zip(jobs, run(enmap_qa, jobs, a.workers)):
        df.loc[i, ["roi_cloud", "roi_snow", "roi_valid"]] = r
    save(df, "enmap.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", nargs="+", default=["landsat", "enmap"])
    ap.add_argument("--max-scene-cloud", type=float, default=90)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    if "landsat" in a.what:
        landsat(a)
    if "enmap" in a.what:
        enmap(a)


if __name__ == "__main__":
    main()