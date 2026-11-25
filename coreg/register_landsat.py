from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter, sobel
from skimage.registration import phase_cross_correlation

from .grid import GRID_PATH, build_grid, select_reference_scenes
from .io_gcs import find_night_b10, find_qa, list_scenes
from .warp import warp_to_grid

LOGGER = logging.getLogger(__name__)
COREG_DIR = Path(__file__).resolve().parent
SHIFTS_CSV = COREG_DIR / "shifts.csv"
SHIFT_COLUMNS = [
    "product_id",
    "sensor",
    "dx_m",
    "dy_m",
    "reliability",
    "n_pikseli",
    "metoda",
    "status",
    "uwagi",
]


def rasterize_mask_geojson(path: Path, grid_path: Path = GRID_PATH) -> np.ndarray:
    """Rasterize a polygon mask onto the common grid (True = masked)."""
    if not path.exists():
        return np.zeros(rasterio_profile_shape(grid_path), dtype=bool)
    import geopandas as gpd
    import rasterio
    from rasterio.features import geometry_mask

    frame = gpd.read_file(path)
    with rasterio.open(grid_path) as grid:
        shapes = frame.to_crs(grid.crs).geometry
        return geometry_mask(
            (g for g in shapes if g is not None),
            out_shape=(grid.height, grid.width),
            transform=grid.transform,
            invert=True,
        )


def rasterio_profile_shape(grid_path: Path) -> tuple[int, int]:
    import rasterio
    with rasterio.open(grid_path) as src:
        return src.height, src.width


def qa_night_mask(qa: np.ndarray) -> np.ndarray:
    """Mask Landsat fill and visibly cloudy/snowy QA classes."""
    fill = (qa & (1 << 0)) != 0
    cloud = (qa & ((1 << 1) | (1 << 3) | (1 << 4) | (1 << 5))) != 0
    return fill | cloud


def gradient_features(image: np.ndarray, mask: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    image = image.astype("float32")
    valid = mask & np.isfinite(image)
    image = np.where(valid, image, np.nanmedian(image))
    image = gaussian_filter(image, sigma=sigma)
    gx = sobel(image, axis=1)
    gy = sobel(image, axis=0)
    magnitude = np.hypot(gx, gy)
    magnitude[~valid] = 0
    magnitude = np.nan_to_num(magnitude)
    return magnitude


def phase_shift(
    reference: np.ndarray,
    moving: np.ndarray,
    reference_mask: np.ndarray,
    moving_mask: np.ndarray,
    upsample_factor: int = 10,
) -> tuple[tuple[float, float], float]:
    ref = gradient_features(reference, reference_mask)
    mov = gradient_features(moving, moving_mask)
    shift, error, phasediff = phase_cross_correlation(
        ref,
        mov,
        upsample_factor=upsample_factor,
        reference_mask=reference_mask,
        moving_mask=moving_mask,
        normalization="phase",
    )
    reliability = float(max(0.0, 1.0 - error))
    return (float(shift[1]), float(shift[0])), reliability


def add_cold_spot_mask(
    data: np.ndarray,
    valid: np.ndarray,
    percentile: float = 8.0,
) -> np.ndarray:
    """Mask unusually cold outlier land pixels that are likely clouds or snow."""
    values = data[valid & np.isfinite(data)]
    if values.size < 100:
        return valid
    threshold = np.percentile(values, percentile)
    cold = np.isfinite(data) & (data < threshold)
    return valid & ~cold


def read_nightly_on_grid(scene: str, grid_path: Path) -> tuple[np.ndarray, np.ndarray]:
    b10 = find_night_b10(scene)
    qa_path = find_qa(scene)
    b10_data, _ = warp_to_grid(str(b10), 0.0, 0.0, grid_path=grid_path)
    qa_data, _ = warp_to_grid(str(qa_path), 0.0, 0.0, grid_path=grid_path, is_qa=True)
    qa_bad = qa_night_mask(qa_data.astype(np.uint32))
    return b10_data, qa_bad


def residual_shift(
    reference: np.ndarray,
    moved: np.ndarray,
    ref_mask: np.ndarray,
    mov_mask: np.ndarray,
) -> tuple[float, float]:
    shift_px, _ = phase_shift(reference, moved, ref_mask, mov_mask)
    return shift_px[0] * 30.0, shift_px[1] * 30.0


def local_check(
    reference: np.ndarray,
    moving: np.ndarray,
    reference_mask: np.ndarray,
    moving_mask: np.ndarray,
    window_size: int = 450,
) -> dict:
    shifts = []
    height, width = reference.shape
    for y in range(0, height, window_size):
        for x in range(0, width, window_size):
            y1, x1 = min(y + window_size, height), min(x + window_size, width)
            if y1 - y < window_size // 2 or x1 - x < window_size // 2:
                continue
            ry, mx = reference[y:y1, x:x1], moving[y:y1, x:x1]
            rm, mm = reference_mask[y:y1, x:x1], moving_mask[y:y1, x:x1]
            if rm.sum() < 300 or mm.sum() < 300:
                continue
            try:
                (sx, sy), reliability = phase_shift(ry, mx, rm, mm)
                if reliability >= 0.2:
                    shifts.append((sx, sy))
            except Exception as exc:
                LOGGER.debug("Local window failed: %s", exc)
    if not shifts:
        return {"n_windows": 0, "spread_px": float("nan"), "median_dx_px": float("nan"),
                "median_dy_px": float("nan")}
    arr = np.asarray(shifts)
    spread = float(np.sqrt(np.nanmedian((arr[:, 0] - np.nanmedian(arr[:, 0])) ** 2)
                           + np.nanmedian((arr[:, 1] - np.nanmedian(arr[:, 1])) ** 2)))
    return {
        "n_windows": len(shifts),
        "spread_px": spread,
        "median_dx_px": float(np.nanmedian(arr[:, 0])),
        "median_dy_px": float(np.nanmedian(arr[:, 1])),
    }


def append_shift(row: dict, csv_path: Path = SHIFTS_CSV) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHIFT_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in SHIFT_COLUMNS})


def register_scene(
    scene: str,
    reference_thermal: np.ndarray,
    reference_mask: np.ndarray,
    grid_path: Path = GRID_PATH,
    cold_percentile: float = 8.0,
) -> dict:
    product_id = scene.rsplit("/", 1)[-1]
    moving, qa_bad = read_nightly_on_grid(scene, grid_path)
    lava_path = COREG_DIR / "masks" / "lava_2021_2025_buf300m.geojson"
    lava_mask = rasterize_mask_geojson(lava_path, grid_path)
    coast_path = COREG_DIR / "masks" / "coastline.geojson"
    coast_mask = rasterize_mask_geojson(coast_path, grid_path)

    valid_ref = reference_mask & ~coast_mask
    valid_moving = ~qa_bad & ~lava_mask & ~coast_mask
    valid_moving = add_cold_spot_mask(moving, valid_moving, cold_percentile)

    n_edge = int(valid_ref.sum() + valid_moving.sum())
    if n_edge < 1000:
        row = dict(product_id=product_id, sensor="Landsat-night", dx_m=0.0, dy_m=0.0,
                   reliability=0.0, n_pikseli=n_edge, metoda="phase_cross_correlation",
                   status="porażka", uwagi="za mało ważnych pikseli po maskowaniu")
        append_shift(row)
        return row

    try:
        (dx_px, dy_px), reliability = phase_shift(
            reference_thermal, moving, valid_ref, valid_moving
        )
        dx_m, dy_m = dx_px * 30.0, dy_px * 30.0
        moved, _ = warp_to_grid(find_night_b10(scene), dx_m, dy_m, grid_path, False)
        residual_dx, residual_dy = residual_shift(
            reference_thermal, moved, valid_ref, valid_moving
        )
        residual_px = float(np.hypot(residual_dx, residual_dy) / 30.0)
        n_pikseli = int(valid_ref.sum() + valid_moving.sum())
        if residual_px < 0.3 and n_pikseli >= 1000 and reliability >= 0.2:
            status, uwagi = "ok", "global phase correlation; residual verified"
        else:
            status = "porażka"
            if residual_px >= 0.3:
                uwagi = f"niewystarczająca zbieżność; resztkowo {residual_px:.2f} px"
            elif reliability < 0.2:
                uwagi = "niska reliability korelacji"
            else:
                uwagi = "za mało ważnych pikseli lub krawędzi"
    except Exception as exc:
        dx_m = dy_m = reliability = 0.0
        n_pikseli = n_edge
        status = "porażka"
        uwagi = f"brak zbieżności korelacji: {exc}"

    row = dict(product_id=product_id, sensor="Landsat-night", dx_m=float(dx_m),
               dy_m=float(dy_m), reliability=float(reliability),
               n_pikseli=int(n_pikseli), metoda="phase_cross_correlation",
               status=status, uwagi=uwagi)
    append_shift(row)
    return row


def export_scene(scene: str, dx_m: float, dy_m: float, grid_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    product = scene.rsplit("/", 1)[-1]
    b10 = find_night_b10(scene)
    warp_to_grid(b10, 0.0, 0.0, grid_path, False, out_dir / f"{product}_before.tif")
    warp_to_grid(b10, dx_m, dy_m, grid_path, False, out_dir / f"{product}_after.tif")


def main() -> None:
    parser = argparse.ArgumentParser(description="Co-register nightly Landsat scenes")
    parser.add_argument("--limit", type=int, help="Process only the first N scenes")
    parser.add_argument("--local-check", action="store_true")
    parser.add_argument("--reference", help="gs:// Landsat L2 day scene")
    parser.add_argument("--cold-percentile", type=float, default=8.0)
    parser.add_argument("--export-dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not GRID_PATH.exists():
        build_grid(args.reference)
    references = select_reference_scenes(limit=1)
    reference_scene = args.reference or references[0]
    thermal = find_night_b10(reference_scene) if "/night/" in reference_scene else None
    if thermal is None:
        from .io_gcs import find_thermal_l2
        thermal = find_thermal_l2(reference_scene)
    ref_data, _ = warp_to_grid(str(thermal), 0.0, 0.0, GRID_PATH)
    ref_mask = np.isfinite(ref_data)
    scenes = list_scenes("night", "landsat")
    if args.limit:
        scenes = scenes[: args.limit]

    local_reports = []
    for scene in scenes:
        LOGGER.info("Registering %s", scene.rsplit("/", 1)[-1])
        row = register_scene(
            scene, ref_data, ref_mask, GRID_PATH, args.cold_percentile
        )
        if args.export_dir and row["status"] == "ok":
            export_scene(scene, row["dx_m"], row["dy_m"], GRID_PATH, args.export_dir)
        if args.local_check:
            moving, qa_bad = read_nightly_on_grid(scene, GRID_PATH)
            valid_ref = ref_mask & ~rasterize_mask_geojson(COREG_DIR / "masks" / "coastline.geojson")
            valid_moving = ~qa_bad
            report = local_check(ref_data, moving, valid_ref, valid_moving)
            report["product_id"] = scene.rsplit("/", 1)[-1]
            local_reports.append(report)
            LOGGER.info("Local check %s: %s", report["product_id"], report)

    if args.local_check:
        local_path = COREG_DIR / "local_check.csv"
        pd.DataFrame(local_reports).to_csv(local_path, index=False)
        LOGGER.info("Saved local test report to %s", local_path)


if __name__ == "__main__":
    main()
