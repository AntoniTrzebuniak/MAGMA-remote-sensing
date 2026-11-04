import json
from pathlib import Path

import pandas as pd
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
ROI = shape(json.loads((ROOT / "roi.geojson").read_text())["features"][0]["geometry"])
_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32627", always_xy=True).transform
ROI_UTM = transform(_to_utm, ROI)


def roi_cover(geom):
    g = transform(_to_utm, geom).buffer(0)
    return round(g.intersection(ROI_UTM).area / ROI_UTM.area, 3)


def add_pass_cover(df, geoms):
    df["roi_cover"] = [roi_cover(g) for g in geoms]
    union = pd.Series(geoms, index=df.index).groupby(df["pass_id"]).apply(lambda s: roi_cover(unary_union(list(s))))
    df["roi_cover_pass"] = df["pass_id"].map(union)
    return df


def save(df, name):
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / name, index=False)
    print(f"{len(df):6d} wierszy -> {OUT / name}")