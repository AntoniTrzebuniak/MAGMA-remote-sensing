from __future__ import annotations

import argparse
import csv
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import gaussian_filter, sobel
from skimage.registration import phase_cross_correlation

from .grid import GRID_PATH, build_grid, select_reference_scenes
from .io_gcs import (
    find_metadata,
    gcs_env,
    gcs_url,
    list_objects,
    list_scenes,
)
from .warp import warp_to_grid

LOGGER = logging.getLogger(__name__)
COREG_DIR = Path(__file__).resolve().parent
PREFIX = "satellites"
SHIFTS_CSV = COREG_DIR / "shifts.csv"
SHIFT_COLUMNS = [
    "product_id", "sensor", "dx_m", "dy_m", "reliability", "n_pikseli",
    "metoda", "status", "uwagi",
]


def parse_enmap_metadata(scene_or_xml: str) -> dict[str, str]:
    """Parse geometry/georeferencing/GCP fields from an EnMAP metadata XML."""
    import io
    from .io_gcs import gcs_url, gcs_env

    if scene_or_xml.startswith("gs://"):
        import fsspec
        with fsspec.open(scene_or_xml, "rb") as handle:
            data = handle.read()
    else:
        data = Path(scene_or_xml).read_bytes()
    root = ET.fromstring(data)
    keywords = ("accuracy", "orthorect", "geometric", "gcp", "ground_control",
                "coordinate", "projection")
    fields: dict[str, str] = {}
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1]
        low = name.lower()
        if any(key in low for key in keywords):
            text = " ".join((element.text or "").split())
            if text:
                fields[name] = text
    return fields


def append_shift(row: dict) -> None:
    SHIFTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = SHIFTS_CSV.exists()
    with SHIFTS_CSV.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHIFT_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in SHIFT_COLUMNS})


def enmap_spectral_url(scene: str) -> str:
    objects = list_objects(scene)
    for obj in objects:
        if "SPECTRAL_IMAGE_COG" in obj.upper():
            return obj
    raise FileNotFoundError(f"No EnMAP SPECTRAL_IMAGE_COG in {scene}")


def enmap_band_for_wavelength(src_count: int, wavelength_nm: int) -> int:
    # EnMAP VNIR/SWIR: 224 bands, approximate continuous 420–2450 nm.
    fraction = (wavelength_nm - 420) / (2450 - 420)
    index = int(np.clip(round(fraction * (src_count - 1)), 0, src_count - 1)) + 1
    return index


def read_enmap_band(scene: str, wavelength_nm: int, grid_path: Path) -> np.ndarray:
    url = enmap_spectral_url(scene)
    with rasterio.Env(**gcs_env()), rasterio.open(gcs_url(url)) as src:
        band = enmap_band_for_wavelength(src.count, wavelength_nm)
        values = src.read(band)
    from rasterio.warp import reproject
    with rasterio.Env(**gcs_env()), rasterio.open(gcs_url(url)) as src:
        from rasterio.enums import Resampling
        with rasterio.open(grid_path) as grid:
            out = np.empty((grid.height, grid.width), dtype="float32")
            reproject(
                source=values,
                destination=out,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=grid.transform,
                dst_crs=grid.crs,
                resampling=Resampling.bilinear,
                src_nodata=src.nodata,
                dst_nodata=0,
            )
    return out


def phase_band(reference: np.ndarray, moving: np.ndarray) -> tuple[float, float, float]:
    ref_valid = np.isfinite(reference) & (reference != 0)
    mov_valid = np.isfinite(moving) & (moving != 0)
    valid = ref_valid & mov_valid
    ref = np.where(valid, reference, np.nanmedian(reference))
    mov = np.where(valid, moving, np.nanmedian(moving))
    ref = gaussian_filter(ref.astype("float32"), 1.0)
    mov = gaussian_filter(mov.astype("float32"), 1.0)
    rg = np.hypot(sobel(ref, 1), sobel(ref, 0))
    mg = np.hypot(sobel(mov, 1), sobel(mov, 0))
    shift, error, _ = phase_cross_correlation(
        rg, mg, upsample_factor=10, reference_mask=valid,
        moving_mask=valid, normalization="phase",
    )
    return float(shift[1] * 30.0), float(shift[0] * 30.0), float(max(0.0, 1.0 - error))


def register_day_scene(
    scene: str,
    reference_nir: np.ndarray,
    grid_path: Path = GRID_PATH,
) -> dict:
    product_id = scene.rsplit("/", 1)[-1]
    moving = read_enmap_band(scene, 850, grid_path)
    try:
        dx_m, dy_m, reliability = phase_band(reference_nir, moving)
        n_pikseli = int(np.count_nonzero((reference_nir != 0) & (moving != 0)))
        status = "ok" if reliability >= 0.2 and n_pikseli >= 1000 else "porażka"
        uwagi = "NIR phase correlation" if status == "ok" else "niska reliability lub za mało wspólnych pikseli"
    except Exception as exc:
        dx_m = dy_m = reliability = 0.0
        n_pikseli = 0
        status = "porażka"
        uwagi = f"brak zbieżności: {exc}"
    row = {
        "product_id": product_id, "sensor": "EnMAP-day", "dx_m": dx_m,
        "dy_m": dy_m, "reliability": reliability, "n_pikseli": n_pikseli,
        "metoda": "phase_cross_correlation-NIR", "status": status, "uwagi": uwagi,
    }
    append_shift(row)
    return row


def find_pair_scenes(limit: int | None = None) -> pd.DataFrame:
    pairs = COREG_DIR.parent / "Reykjanes_data_inventory" / "out" / "pairs_hsi_landsat.csv"
    frame = pd.read_csv(pairs)
    frame = frame[frame["day_night"] == "night"].copy()
    if limit:
        frame = frame.head(limit)
    return frame


def list_enmap_scenes(level: str = "L1C") -> list[str]:
    objects = list_objects(f"{PREFIX}/roi/enmap/{level}/")
    return sorted({obj.rsplit("/", 1)[0] for obj in objects})


def register_night_pair(row: pd.Series, grid_path: Path = GRID_PATH) -> dict:
    """Match an EnMAP night product to paired Landsat using SWIR hot features."""
    product_id = str(row["product_id"])
    enmap_scenes = [scene for scene in list_enmap_scenes("L1C") if product_id in scene]
    if not enmap_scenes:
        enmap_scenes = [scene for scene in list_enmap_scenes("L2A") if product_id in scene]
    if not enmap_scenes:
        return {
            "product_id": product_id, "sensor": "EnMAP-night", "dx_m": 0.0,
            "dy_m": 0.0, "reliability": 0.0, "n_pikseli": 0,
            "metoda": "SWIR-B6/B7", "status": "porażka",
            "uwagi": "nie znaleziono sceny EnMAP w buckecie",
        }

    scene = enmap_scenes[0]
    xml = find_metadata(scene)
    summary = parse_enmap_metadata(xml)
    landsat_id = str(row["night_id"])
    landsat_scenes = [
        scene for scene in list_objects(f"{PREFIX}/roi/landsat/night/")
        if landsat_id in scene
    ]
    if not landsat_scenes:
        result = {
            "product_id": product_id, "sensor": "EnMAP-night", "dx_m": 0.0,
            "dy_m": 0.0, "reliability": 0.0, "n_pikseli": 0,
            "metoda": "SWIR-B6/B7", "status": "porażka",
            "uwagi": "nie znaleziono sparowanego nocnego Landsata",
        }
        append_shift(result)
        LOGGER.info("EnMAP geometry fields for %s: %d", product_id, len(summary))
        return result

    landsat_scene = landsat_scenes[0].rsplit("/", 1)[0]
    try:
        from .io_gcs import find_band
        landsat_b7 = find_band(landsat_scene, ("b7",))
        landsat_swir, _ = warp_to_grid(landsat_b7, 0.0, 0.0, grid_path)
        enmap_swir = read_enmap_band(scene, 2200, grid_path)
        dx_m, dy_m, reliability = phase_band(landsat_swir, enmap_swir)
        n_pikseli = int(np.count_nonzero((landsat_swir != 0) & (enmap_swir != 0)))
        status = "ok" if reliability >= 0.2 and n_pikseli >= 1000 else "porażka"
        uwagi = "SWIR 2200 nm vs Landsat B7" if status == "ok" else "niska reliability lub za mało wspólnych pikseli"
    except Exception as exc:
        dx_m = dy_m = reliability = 0.0
        n_pikseli = 0
        status = "porażka"
        uwagi = f"brak zbieżności SWIR: {exc}"
    result = {
        "product_id": product_id, "sensor": "EnMAP-night", "dx_m": dx_m,
        "dy_m": dy_m, "reliability": reliability, "n_pikseli": n_pikseli,
        "metoda": "SWIR-B7/2200nm", "status": status, "uwagi": uwagi,
    }
    append_shift(result)
    LOGGER.info("EnMAP geometry fields for %s: %d", product_id, len(summary))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse EnMAP metadata and register EnMAP scenes")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--day", action="store_true", help="Register daytime EnMAP scenes")
    parser.add_argument("--night-pairs", action="store_true", help="Process paired night metadata")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not GRID_PATH.exists():
        build_grid()
    if args.night_pairs:
        pairs = find_pair_scenes(args.limit)
        for _, row in pairs.iterrows():
            register_night_pair(row)

    if args.day:
        scene_prefix = list_scenes("day", "landsat")
        if not scene_prefix:
            raise RuntimeError("No Landsat day scenes")
        reference = scene_prefix[0]
        from .io_gcs import find_nir
        nir_url = find_nir(reference)
        nir, _ = warp_to_grid(nir_url, 0.0, 0.0, GRID_PATH)
        enmap_scenes = list_enmap_scenes("L1C") + list_enmap_scenes("L2A")
        if args.limit:
            enmap_scenes = enmap_scenes[: args.limit]
        for scene in enmap_scenes:
            register_day_scene(scene, nir)


if __name__ == "__main__":
    main()
