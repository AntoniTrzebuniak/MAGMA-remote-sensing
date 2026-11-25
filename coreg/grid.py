from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import rasterio
from rasterio.transform import from_origin

from .io_gcs import find_qa, find_thermal_l2, list_scenes, open_raster

from importlib import import_module

LOGGER = logging.getLogger(__name__)
COREG_DIR = Path(__file__).resolve().parent
GRID_PATH = COREG_DIR / "grid.tif"
PIXEL_SIZE = 30.0


def _roi_utm():
    common = import_module("Reykjanes_data_inventory.common")
    return common.ROI_UTM


def compute_grid(reference_scene: str | None = None) -> dict:
    roi = _roi_utm().buffer(2000)
    minx, miny, maxx, maxy = roi.bounds

    if reference_scene is None:
        scene = select_reference_scenes(limit=1)[0]
    else:
        scene = reference_scene

    thermal = find_thermal_l2(scene)
    with open_raster(thermal) as src:
        ref_transform = src.transform
    # Snap both corners to pixel multiples that start at the reference scene origin.
    origin_x = ref_transform.c + (minx - ref_transform.c) // PIXEL_SIZE * PIXEL_SIZE
    origin_y = ref_transform.f + ((maxy - ref_transform.f) + PIXEL_SIZE - 1) // PIXEL_SIZE * PIXEL_SIZE
    width = int((maxx - origin_x) / PIXEL_SIZE + 0.999999)
    height = int((origin_y - miny) / PIXEL_SIZE + 0.999999)
    origin_y = origin_y

    transform = from_origin(origin_x, origin_y, PIXEL_SIZE, PIXEL_SIZE)
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "count": 1,
        "width": width,
        "height": height,
        "crs": "EPSG:32627",
        "transform": transform,
        "compress": "DEFLATE",
        "nodata": 0,
    }
    return profile


def build_grid(reference_scene: str | None = None, output: str | Path = GRID_PATH) -> tuple[Path, dict]:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = compute_grid(reference_scene)
    import numpy as np
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(np.zeros((1, profile["height"], profile["width"]), dtype="uint8"))
    LOGGER.info("Wrote %s (%dx%d)", output, profile["width"], profile["height"])
    return output, profile


def select_reference_scenes(limit: int = 2) -> list[str]:
    """Prefer winter day scenes and rank them by estimated QA fill/cloud burden."""
    scenes = list_scenes("day", "landsat")
    ranked = []
    for scene in scenes:
        name = scene.rsplit("/", 1)[-1]
        match = re.search(r"_(20\d{2})(\d{2})\d{2}_", name)
        if not match:
            continue
        year = int(match.group(1))
        month_no = int(match.group(2))
        winter = month_no in (11, 12, 1, 2, 3)
        ranked.append((not winter, 1.0, name, scene))

    ranked.sort(key=lambda x: (x[0], x[1], x[2]))
    candidates = ranked[: max(limit * 5, 5)]
    measured = []
    for _, _, name, scene in candidates:
        try:
            qa = find_qa(scene)
            with open_raster(qa) as src:
                data = src.read(1, out_shape=(1, max(1, src.height // 8), max(1, src.width // 8)))
            cloud = ((data & ((1 << 3) | (1 << 4) | (1 << 5))) != 0).mean()
        except Exception:
            cloud = 1.0
        measured.append((cloud, name, scene))
    measured.sort(key=lambda x: (x[0], x[1]))
    selected = [row[2] for row in measured[:limit]]
    if not selected:
        raise RuntimeError("No daily Landsat L2 scenes found")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the shared 30 m Reykjanes grid")
    parser.add_argument("--reference", help="gs:// Landsat day scene")
    parser.add_argument("--output", default=str(GRID_PATH))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build_grid(args.reference, args.output)


if __name__ == "__main__":
    main()
