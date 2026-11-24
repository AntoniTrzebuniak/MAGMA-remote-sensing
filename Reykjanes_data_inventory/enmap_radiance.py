import argparse
import tempfile
import time
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from download import GCS, ROOT, gcs

warnings.filterwarnings("ignore", category=FutureWarning)
OUT_PREFIX = f"{GCS['prefix']}/derived/enmap_radiance/L1C"
PROBE_NM = (1650, 2200)


def band_table(xml_bytes):
    root = ET.fromstring(xml_bytes)
    for el in root.iter():
        el.tag = el.tag.split("}")[-1]
    rows = []
    for b in root.iter("bandID"):
        if b.find("GainOfBand") is None:
            continue
        rows.append(dict(band=int(b.get("number")),
                         wavelength_nm=float(b.findtext("wavelengthCenterOfBand")),
                         fwhm_nm=float(b.findtext("FWHMOfBand")),
                         gain=float(b.findtext("GainOfBand")),
                         offset=float(b.findtext("OffsetOfBand"))))
    sun = root.findtext("specific/sunElevationAngle/center")
    unit = next((e.text.strip() for e in root.iter()
                 if "unit" in e.tag.lower() and e.text and "sr" in e.text), "")
    table = pd.DataFrame(rows)
    if not table.empty and table.band.is_unique:
        table = table.sort_values("band").reset_index(drop=True)
    return table, sun, unit


def process(r, src_key, meta_key, out_key, workdir):
    t = time.time()
    table, sun, unit = band_table(gcs().blob(meta_key).download_as_bytes(timeout=300))
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        dn_path, out_path = Path(tmp) / "dn.tif", Path(tmp) / "rad.tif"
        gcs().blob(src_key).download_to_filename(str(dn_path), timeout=600)
        with rasterio.open(dn_path) as src:
            if len(table) != src.count:
                raise ValueError(f"METADATA ma {len(table)} pasm, obraz {src.count}")
            dn = src.read()
            bad = dn == src.nodata if src.nodata is not None else None
            gain = table.gain.to_numpy(np.float32)[:, None, None]
            offset = table.offset.to_numpy(np.float32)[:, None, None]
            rad = dn.astype(np.float32)
            del dn
            rad *= gain
            rad += offset
            if bad is not None:
                rad[bad] = np.nan
                del bad
            prof = dict(driver="COG", dtype="float32", count=src.count, crs=src.crs, nodata=np.nan,
                        width=src.width, height=src.height, transform=src.transform,
                        compress="DEFLATE", predictor="YES", bigtiff="IF_SAFER")
        with rasterio.open(out_path, "w", **prof) as out:
            out.write(rad)
            out.update_tags(PRODUCT_ID=r.product_id, DATETIME_UTC=r.datetime_utc, DAY_NIGHT=r.day_night,
                            PASS_ID=r.pass_id, PRIORITY=r.priority, EVENT=r.event if isinstance(r.event, str) else "",
                            SUN_ELEVATION=sun or "", RADIANCE_UNIT=unit, FORMULA="L = GainOfBand * DN + OffsetOfBand",
                            SOURCE=f"gs://{GCS['bucket']}/{src_key}")
            for i, b in enumerate(table.itertuples(), 1):
                out.set_band_description(i, f"{b.wavelength_nm:.2f} nm")
                out.update_tags(i, WAVELENGTH_NM=b.wavelength_nm, FWHM_NM=b.fwhm_nm, GAIN=b.gain, OFFSET=b.offset)
        stats = dict(product_id=r.product_id, datetime_utc=r.datetime_utc, day_night=r.day_night, event=r.event,
                     sun_elevation=sun, unit=unit, valid_frac=float(np.isfinite(rad[0]).mean()))
        for nm in PROBE_NM:
            i = int((table.wavelength_nm - nm).abs().idxmin())
            v = rad[i][np.isfinite(rad[i])]
            stats[f"p99_9_{nm}nm"] = float(np.percentile(v, 99.9)) if v.size else np.nan
            stats[f"max_{nm}nm"] = float(v.max()) if v.size else np.nan
        del rad
        gcs().blob(out_key).upload_from_filename(str(out_path), timeout=600)
        stats["mb"] = round(out_path.stat().st_size / 1e6, 1)
    stats["s"] = round(time.time() - t)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--priority", default="P1")
    ap.add_argument("--day-night", default="all", choices=["all", "day", "night"])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    m = pd.read_csv(ROOT / "manifest" / "download_manifest.csv")
    m = m[(m.sensor == "EnMAP") & (m.level == "L1C") & m.priority.isin(a.priority.split(","))]
    if a.day_night != "all":
        m = m[m.day_night == a.day_night]
    have = {b.name for b in gcs().list_blobs(prefix=f"{GCS['prefix']}/")}
    key = lambda dst: f"{GCS['prefix']}/{dst}"

    todo, missing, done = [], [], 0
    for pid, g in m.groupby("product_id"):
        img = g[g.dst.str.contains("SPECTRAL_IMAGE")]
        meta = g[g.dst.str.contains("METADATA")]
        out_key = f"{OUT_PREFIX}/{pid}_RADIANCE.TIF"
        if out_key in have and not a.overwrite:
            done += 1
        elif img.empty or meta.empty or key(img.dst.iloc[0]) not in have or key(meta.dst.iloc[0]) not in have:
            missing.append(pid)
        else:
            todo.append((img.iloc[0], key(img.dst.iloc[0]), key(meta.dst.iloc[0]), out_key))
    todo = todo[:a.limit] if a.limit else todo
    print(f"EnMAP L1C {a.priority} {a.day_night}: {len(todo)} do przeliczenia, {done} już gotowych, "
          f"{len(missing)} bez obrazu lub METADATA w buckecie")

    workdir = ROOT / "data" / "tmp"
    workdir.mkdir(parents=True, exist_ok=True)
    stats, failed = [], []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(process, *t, workdir): t[0].product_id for t in todo}
        for i, f in enumerate(as_completed(futs), 1):
            pid = futs[f]
            short = pid.replace("ENMAP01-____", "")[:40]
            try:
                s = f.result()
                stats.append(s)
                print(f"  [{i}/{len(todo)}] {short} {s['day_night']}: {s['mb']} MB, {s['s']} s, "
                      f"max 2200 nm = {s['max_2200nm']:.4g}", flush=True)
            except Exception as e:
                failed.append(dict(product_id=pid, error=str(e)[:300]))
                print(f"  ! [{i}/{len(todo)}] {short}: {str(e)[:200]}", flush=True)

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    tag = a.priority.replace(",", "") + ("" if a.day_night == "all" else f"_{a.day_night}")
    if stats:
        p = out / f"enmap_radiance_{tag}.csv"
        s = pd.DataFrame(stats)
        if p.exists():
            s = pd.concat([pd.read_csv(p), s], ignore_index=True).drop_duplicates("product_id", keep="last")
        s.sort_values("datetime_utc").to_csv(p, index=False)
        print(f"\nStatystyki scen: {p}")
        units = set(s.unit.dropna())
        print(f"Jednostka z METADATA: {units or 'nie znaleziono'}")
    if missing:
        print(f"Bez danych w buckecie ({len(missing)}): np. {missing[0]}")
    if failed:
        pd.DataFrame(failed).to_csv(out / f"enmap_radiance_failed_{tag}.csv", index=False)
        print(f"{len(failed)} scen nie przeliczono, lista w out/enmap_radiance_failed_{tag}.csv")
    else:
        print("Gotowe, bez błędów.")


if __name__ == "__main__":
    main()
