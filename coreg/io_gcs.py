from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

import google.auth
import rasterio
from google.auth.transport.requests import Request
from google.cloud import storage
from rasterio.io import DatasetReader

LOGGER = logging.getLogger(__name__)
PROJECT = "magma-513619"
BUCKET = "magma-remote-sensing-2026"
PREFIX = "satellites"


def gcs_env() -> dict[str, str]:
    """Return GDAL options that use ADC and a short-lived bearer token."""
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/devstorage.read_only"]
    )
    creds.refresh(Request())
    return {
        "GDAL_HTTP_HEADERS": f"Authorization: Bearer {creds.token}",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_TIMEOUT": "120",
        "CPL_VSIL_CURL_CHUNK_SIZE": "4194304",
    }


def gcs_url(path: str) -> str:
    path = path.strip()
    if path.startswith("gs://"):
        path = path.removeprefix("gs://")
    return "/vsicurl/https://storage.googleapis.com/" + path


@contextmanager
def open_raster(path: str) -> Iterator[DatasetReader]:
    """Open a gs:// object directly with the proven ADC + rasterio pattern."""
    env = gcs_env()
    with rasterio.Env(**env):
        with rasterio.open(gcs_url(path)) as src:
            yield src


def list_objects(prefix: str) -> list[str]:
    prefix = prefix.removeprefix(f"gs://{BUCKET}/")
    client = storage.Client(project=PROJECT)
    bucket = client.bucket(BUCKET)
    objects = [f"gs://{BUCKET}/{b.name}" for b in bucket.list_blobs(prefix=prefix)]
    LOGGER.info("Listed %d objects under gs://%s/%s", len(objects), BUCKET, prefix)
    return objects


def list_scenes(day_night: str, sensor: str = "landsat") -> list[str]:
    prefix = f"{PREFIX}/roi/{sensor}/{day_night}/"
    objects = list_objects(prefix)
    if sensor == "landsat":
        marker = "/landsat/" + day_night + "/"
    else:
        marker = "/enmap/"
    scenes = sorted({obj.rsplit("/", 1)[0] for obj in objects if marker in obj})
    return scenes


def find_band(scene_path: str, candidates: Sequence[str]) -> str:
    objects = list_objects(scene_path)
    lowered = [(obj, obj.lower()) for obj in objects]
    for candidate in candidates:
        token = candidate.lower()
        for obj, name in lowered:
            if token in name and name.endswith((".tif", ".tiff")):
                return obj
    raise FileNotFoundError(
        f"No raster matching {list(candidates)} in gs://{BUCKET}/{scene_path}"
    )


def find_night_b10(scene_path: str) -> str:
    return find_band(scene_path, ("b10",))


def find_qa(scene_path: str) -> str:
    return find_band(scene_path, ("qa_pixel",))


def find_thermal_l2(scene_path: str) -> str:
    return find_band(scene_path, ("st_b10", "lwir11", "thermal"))


def find_nir(scene_path: str) -> str:
    return find_band(scene_path, ("sr_b5", "nir08", "b5", "nir"))


def find_metadata(scene_path: str) -> str:
    objects = list_objects(scene_path)
    for obj in objects:
        if obj.lower().endswith(".xml") or "metadata" in obj.lower():
            return obj
    raise FileNotFoundError(f"No EnMAP metadata XML in {scene_path}")
