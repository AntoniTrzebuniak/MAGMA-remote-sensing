import argparse
import json

import pandas as pd
from pystac_client import Client

from common import OUT, ROI, ROOT

PC = "https://planetarycomputer.microsoft.com/api/stac/v1"
LS_NIGHT = {"lwir11": "B10.TIF", "lwir12": "B11.TIF", "swir16": "B6.TIF", "swir22": "B7.TIF",
            "qa_pixel": "QA_PIXEL.TIF", "MTL.txt": "MTL.txt"}
LS_DAY = ["lwir11", "emis", "blue", "red", "nir08", "swir16", "swir22", "qa_pixel", "mtl.txt"]
EN_PATTERNS = {"L1C": ("SPECTRAL_IMAGE", "METADATA", "QL_PIXELMASK"),
               "L2A": ("SPECTRAL_IMAGE", "METADATA", "QL_PIXELMASK", "QL_QUALITY")}
PRIO = {"cooling": "P1", "background": "P2", "eruption": "P3"}


def load(name):
    d = pd.read_csv(OUT / name)
    d["t"] = pd.to_datetime(d.datetime_utc, utc=True, format="mixed").dt.tz_localize(None)
    sc = d.scene_cloud.where(d.scene_cloud >= 0) / 100
    d["cloud"] = d.roi_cloud.fillna(sc) if "roi_cloud" in d else sc
    return d


def utc(ev, col, fallback):
    if col not in ev:
        return fallback
    return pd.to_datetime(ev[col], utc=True, errors="coerce").dt.tz_localize(None).fillna(fallback)


def add_phase(d, ev, cooling_days):
    d["phase"], d["event"] = "background", ""
    ev = ev.assign(t0=utc(ev, "start_utc", ev.start), t1=utc(ev, "end_utc", ev.end + pd.Timedelta(days=1)))
    for e in ev.itertuples():
        m = (d.t >= e.t1) & (d.t < e.t1 + pd.Timedelta(days=cooling_days))
        d.loc[m, ["phase", "event"]] = ["cooling", e.name]
    for e in ev.itertuples():
        m = (d.t >= e.t0) & (d.t < e.t1)
        d.loc[m, ["phase", "event"]] = ["eruption", e.name]
    d["priority"] = d.phase.map(PRIO)
    return d


def assets_of(path):
    return {f["id"]: f["assets"] for f in json.loads(path.read_text())["features"]}


def basename(href):
    return href.split("?")[0].rsplit("/", 1)[-1]


def enmap_rows(en, items):
    rows = []
    for r in en.itertuples():
        hrefs = [a["href"] for a in items.get(r.product_id, {}).values()
                 if any(p in basename(a["href"]).upper() for p in EN_PATTERNS[r.level])]
        if not hrefs:
            print("  ! brak assetów:", r.product_id, list(items.get(r.product_id, {}))[:10])
        rows += [(r, h, f"roi/enmap/{r.level}/{r.product_id}/{basename(h)}") for h in hrefs]
    return rows


def s3_href(pid, assets, key, suffix):
    alt = assets.get(key, {}).get("alternate", {}).get("s3", {}).get("href")
    if alt:
        return alt
    f = pid.split("_")
    return (f"s3://usgs-landsat/collection02/level-1/standard/oli-tirs/{f[3][:4]}/"
            f"{f[2][:3]}/{f[2][3:]}/{pid}/{pid}_{suffix}")


def scene_key(pid):
    return "_".join(pid.split("_")[k] for k in (0, 2, 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enmap-owners", default="kubek,pomocnik")
    ap.add_argument("--landsat-owner", default=None)
    ap.add_argument("--min-cover", type=float, default=0.5)
    ap.add_argument("--max-cloud", type=float, default=0.3)
    ap.add_argument("--cooling-days", type=int, default=60)
    a = ap.parse_args()
    owners = a.enmap_owners.split(",")
    ev = pd.read_csv(ROOT / "eruptions.csv", parse_dates=["start", "end"])

    en = add_phase(load("enmap.csv"), ev, a.cooling_days)
    en = en[(en.roi_cover_pass >= a.min_cover) & (en.roi_cover > 0)]
    en["pcloud"] = en.groupby("pass_id").cloud.transform("mean")
    night = en.day_night == "night"
    en = en[(night & (en.level == "L1C")) | (~night & ~(en.pcloud > a.max_cloud))]
    p = en.drop_duplicates("pass_id").sort_values("t")
    p["owner"] = [owners[i % len(owners)] for i in p.groupby("priority").cumcount()]
    en["owner"] = en.pass_id.map(p.set_index("pass_id").owner)

    ls = add_phase(load("landsat.csv"), ev, a.cooling_days)
    ls = ls[(ls.roi_cover_pass >= a.min_cover) & (ls.roi_cover > 0.05)]
    pairs = pd.read_csv(OUT / "pairs_hsi_landsat.csv")
    paired = pairs[(pairs.day_night == "night") & (pairs.night_dt_h.abs() <= 6)].night_id
    paired_pass = set(ls[ls.product_id.isin(paired)].pass_id)
    ls_n = ls[(ls.day_night == "night") & ((ls.sun_elevation < 0) | ls.pass_id.isin(paired_pass))]
    ls_d = ls[(ls.day_night == "day") & ~(ls.cloud > a.max_cloud)]

    rows = enmap_rows(en, {**assets_of(OUT / "enmap_L1C_items.geojson"), **assets_of(OUT / "enmap_L2A_items.geojson")})
    ls_items = assets_of(OUT / "landsat_items.geojson")
    for r in ls_n.itertuples():
        for key, suffix in LS_NIGHT.items():
            h = s3_href(r.product_id, ls_items.get(r.product_id, {}), key, suffix)
            rows.append((r, h, f"roi/landsat/night/{r.product_id}/{basename(h)}"))

    t0, t1 = ls_d.t.min().date(), ls_d.t.max().date()
    l2 = {scene_key(it.id): it for it in Client.open(PC).search(
        collections=["landsat-c2-l2"], bbox=ROI.bounds, datetime=f"{t0}/{t1}", limit=500).items()}
    missing = 0
    for r in ls_d.itertuples():
        it = l2.get(scene_key(r.product_id))
        if it is None:
            missing += 1
            continue
        for key in LS_DAY:
            if key in it.assets:
                h = it.assets[key].href
                rows.append((r, h, f"roi/landsat/day/{it.id}/{basename(h)}"))
    print(f"Landsat dzień: {len(ls_d) - missing} scen z L2 na Planetary Computer, {missing} bez L2 (pominięte)")

    lo = a.landsat_owner or owners[0]
    m = pd.DataFrame([{
        "priority": r.priority, "phase": r.phase, "event": r.event,
        "owner": r.owner if r.sensor == "EnMAP" else lo,
        "sensor": r.sensor, "day_night": r.day_night, "level": r.level,
        "product_id": r.product_id, "pass_id": r.pass_id, "datetime_utc": r.datetime_utc,
        "href": h, "dst": dst} for r, h, dst in rows])
    m.loc[m.dst.str.startswith("roi/landsat/day"), "level"] = "L2"
    m = m.sort_values(["priority", "datetime_utc", "dst"])
    (ROOT / "manifest").mkdir(exist_ok=True)
    m.to_csv(ROOT / "manifest" / "download_manifest.csv", index=False)

    s = m.drop_duplicates("product_id")
    s = s.assign(typ=s.sensor.where(s.sensor == "EnMAP", "Landsat") + " " + s.day_night)
    print(f"\n{len(m)} plików, {len(s)} produktów -> manifest/download_manifest.csv\n")
    print("Produkty wg priorytetu:")
    print(pd.crosstab(s.typ, s.priority, margins=True, margins_name="razem").to_string())
    print("\nProdukty wg osoby:")
    print(pd.crosstab([s.owner], s.priority, margins=True, margins_name="razem").to_string())


if __name__ == "__main__":
    main()
