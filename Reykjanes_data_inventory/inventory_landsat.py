import argparse
import pandas as pd
from pystac import ItemCollection
from pystac_client import Client
from shapely.geometry import shape

from common import OUT, ROI, add_pass_cover, save

STAC = "https://landsatlook.usgs.gov/stac-server"
PLATFORMS = {"LANDSAT_8": "L8", "LANDSAT_9": "L9"}


def to_rows(items):
    rows, geoms = [], []
    for it in items:
        p = it.properties
        plat = PLATFORMS.get(str(p.get("platform", "")).upper().replace("-", "_"))
        if not plat:
            continue
        path, row = int(p["landsat:wrs_path"]), int(p["landsat:wrs_row"])
        night = row >= 123
        rows.append({
            "sensor": plat, "level": "L1", "product_id": it.id, "datetime_utc": it.datetime,
            "day_night": "night" if night else "day", "sun_elevation": p.get("view:sun_elevation"),
            "scene_cloud": p.get("eo:cloud_cover"), "land_cloud": p.get("landsat:cloud_cover_land"),
            "wrs_path": path, "wrs_row": row, "correction": p.get("landsat:correction"),
            "tier": p.get("landsat:collection_category"),
            "pass_id": f"{plat}_{it.datetime:%Y%m%d}_{path:03d}_{'N' if night else 'D'}",
        })
        geoms.append(shape(it.geometry))
    return rows, geoms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-09-01")
    ap.add_argument("--end", default="2026-12-31")
    a = ap.parse_args()
    items = list(Client.open(STAC).search(collections=["landsat-c2l1"], bbox=ROI.bounds,
                                          datetime=f"{a.start}/{a.end}", limit=300).items())
    print(f"landsat-c2l1: {len(items)} produktów (wszystkie misje)")
    OUT.mkdir(exist_ok=True)
    ItemCollection(items).save_object(str(OUT / "landsat_items.geojson"))

    rows, geoms = to_rows(items)
    if not rows:
        print("brak scen L 8/9.")
        return
    df = add_pass_cover(pd.DataFrame(rows), geoms).sort_values("datetime_utc")
    save(df, "landsat.csv")

    p = df.drop_duplicates("pass_id")
    p = p[p.roi_cover_pass >= 0.5]
    print("\nPrzeloty L8/L9 nad ROI (pokrycie ROI >= 50%):")
    print(pd.crosstab(pd.to_datetime(p.datetime_utc, utc=True).dt.year, [p.sensor, p.day_night]).to_string())
    if (p.day_night == "night").sum() == 0:
        print("\n0 nocnych")


if __name__ == "__main__":
    main()