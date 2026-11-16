import sys
import warnings

import rasterio

warnings.filterwarnings("ignore", category=FutureWarning)


def gcs_env():
    import google.auth
    from google.auth.transport.requests import Request
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
    creds.refresh(Request())
    return dict(GDAL_HTTP_HEADERS=f"Authorization: Bearer {creds.token}", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR")


def gcs_url(path):
    return "/vsicurl/https://storage.googleapis.com/" + path.removeprefix("gs://")


if __name__ == "__main__":
    with rasterio.Env(**gcs_env()), rasterio.open(gcs_url(sys.argv[1])) as src:
        print(src.profile)
        print("średnia z pasma 1:", src.read(1, masked=True).mean())