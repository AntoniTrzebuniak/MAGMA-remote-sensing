import argparse
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import Normalize, PowerNorm, TwoSlopeNorm
from matplotlib.figure import Figure
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from common import OUT, ROI_UTM, ROOT
from download import GCS, gcs
from enmap_radiance import band_table

warnings.filterwarnings("ignore")
RES = 30
ZOOM = 4000
CRS = "EPSG:32627"
_l, _b, _r, _t = ROI_UTM.buffer(2000).bounds
LEFT, TOP = np.floor(_l / RES) * RES, np.ceil(_t / RES) * RES
W, H = int(np.ceil((_r - LEFT) / RES)), int(np.ceil((TOP - _b) / RES))
GRID = from_origin(LEFT, TOP, RES, RES)
EXTENT = [LEFT, LEFT + W * RES, TOP - H * RES, TOP]
REVIEW = ["lava_in_swath", "clear_over_lava_ls", "clear_over_lava_enmap", "plume", "saturation",
          "offset_m", "phase_ok", "usable_for", "notes"]


def key(dst):
    return f"{GCS['prefix']}/{dst}"


def read(dst, band=1, scale=None):
    with MemoryFile(gcs().blob(key(dst)).download_as_bytes(timeout=600)) as mf, mf.open() as src:
        a = src.read(band).astype(np.float32)
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
        raw_max = float(np.nanmax(a)) if np.isfinite(a).any() else np.nan
        n_max = int((a == raw_max).sum())
        if scale:
            a = a * scale[0] + scale[1]
        out = np.full((H, W), np.nan, np.float32)
        reproject(a, out, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=GRID, dst_crs=CRS, dst_nodata=np.nan, resampling=Resampling.nearest)
    return out, raw_max, n_max


def mosaic(parts):
    out = np.full((H, W), np.nan, np.float32)
    for p in parts:
        out = np.where(np.isnan(out), p, out)
    return out


def mtl(dst):
    text = gcs().blob(key(dst)).download_as_bytes(timeout=300).decode()
    return {k: float(v) for k, v in re.findall(r"(\w+)\s*=\s*([-+0-9.Ee]+)\s*$", text, re.M)}


def bt(dn, m, b):
    rad = dn * m[f"RADIANCE_MULT_BAND_{b}"] + m[f"RADIANCE_ADD_BAND_{b}"]
    with np.errstate(invalid="ignore", divide="ignore"):
        return m[f"K2_CONSTANT_BAND_{b}"] / np.log(m[f"K1_CONSTANT_BAND_{b}"] / rad + 1) - 273.15


def hot(a):
    v = a[np.isfinite(a)]
    if v.size < 100:
        return np.zeros(a.shape, bool), np.nan
    med = np.median(v)
    mad = 1.4826 * np.median(np.abs(v - med))
    low = v[v <= np.percentile(v, 99)]
    thr = med + max(10 * mad, 5 * low.std(), 1e-6)
    return np.nan_to_num(a, nan=-np.inf) > thr, thr


def centroid(mask, w):
    yy, xx = np.nonzero(mask)
    ww = np.nan_to_num(w[yy, xx])
    ww = ww - ww.min() + 1e-9
    return LEFT + (np.average(xx, weights=ww) + 0.5) * RES, TOP - (np.average(yy, weights=ww) + 0.5) * RES


def files(m, pass_id, sensor, pattern):
    return m[(m.pass_id == pass_id) & (m.sensor == sensor) & m.dst.str.contains(pattern)].dst.tolist()


def landsat_pass(m, pass_id):
    rows = m[(m.pass_id == pass_id) & (m.sensor != "EnMAP")]
    b10, b11, b7 = [], [], []
    for pid, g in rows.groupby("product_id"):
        get = lambda s: g[g.dst.str.endswith(s)].dst.tolist()
        if not (get("_MTL.txt") and get("_B10.TIF") and get("_B7.TIF")):
            continue
        t = mtl(get("_MTL.txt")[0])
        b10.append(bt(read(get("_B10.TIF")[0])[0], t, 10))
        if get("_B11.TIF"):
            b11.append(bt(read(get("_B11.TIF")[0])[0], t, 11))
        a, mx, n = read(get("_B7.TIF")[0])
        b7.append((a * t["RADIANCE_MULT_BAND_7"] + t["RADIANCE_ADD_BAND_7"], mx, n))
    if not b10:
        return None
    sat = sum(n for _, mx, n in b7 if mx >= 65535)
    return dict(bt10=mosaic(b10), bt11=mosaic(b11) if b11 else None, b7=mosaic([a for a, _, _ in b7]), sat=sat)


def enmap_pass(m, pass_id):
    parts, unit, mx, nmx = [], "", 0, 0
    for img in files(m, pass_id, "EnMAP", "L1C/.*SPECTRAL_IMAGE"):
        meta = img.rsplit("/", 1)[0]
        xml = [d for d in files(m, pass_id, "EnMAP", "METADATA") if d.startswith(meta)]
        if not xml:
            continue
        table, _, unit = band_table(gcs().blob(key(xml[0])).download_as_bytes(timeout=300))
        i = int((table.wavelength_nm - 2200).abs().idxmin())
        a, raw_max, n = read(img, i + 1, (table.gain[i], table.offset[i]))
        parts.append(a)
        if raw_max > mx:
            mx, nmx = raw_max, n
        wl = table.wavelength_nm[i]
    if not parts:
        return None
    return dict(r2200=mosaic(parts), unit=unit, wl=wl, dn_max=mx, n_at_max=nmx)


def day_rgb(m, day_id):
    rows = m[(m.product_id == day_id) & m.dst.str.contains("roi/landsat/day")]
    bands = []
    for s in ("_SR_B7.TIF", "_SR_B5.TIF", "_SR_B4.TIF"):
        d = rows[rows.dst.str.endswith(s)].dst.tolist()
        if not d:
            return None
        bands.append(read(d[0])[0])
    rgb = np.dstack(bands)
    lo, hi = np.nanpercentile(rgb, 2), np.nanpercentile(rgb, 98)
    return np.nan_to_num(np.clip((rgb - lo) / (hi - lo + 1e-9), 0, 1))


def show(ax, a, title, cmap="gray", norm=None):
    ax.imshow(a, extent=EXTENT, cmap=cmap, norm=norm, interpolation="nearest")
    x, y = ROI_UTM.exterior.xy
    ax.plot(x, y, color="yellow", lw=0.8)
    ax.set_title(title, fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])


def contour(ax, mask, color):
    if mask.sum() >= 3:
        ax.contour(mask.astype(float), levels=[0.5], colors=color, linewidths=0.8, extent=EXTENT, origin="upper")


def pnorm(a):
    v = a[np.isfinite(a)]
    if v.size == 0:
        return None
    lo, hi = np.percentile(v, 1), np.percentile(v, 99.9)
    return PowerNorm(0.5, vmin=lo, vmax=hi if hi > lo else lo + 1e-6)


def process(p, m, qdir):
    en, ls = enmap_pass(m, p.pass_id), landsat_pass(m, p.ls_pass)
    if en is None or ls is None:
        return dict(pair=p.pair, error="brak plików EnMAP" if en is None else "brak plików Landsat")
    e_hot, e_thr = hot(en["r2200"])
    l_hot, l_thr = hot(ls["b7"])
    both = np.isfinite(en["r2200"]) & np.isfinite(ls["b7"])
    btd = ls["bt10"] - ls["bt11"] if ls["bt11"] is not None else None
    v10 = ls["bt10"][np.isfinite(ls["bt10"])]
    r = dict(pair=p.pair, enmap_valid=float(np.isfinite(en["r2200"]).mean()), ls_valid=float(np.isfinite(ls["bt10"]).mean()),
             overlap=float(both.mean()), enmap_hot_px=int(e_hot.sum()), ls_hot_px=int(l_hot.sum()),
             enmap_max=float(np.nanmax(en["r2200"])), ls_b7_max=float(np.nanmax(ls["b7"])),
             enmap_dn_max=en["dn_max"], enmap_n_at_max=en["n_at_max"], ls_b7_saturated=ls["sat"],
             bt10_median=float(np.median(v10)), bt10_p05=float(np.percentile(v10, 5)),
             cold_frac=float((v10 < np.median(v10) - 5).mean()),
             btd_median=float(np.nanmedian(btd)) if btd is not None else np.nan,
             btd_p95=float(np.nanpercentile(btd, 95)) if btd is not None else np.nan,
             enmap_unit=en["unit"], error="")
    u = (e_hot | l_hot) & both
    r["hot_iou"] = float((e_hot & l_hot & both).sum() / u.sum()) if u.sum() else np.nan
    if e_hot.sum() >= 5 and l_hot.sum() >= 5:
        (ex, ey), (lx, ly) = centroid(e_hot, en["r2200"]), centroid(l_hot, ls["b7"])
        r["hot_dx_m"], r["hot_dy_m"] = round(lx - ex), round(ly - ey)
    else:
        r["hot_dx_m"] = r["hot_dy_m"] = np.nan

    fig = Figure(figsize=(16, 16))
    ax = fig.subplots(3, 3)
    show(ax[0, 0], en["r2200"], f"EnMAP {en['wl']:.0f} nm (kontur: gorące w Landsat B7)", "inferno", pnorm(en["r2200"]))
    contour(ax[0, 0], l_hot, "cyan")
    show(ax[0, 1], ls["b7"], "Landsat B7 2200 nm (kontur: gorące w EnMAP)", "inferno", pnorm(ls["b7"]))
    contour(ax[0, 1], e_hot, "red")
    rgb = day_rgb(m, p.day_id) if isinstance(p.day_id, str) else None
    if rgb is not None:
        show(ax[0, 2], rgb, f"Dzień L2 SWIR/NIR/R, Δt {p.day_dt_h:+.0f} h od EnMAP")
        contour(ax[0, 2], e_hot, "red")
        contour(ax[0, 2], l_hot, "cyan")
    else:
        ax[0, 2].axis("off")
        ax[0, 2].set_title("brak dziennej sceny L2", fontsize=9)
    lo, hi = np.percentile(v10, 2), np.percentile(v10, 98)
    show(ax[1, 0], ls["bt10"], "Landsat BT10 [°C]", "magma", Normalize(lo, hi))
    fig.colorbar(ax[1, 0].images[0], ax=ax[1, 0], fraction=0.04)
    if btd is not None:
        show(ax[1, 1], btd, "BT10 − BT11 [K]", "RdBu_r", TwoSlopeNorm(0, -3, 3))
        fig.colorbar(ax[1, 1].images[0], ax=ax[1, 1], fraction=0.04)
    else:
        ax[1, 1].axis("off")
    ax[1, 2].axis("off")
    txt = [f"para {p.pair}", f"EnMAP  {p.datetime_utc}  ({p.pass_id})", f"Landsat {p.ls_time}  Δt {p.night_dt_h:+.1f} h",
           f"faza: {p.phase}  {p.event}", "",
           f"pokrycie siatki: EnMAP {r['enmap_valid']:.0%}, Landsat {r['ls_valid']:.0%}, wspólne {r['overlap']:.0%}",
           f"gorące px: EnMAP {r['enmap_hot_px']}, Landsat {r['ls_hot_px']}, IoU {r['hot_iou']:.2f}",
           f"przesunięcie gorących (LS − EnMAP): dx {r['hot_dx_m']} m, dy {r['hot_dy_m']} m",
           f"max EnMAP {r['enmap_max']:.4g} {en['unit']}", f"max B7 {r['ls_b7_max']:.4g} W/(m² sr µm)",
           f"EnMAP DN max {r['enmap_dn_max']:.0f} ({r['enmap_n_at_max']} px), B7 nasycone px {r['ls_b7_saturated']}",
           f"BT10 mediana {r['bt10_median']:.1f} °C, p5 {r['bt10_p05']:.1f} °C, zimne (<med−5 K) {r['cold_frac']:.0%}",
           f"BT10−BT11 mediana {r['btd_median']:.2f} K, p95 {r['btd_p95']:.2f} K"]
    ax[1, 2].text(0, 1, "\n".join(txt), va="top", family="monospace", fontsize=9)
    zoom = e_hot | l_hot
    if zoom.sum() >= 3:
        cx, cy = centroid(zoom, np.ones(zoom.shape, np.float32))
        for j, (a_, t_, cm, nm) in enumerate([(en["r2200"], "EnMAP 2200 nm", "inferno", pnorm(en["r2200"])),
                                              (ls["b7"], "Landsat B7", "inferno", pnorm(ls["b7"])),
                                              (ls["bt10"], "Landsat BT10", "magma", pnorm(ls["bt10"]))]):
            show(ax[2, j], a_, f"zbliżenie ±{ZOOM / 1000:.0f} km: {t_} (czerw. EnMAP, cyjan LS)", cm, nm)
            contour(ax[2, j], e_hot, "red")
            contour(ax[2, j], l_hot, "cyan")
            ax[2, j].set_xlim(cx - ZOOM, cx + ZOOM)
            ax[2, j].set_ylim(cy - ZOOM, cy + ZOOM)
    else:
        for j in range(3):
            ax[2, j].axis("off")
        ax[2, 0].set_title("brak gorących pikseli, bez zbliżenia", fontsize=9)
    fig.tight_layout()
    fig.savefig(qdir / f"{p.pair}.png", dpi=110)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dt", type=float, default=6)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    m = pd.read_csv(ROOT / "manifest" / "download_manifest.csv")
    pairs = pd.read_csv(OUT / "pairs_hsi_landsat.csv")
    pairs = pairs[(pairs.sensor == "EnMAP") & (pairs.day_night == "night") & (pairs.night_dt_h.abs() <= a.max_dt)]
    pairs = pairs.sort_values("datetime_utc").reset_index(drop=True)
    ls_pass = m.drop_duplicates("product_id").set_index("product_id").pass_id
    ls_time = m.drop_duplicates("product_id").set_index("product_id").datetime_utc
    lab = m[m.sensor == "EnMAP"].drop_duplicates("pass_id").set_index("pass_id")
    pairs["ls_pass"] = pairs.night_id.map(ls_pass)
    pairs["ls_time"] = pairs.night_id.map(ls_time)
    pairs["phase"] = pairs.pass_id.map(lab.phase).fillna("?")
    pairs["event"] = pairs.pass_id.map(lab.event).fillna("")
    pairs["pair"] = [f"{i + 1:02d}_{str(t)[:10].replace('-', '')}" for i, t in enumerate(pairs.datetime_utc)]
    print(f"Par EnMAP noc × Landsat noc (|Δt| <= {a.max_dt} h): {len(pairs)}, "
          f"bez nocnego Landsata w manifeście: {pairs.ls_pass.isna().sum()}")
    pairs = pairs[pairs.ls_pass.notna()]

    qdir = OUT / "quicklooks"
    qdir.mkdir(parents=True, exist_ok=True)
    auto_p = OUT / "pairs_auto.csv"
    old = pd.read_csv(auto_p) if auto_p.exists() and not a.overwrite else pd.DataFrame(columns=["pair", "error"])
    ok = set(old[old.error.fillna("") == ""].pair)
    todo = pairs[~pairs.pair.isin(ok) | ~pairs.pair.map(lambda s: (qdir / f"{s}.png").exists())]
    todo = todo.head(a.limit) if a.limit else todo
    print(f"Do zrobienia: {len(todo)}, gotowych: {len(pairs) - len(todo)}")

    res = []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(process, p, m, qdir): p.pair for p in todo.itertuples()}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
            except Exception as e:
                r = dict(pair=futs[f], error=str(e)[:200])
            res.append(r)
            msg = r["error"] or f"gorące EnMAP/LS {r['enmap_hot_px']}/{r['ls_hot_px']}, IoU {r['hot_iou']:.2f}"
            print(f"  [{i}/{len(todo)}] {r['pair']}: {msg}", flush=True)

    meta = pairs[["pair", "pass_id", "ls_pass", "datetime_utc", "ls_time", "night_dt_h", "phase", "event"]]
    old = old[[c for c in old.columns if c == "pair" or c not in meta.columns]]
    auto = pd.concat([old[~old.pair.isin([r["pair"] for r in res])], pd.DataFrame(res)], ignore_index=True)
    auto = meta.merge(auto, on="pair", how="right").sort_values("pair")
    auto.to_csv(auto_p, index=False)

    rev_p = OUT / "pairs_review.csv"
    rev = pd.read_csv(rev_p, dtype=str) if rev_p.exists() else pd.DataFrame(columns=list(meta.columns) + REVIEW)
    new = meta[~meta.pair.isin(rev.pair)].assign(**{c: "" for c in REVIEW})
    rev = pd.concat([rev, new], ignore_index=True).sort_values("pair")
    rev.to_csv(rev_p, index=False, encoding="utf-8-sig")

    err = sum(1 for r in res if r["error"])
    print(f"\nObrazki: {qdir}\nWskaźniki: {auto_p}\nDo wypełnienia: {rev_p} ({len(new)} nowych wierszy)")
    print("Gotowe, bez błędów." if not err else f"{err} par z błędem, szczegóły w kolumnie error w {auto_p.name}")


if __name__ == "__main__":
    main()
