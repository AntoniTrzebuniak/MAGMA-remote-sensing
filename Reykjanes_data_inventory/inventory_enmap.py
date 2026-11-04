import argparse
import base64
import os
import pandas as pd
from pystac import ItemCollection
from pystac_client import Client
from shapely.geometry import shape

from common import OUT, ROI, add_pass_cover, save

STAC = "https://geoservice.dlr.de/eoc/ogc/stac/v1/"
PREFIXES = ("eo:", "view:", "sat:", "enmap:")


def auth_headers():
    up = os.environ.get("GDAL_HTTP_USERPWD")
    return {"Authorization": "Basic " + base64.b64encode(up.encode()).decode()} if up else None


def to_rows(items, level):
    rows = []
    for it in items:
        p = it.properties
        extra = {k: v for k, v in p.items() if k.startswith(PREFIXES) and not isinstance(v, (list, dict))}
        rows.append({
            "sensor": "EnMAP", "level": level, "product_id": it.id,
            "datetime_utc": it.datetime or p.get("start_datetime"),
            "day_night": "day", "sun_elevation": p.get("view:sun_elevation"),
            "scene_cloud": p.get("eo:cloud_cover"), **extra,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-04-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--levels", default="L1C,L2A")
    a = ap.parse_args()

    cat = Client.open(STAC, headers=auth_headers())
    OUT.mkdir(exist_ok=True)
    rows, geoms = [], []
    for lvl in a.levels.split(","):
        coll = f"ENMAP_HSI_{lvl}"
        try:
            items = list(cat.search(collections=[coll], bbox=ROI.bounds,
                                    datetime=f"{a.start}/{a.end}", limit=100).items())
        except Exception as e:
            print(f"{coll}: brak: {e}")
            continue
        print(f"{coll}: {len(items)} itemow")
        if not items:
            print("  katalog:", [c.id for c in cat.get_collections() if "ENMAP" in c.id.upper()])
            continue
        ItemCollection(items).save_object(str(OUT / f"enmap_{lvl}_items.geojson"))
        rows += to_rows(items, lvl)
        geoms += [shape(it.geometry) for it in items]
    if not rows:
        print("No data")
        return
    df = pd.DataFrame(rows)
    dt = pd.to_datetime(df["datetime_utc"], utc=True)
    take = df["product_id"].str.extract(r"(DT\d+)")[0]
    df["pass_id"] = "EnMAP_" + take.fillna(dt.dt.floor("10min").dt.strftime("%Y%m%dT%H%M"))
    df = add_pass_cover(df, geoms).sort_values("datetime_utc")
    save(df, "enmap.csv")

    p = df.drop_duplicates("pass_id")
    print("\nROI >= 50% na rok:")
    print(p[p.roi_cover_pass >= 0.5].groupby(pd.to_datetime(p.datetime_utc, utc=True).dt.year).size().to_string())


if __name__ == "__main__":
    main()