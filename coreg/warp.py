from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import reproject

from .io_gcs import gcs_env, gcs_url


def warp_to_grid(
    src_path: str,
    dx_m: float,
    dy_m: float,
    grid_path: str | Path = "coreg/grid.tif",
    is_qa: bool = False,
    dst_path: str | Path | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Translate src by (dx_m, dy_m) and resample it to the shared grid."""
    grid_path = Path(grid_path)
    with rasterio.open(grid_path) as grid:
        grid_profile = grid.profile.copy()
        grid_arr = grid.read(1)
        grid_crs = grid.crs
        grid_transform = grid.transform
        out_shape = (grid.height, grid.width)

    with rasterio.Env(**gcs_env()), rasterio.open(gcs_url(src_path)) as src:
        translated = Affine(
            src.transform.a,
            src.transform.b,
            src.transform.c + dx_m,
            src.transform.d,
            src.transform.e,
            src.transform.f + dy_m,
        )
        data = np.empty(out_shape, dtype=src.dtypes[0])
        reproject(
            source=rasterio.band(src, 1),
            destination=data,
            src_transform=translated,
            src_crs=src.crs,
            dst_transform=grid_transform,
            dst_crs=grid_crs,
            resampling=Resampling.nearest if is_qa else Resampling.bilinear,
            src_nodata=src.nodata,
            dst_nodata=0,
        )

    profile = grid_profile.copy()
    profile.update(
        driver="GTiff",
        dtype=str(data.dtype),
        count=1,
        compress="DEFLATE",
        height=out_shape[0],
        width=out_shape[1],
    )
    if dst_path is not None:
        dst_path = Path(dst_path)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(data, 1)
    return data, profile
