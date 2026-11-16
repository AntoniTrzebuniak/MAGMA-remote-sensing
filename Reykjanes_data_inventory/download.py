import argparse
import hashlib
import os
import re
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import rasterio
import requests
from rasterio.errors import WindowError
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds
from shapely.geometry import mapping, shape

from common import ROI_UTM, ROOT

warnings.filterwarnings("ignore", category=FutureWarning)
AOI = mapping(ROI_UTM.buffer(2000))
BASE_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="5",
                GDAL_HTTP_TIMEOUT="120", CPL_VSIL_CURL_CHUNK_SIZE="4194304")
GCS = dict(project="magma-513619", bucket="magma-remote-sensing-2026", prefix="satellites")
_tls = threading.local()
_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3", region_name="us-west-2")
    return _s3


def gcs():
    if not hasattr(_tls, "bucket"):
        from google.cloud import storage
        _tls.bucket = storage.Client(project=GCS["project"]).bucket(GCS["bucket"])
    return _tls.bucket


def env_for(href):
    if href.startswith("s3://"):
        return dict(AWS_REQUEST_PAYER="requester", AWS_REGION="us-west-2")
    if "dlr.de" in href:
        return dict(GDAL_HTTP_USERPWD=os.environ["ENMAP_USERPWD"])
    return {}


def url_for(href):
    return planetary_computer.sign(href) if "blob.core.windows.net" in href else href


def read_chunks(src, win, size=32, tries=5):
    data = np.empty((src.count, win.height, win.width), dtype=src.dtypes[0])
    for b0 in range(0, src.count, size):
        bands = list(range(b0 + 1, min(b0 + size, src.count) + 1))
        for attempt in range(tries):
            try:
                data[b0:b0 + len(bands)] = src.read(bands, window=win)
                break
            except rasterio.errors.RasterioIOError:
                if attempt == tries - 1:
                    raise
                time.sleep(5 * (attempt + 1))
    return data


def label(dst):
    return re.sub(r"_V\d+_\d+T\d+Z", "", dst.name.replace("ENMAP01-____", ""))


def clip(url, dst):
    tmp = dst.with_name(dst.name + ".part")
    with rasterio.open(url) as src:
        g = transform_geom("EPSG:32627", src.crs, AOI)
        win = from_bounds(*shape(g).bounds, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        prof = dict(driver="COG", dtype=src.dtypes[0], count=src.count, crs=src.crs, nodata=src.nodata,
                    width=win.width, height=win.height, transform=src.window_transform(win),
                    compress="DEFLATE", bigtiff="IF_SAFER")
        data = read_chunks(src, win)
        with rasterio.open(tmp, "w", **prof) as out:
            out.write(data)
            out.update_tags(**src.tags())
            for b in range(1, src.count + 1):
                out.update_tags(b, **src.tags(b))
                if src.descriptions[b - 1]:
                    out.set_band_description(b, src.descriptions[b - 1])
    os.replace(tmp, dst)


def fetch(href, dst):
    if href.startswith("s3://"):
        bucket, key = href[5:].split("/", 1)
        body = s3().get_object(Bucket=bucket, Key=key, RequestPayer="requester")["Body"].read()
    else:
        auth = tuple(os.environ["ENMAP_USERPWD"].split(":", 1)) if "dlr.de" in href else None
        r = requests.get(url_for(href), auth=auth, timeout=300)
        r.raise_for_status()
        body = r.content
    tmp = dst.with_name(dst.name + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, dst)


def upload(dst, key):
    gcs().blob(key).upload_from_filename(str(dst), timeout=600)
    dst.unlink()


def remove_empty_dirs(root):
    for d, _, _ in sorted(os.walk(root), key=lambda w: -len(w[0])):
        try:
            os.rmdir(d)
        except OSError:
            pass


def clip_any(href, dst):
    try:
        clip(url_for(href), dst)
    except rasterio.errors.RasterioIOError:
        if not href.startswith("https://") or "dlr.de" in href or "blob.core.windows.net" in href:
            raise
        full = dst.with_name(dst.name + ".full")
        try:
            with requests.get(href, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(full, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            clip(str(full), dst)
        finally:
            full.unlink(missing_ok=True)


def job(href, dst, key, keep_local, verbose):
    name = label(Path(key))
    dst.parent.mkdir(parents=True, exist_ok=True)
    raster = href.split("?")[0].upper().endswith((".TIF", ".TIFF"))
    err = None
    for attempt in range(4):
        try:
            t = time.time()
            if not dst.exists():
                if verbose:
                    print(f"    > {name}" + (f" (próba {attempt + 1})" if attempt else ""), flush=True)
                with rasterio.Env(**BASE_ENV, **env_for(href)):
                    if raster:
                        clip_any(href, dst)
                    else:
                        fetch(href, dst)
                if verbose:
                    print(f"    ✓ {name}: pobrano w {time.time() - t:.0f} s, {dst.stat().st_size / 1e6:.1f} MB", flush=True)
            if not keep_local:
                t = time.time()
                upload(dst, key)
                if verbose:
                    print(f"    ↑ {name}: w buckecie po {time.time() - t:.0f} s", flush=True)
            return None
        except WindowError:
            return "poza ROI"
        except KeyError as e:
            return f"brak zmiennej środowiskowej {e}"
        except Exception as e:
            cause = e.__cause__ or e.__context__
            err = (f"{e} ({cause})" if cause else str(e)).split("?")[0][:200]
            if verbose:
                print(f"    ! {name}: {err} — ponawiam za {10 * 2 ** attempt} s", flush=True)
            time.sleep(10 * 2 ** attempt)
    return err


def local_path(root, dst, keep_local):
    if keep_local:
        return root / dst
    return root / "tmp" / (hashlib.md5(dst.encode()).hexdigest()[:12] + Path(dst).suffix)


def run(rows, root, workers, label, keep_local):
    if rows.empty:
        return []
    print(f"\n{label}: {len(rows)} plików, {workers} wątk.")
    failed, n = [], len(rows)
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(job, r.href, local_path(root, r.dst, keep_local), f"{GCS['prefix']}/{r.dst}", keep_local, workers <= 2): r
                for r in rows.itertuples()}
        for i, f in enumerate(as_completed(futs), 1):
            r, err = futs[f], f.result()
            if err == "poza ROI":
                print(f"  - [{i}/{n}] {Path(r.dst).name}: poza ROI, pomijam")
            elif err:
                print(f"  ! [{i}/{n}] {Path(r.dst).name}: {err}")
                failed.append({**r._asdict(), "error": err})
            elif i % 20 == 0 or i == n or workers <= 2:
                print(f"  [{i}/{n}] ok", flush=True)
    return failed


def run_usgs(rows, root, workers, keep_local, batch):
    if rows.empty:
        return []
    if not (os.environ.get("USGS_USERNAME") and os.environ.get("USGS_TOKEN")):
        print(f"\nLandsat noc: brak USGS_USERNAME / USGS_TOKEN, pomijam {len(rows)} plików")
        return []
    from m2m import M2M
    api, failed = M2M(), []
    pids = list(dict.fromkeys(rows.product_id))
    print(f"\nLandsat noc przez USGS M2M: {len(rows)} plików, {len(pids)} scen, paczki po {batch}")
    try:
        for i in range(0, len(pids), batch):
            part = rows[rows.product_id.isin(pids[i:i + batch])].copy()
            part["name"] = part.dst.map(lambda d: Path(d).name)
            try:
                urls = api.urls(pids[i:i + batch], set(part.name))
            except Exception as e:
                print(f"  ! paczka {i + 1}–{min(i + batch, len(pids))}: {str(e)[:200]} — loguję ponownie, pomijam paczkę")
                try:
                    api.login()
                except Exception:
                    pass
                urls = {}
            part["href"] = part.name.map(urls)
            missing = part[part.href.isna()]
            for r in missing.itertuples():
                print(f"  ! {r.name}: USGS nie zwrócił linku")
                failed.append({**r._asdict(), "error": "brak linku z M2M"})
            failed += run(part[part.href.notna()].drop(columns="name"), root, workers,
                          f"Landsat noc, sceny {i + 1}–{min(i + batch, len(pids))}", keep_local)
    finally:
        api.logout()
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--priority", default="P1")
    ap.add_argument("--sensor", choices=["all", "enmap", "landsat"], default="all")
    ap.add_argument("--day-night", choices=["all", "day", "night"], default="all")
    ap.add_argument("--root", default="data")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--enmap-workers", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep-local", action="store_true")
    ap.add_argument("--landsat-source", choices=["usgs", "aws"], default="usgs")
    ap.add_argument("--batch", type=int, default=20)
    a = ap.parse_args()

    root = Path(a.root)
    m = pd.read_csv(ROOT / "manifest" / "download_manifest.csv")
    if a.owner not in set(m.owner):
        print(f"Brak '{a.owner}' w manifeście. Dostępne --owner: {', '.join(sorted(set(m.owner)))}")
        return
    m = m[(m.owner == a.owner) & m.priority.isin(a.priority.split(","))]
    if a.day_night != "all":
        m = m[m.day_night == a.day_night]
    is_en = m.sensor == "EnMAP"
    if a.sensor != "all":
        m = m[is_en if a.sensor == "enmap" else ~is_en]
        is_en = m.sensor == "EnMAP"
    if a.limit:
        keep = m.drop_duplicates("product_id").groupby(is_en).head(a.limit).product_id
        m = m[m.product_id.isin(keep)]
        is_en = m.sensor == "EnMAP"

    if a.keep_local:
        done = m.dst.map(lambda d: (root / d).exists())
        where = f"lokalnie w {root}"
    else:
        names = {b.name for b in gcs().list_blobs(prefix=f"{GCS['prefix']}/roi/")}
        done = m.dst.map(lambda d: f"{GCS['prefix']}/{d}" in names)
        where = f"gs://{GCS['bucket']}/{GCS['prefix']}"
    print(f"{a.owner} {a.priority}: {len(m)} plików, {done.sum()} już jest ({where}), {(~done).sum()} do pobrania")
    m, is_en = m[~done], is_en[~done]

    via_usgs = m.href.str.startswith("s3://") & (a.landsat_source == "usgs")
    failed = run(m[~is_en & ~via_usgs], root, a.workers, "Landsat", a.keep_local)
    failed += run_usgs(m[via_usgs], root, a.workers, a.keep_local, a.batch)
    failed += run(m[is_en], root, a.enmap_workers, "EnMAP", a.keep_local)
    if not a.keep_local:
        remove_empty_dirs(root / "roi")
    log = root / f"failed_{a.owner}.csv"
    root.mkdir(exist_ok=True)
    if failed:
        pd.DataFrame(failed).drop(columns="Index").to_csv(log, index=False)
        print(f"\n{len(failed)} plików nie pobrano -> {log}. Uruchom ponownie to samo polecenie.")
    else:
        log.unlink(missing_ok=True)
        print("\nGotowe, bez błędów.")


if __name__ == "__main__":
    main()