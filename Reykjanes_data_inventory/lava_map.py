import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import TwoSlopeNorm
from matplotlib.figure import Figure
from pyproj import Transformer
from rasterio.features import shapes
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from common import OUT, ROOT
from pair_quicklooks import CRS, GRID, H, W, bt, contour, hot, mtl, pnorm, read, show


def night_scene(g):
    get = lambda s: g[g.dst.str.endswith(s)].dst.tolist()
    if not (get("_MTL.txt") and get("_B10.TIF") and get("_B7.TIF")):
        return None
    t = mtl(get("_MTL.txt")[0])
    b10 = bt(read(get("_B10.TIF")[0])[0], t, 10)
    b7 = read(get("_B7.TIF")[0])[0] * t["RADIANCE_MULT_BAND_7"] + t["RADIANCE_ADD_BAND_7"]
    anom = b10 - np.nanmedian(b10) if np.isfinite(b10).sum() > 1000 else np.full_like(b10, np.nan)
    return b7, hot(b7)[0], anom


def to_polygons(mask, min_px, buffer_m):
    geoms = [shape(s) for s, v in shapes(mask.astype("uint8"), mask=mask, transform=GRID) if v == 1]
    geoms = [g for g in geoms if g.area >= min_px * 900]
    return unary_union(geoms).buffer(buffer_m) if geoms else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-hot-nights", type=int, default=2)
    ap.add_argument("--min-dbt", type=float, default=2.0)
    ap.add_argument("--buffer", type=float, default=300)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    m = pd.read_csv(ROOT / "manifest" / "download_manifest.csv")
    m = m[(m.sensor != "EnMAP") & (m.day_night == "night")]
    m["group"] = m.event.fillna("").where(m.event.fillna("") != "", "background")
    groups = list(dict.fromkeys(["background"] + [g for g in m.sort_values("datetime_utc").group if g != "background"]))
    prods = list(m.groupby("product_id"))
    prods = prods[:a.limit] if a.limit else prods
    print(f"Nocne sceny Landsat: {len(prods)}, grupy: {', '.join(groups)}")

    z = lambda: np.zeros((H, W), np.float32)
    acc = {g: dict(n=z(), s=z(), hot=z(), scenes=0) for g in groups}
    b7_max = np.full((H, W), -np.inf, np.float32)
    errors = 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(night_scene, g): g.group.iloc[0] for _, g in prods}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
            except Exception as e:
                errors += 1
                print(f"  ! {str(e)[:150]}")
                continue
            if r is None:
                continue
            b7, h, anom = r
            c = acc[futs[f]]
            ok = np.isfinite(anom)
            c["n"] += ok
            c["s"] += np.where(ok, anom, 0)
            c["hot"] += h
            c["scenes"] += 1
            b7_max = np.fmax(b7_max, np.nan_to_num(b7, nan=-np.inf))
            if i % 50 == 0 or i == len(futs):
                print(f"  [{i}/{len(futs)}]", flush=True)

    with np.errstate(invalid="ignore", divide="ignore"):
        mean = {g: c["s"] / c["n"] for g, c in acc.items()}
    events = [g for g in groups if g != "background" and acc[g]["scenes"]]
    bands, names, masks = [np.where(np.isinf(b7_max), np.nan, b7_max)], ["b7_max_all"], {}
    for g in events:
        dbt = mean[g] - mean["background"]
        bands += [acc[g]["hot"], dbt]
        names += [f"hot_nights {g}", f"dBT10 {g}"]
        masks[g] = (acc[g]["hot"] >= a.min_hot_nights) | ((dbt >= a.min_dbt) & (acc[g]["n"] >= 3))

    tif = OUT / "lava_map.tif"
    OUT.mkdir(exist_ok=True)
    with rasterio.open(tif, "w", driver="GTiff", dtype="float32", count=len(bands), width=W, height=H,
                       crs=CRS, transform=GRID, nodata=np.nan, compress="DEFLATE") as o:
        for i, (b, n) in enumerate(zip(bands, names), 1):
            o.write(b.astype(np.float32), i)
            o.set_band_description(i, n)

    to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform
    feats, union = [], []
    for g, mk in masks.items():
        poly = to_polygons(mk, 4, a.buffer)
        if poly is not None:
            union.append(poly)
            feats.append(dict(type="Feature", properties=dict(event=g, scenes=acc[g]["scenes"], area_km2=round(poly.area / 1e6, 2)),
                              geometry=mapping(transform(to_wgs, poly))))
    if union:
        allp = unary_union(union)
        feats.append(dict(type="Feature", properties=dict(event="ALL", scenes=sum(acc[g]["scenes"] for g in events),
                                                          area_km2=round(allp.area / 1e6, 2)),
                          geometry=mapping(transform(to_wgs, allp))))
    gj = OUT / "lava_mask.geojson"
    gj.write_text(json.dumps(dict(type="FeatureCollection", features=feats)), encoding="utf-8")

    n = len(events) + 1
    cols = 4
    rows = int(np.ceil(n / cols))
    fig = Figure(figsize=(4.2 * cols, 4.4 * rows))
    ax = np.atleast_2d(fig.subplots(rows, cols))
    show(ax[0, 0], bands[0], "max B7 wszystkich nocy", "inferno", pnorm(bands[0]))
    for k, g in enumerate(events, 1):
        x = ax[k // cols, k % cols]
        show(x, mean[g] - mean["background"], f"{g}: ΔBT10 vs tło [K], n={acc[g]['scenes']}", "RdBu_r", TwoSlopeNorm(0, -5, 5))
        contour(x, acc[g]["hot"] >= a.min_hot_nights, "black")
        contour(x, masks[g], "lime")
    for k in range(n, rows * cols):
        ax[k // cols, k % cols].axis("off")
    fig.tight_layout()
    png = OUT / "lava_map.png"
    fig.savefig(png, dpi=100)

    print(f"\nScen tła: {acc['background']['scenes']}, błędów odczytu: {errors}")
    for f in feats:
        print(f"  {f['properties']['event']:22s} scen {f['properties']['scenes']:4d}  maska {f['properties']['area_km2']} km²")
    print(f"\nRastry: {tif}\nMaska: {gj}\nPodgląd: {png}")


if __name__ == "__main__":
    main()
