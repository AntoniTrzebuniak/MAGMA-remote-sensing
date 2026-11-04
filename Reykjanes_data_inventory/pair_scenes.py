import argparse

import numpy as np
import pandas as pd

from common import OUT, save

COLS = ["sensor", "levels", "pass_id", "product_id", "datetime_utc", "roi_cover_pass", "cloud", "sun_elevation"]


def load(name):
    p = OUT / name
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p)
    d["datetime_utc"] = pd.to_datetime(d.datetime_utc, utc=True, format="mixed").dt.tz_localize(None)
    if "pass_id" not in d:
        d["pass_id"] = d["product_id"]
    if "roi_cover_pass" not in d:
        d["roi_cover_pass"] = d.get("roi_cover", 1.0)
    if "sun_elevation" not in d:
        d["sun_elevation"] = np.nan
    sc = d["scene_cloud"].where(d["scene_cloud"] >= 0) / 100
    d["cloud"] = d["roi_cloud"].fillna(sc) if "roi_cloud" in d else sc
    d["cloud"] = d.groupby("pass_id")["cloud"].transform("mean")
    d["levels"] = d.groupby("pass_id")["level"].transform(lambda s: "+".join(sorted(set(s.astype(str)))))
    d = d.sort_values("roi_cover_pass", ascending=False).drop_duplicates("pass_id")
    return d.sort_values("datetime_utc")


def match(ref, cand, tag, win_h):
    c = cand[["datetime_utc", "product_id"]].rename(columns={"datetime_utc": f"{tag}_time", "product_id": f"{tag}_id"})
    m = pd.merge_asof(ref, c, left_on="datetime_utc", right_on=f"{tag}_time", direction="nearest")
    m[f"{tag}_dt_h"] = ((m[f"{tag}_time"] - m["datetime_utc"]).dt.total_seconds() / 3600).round(1)
    t, r, w = c[f"{tag}_time"].to_numpy(), m["datetime_utc"].to_numpy(), np.timedelta64(win_h, "h")
    m[f"n_{tag}_pm{win_h}h"] = np.searchsorted(t, r + w, "right") - np.searchsorted(t, r - w, "left")
    return m.drop(columns=f"{tag}_time")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cover", type=float, default=0.5)
    ap.add_argument("--max-cloud", type=float, default=0.3)
    a = ap.parse_args()

    def ok(d):
        return d[(d.roi_cover_pass >= a.min_cover) & ~(d.cloud > a.max_cloud)][COLS]

    ls = load("landsat.csv")
    hsi = [d for d in (load("enmap.csv"), load("prisma.csv")) if len(d)]
    if ls.empty or not hsi:
        print("Brak out/landsat.csv albo out/enmap.csv / out/prisma.csv — najpierw inwentaryzacja.")
        return
    hsi = ok(pd.concat(hsi, ignore_index=True)).sort_values("datetime_utc")
    day = ok(ls[ls.day_night == "day"])
    night = ok(ls[ls.day_night == "night"])

    pairs = match(match(hsi, day, "day", 72), night, "night", 168)
    save(pairs, "pairs_hsi_landsat.csv")
    dn = match(night, day, "day", 48)
    save(dn, "pairs_landsat_daynight.csv")

    allp = pd.concat([hsi, day.assign(sensor=day.sensor + " dzień"), night.assign(sensor=night.sensor + " noc")],
                     ignore_index=True)
    out = [f"# Dostępność danych, ROI Reykjanes",
           f"Filtry: pokrycie ROI >= {a.min_cover}, chmury <= {a.max_cloud} (nocne bez filtra chmur)", "",
           "## Przeloty na rok", "```", pd.crosstab(allp.sensor, allp.datetime_utc.dt.year).to_string(), "```", "",
           "## Sceny hiperspektralne vs najbliższy Landsat"]
    for s, g in pairs.groupby("sensor"):
        adt = g.day_dt_h.abs()
        out.append(f"- {s}: {len(g)} scen | Landsat dzień <= 6 h: {(adt <= 6).sum()}, <= 24 h: {(adt <= 24).sum()}, "
                   f"<= 72 h: {(adt <= 72).sum()} | noc w ±7 dni: {(g.n_night_pm168h > 0).sum()}")
    out += ["", "## Landsat noc",
            f"- przelotów: {len(dn)}, słońce < 0°: {(dn.sun_elevation < 0).sum()}, "
            f"z czystą sceną dzienną w ±48 h: {(dn.n_day_pm48h > 0).sum()}",
            "```", pd.crosstab(night.datetime_utc.dt.year, night.datetime_utc.dt.month).to_string()
            if len(night) else "brak", "```"]
    text = "\n".join(out)
    print("\n" + text)
    (OUT / "summary.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()