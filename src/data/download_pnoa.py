import os
import time

import requests
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from src.common.config import PNOA_DIR, get_bbox_tuple

# Número de divisiones
GRID_X = 5
GRID_Y = 5

# Imagen por tesela
# High-resolution imagery while keeping the same geographic grid.
IMAGE_WIDTH = 4096
IMAGE_HEIGHT = 4096
FALLBACK_IMAGE_WIDTH = 2048
FALLBACK_IMAGE_HEIGHT = 2048
REQUEST_RETRIES = 3
RESUME_EXISTING = True

OUTPUT_DIR = PNOA_DIR / "tiles"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Servicio WMS PNOA
WMS_URL = (
    "https://www.ign.es/wms-inspire/pnoa-ma"
)


def _save_tile(
    output_file,
    content: bytes,
    bbox: tuple[float, float, float, float],
    image_width: int,
    image_height: int,
) -> None:
    """Write a georeferenced GeoTIFF tile atomically."""
    temporary_file = output_file.with_name(
        f".{output_file.name}.{os.getpid()}.part"
    )
    min_lon, min_lat, max_lon, max_lat = bbox

    for attempt in range(3):
        try:
            with MemoryFile(content) as source_file:
                with source_file.open() as source:
                    profile = source.profile.copy()
                    profile.update(
                        driver="GTiff",
                        width=image_width,
                        height=image_height,
                        count=source.count,
                        dtype=source.dtypes[0],
                        crs="EPSG:4326",
                        transform=from_bounds(
                            min_lon,
                            min_lat,
                            max_lon,
                            max_lat,
                            image_width,
                            image_height,
                        ),
                        compress="deflate",
                    )

                    with rasterio.open(temporary_file, "w", **profile) as destination:
                        destination.write(source.read())
            os.replace(temporary_file, output_file)
            return
        except OSError:
            temporary_file.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(1)


def _download_image(params: dict) -> tuple[bytes, int, int]:
    """Download an image, falling back to a smaller size after WMS errors."""
    for attempt in range(1, REQUEST_RETRIES + 1):
        response = requests.get(WMS_URL, params=params, timeout=120)
        if response.ok:
            return response.content, params["WIDTH"], params["HEIGHT"]

        print(
            f"WMS error {response.status_code} "
            f"(attempt {attempt}/{REQUEST_RETRIES})"
        )
        if attempt < REQUEST_RETRIES:
            time.sleep(attempt * 2)

    fallback_params = params.copy()
    fallback_params["WIDTH"] = FALLBACK_IMAGE_WIDTH
    fallback_params["HEIGHT"] = FALLBACK_IMAGE_HEIGHT
    print(
        "Retrying tile at fallback resolution "
        f"{FALLBACK_IMAGE_WIDTH}x{FALLBACK_IMAGE_HEIGHT}"
    )
    fallback_response = requests.get(WMS_URL, params=fallback_params, timeout=120)
    fallback_response.raise_for_status()
    return (
        fallback_response.content,
        FALLBACK_IMAGE_WIDTH,
        FALLBACK_IMAGE_HEIGHT,
    )

def download_pnoa() -> None:
    """Download PNOA imagery for the configured pilot area."""
    min_lon, min_lat, max_lon, max_lat = get_bbox_tuple()
    lon_step = (max_lon - min_lon) / GRID_X
    lat_step = (max_lat - min_lat) / GRID_Y
    tile_id = 1
    total_tiles = GRID_X * GRID_Y

    for row in range(GRID_Y):
        for col in range(GRID_X):
            tile_min_lon = min_lon + col * lon_step
            tile_max_lon = tile_min_lon + lon_step
            tile_min_lat = min_lat + row * lat_step
            tile_max_lat = tile_min_lat + lat_step

            # WMS 1.3.0 + EPSG:4326 requires latitude,longitude axis order.
            bbox = (
                f"{tile_min_lat},{tile_min_lon},"
                f"{tile_max_lat},{tile_max_lon}"
            )
            params = {
                "SERVICE": "WMS",
                "VERSION": "1.3.0",
                "REQUEST": "GetMap",
                "LAYERS": "OI.OrthoimageCoverage",
                "CRS": "EPSG:4326",
                "BBOX": bbox,
                "WIDTH": IMAGE_WIDTH,
                "HEIGHT": IMAGE_HEIGHT,
                "FORMAT": "image/png",
                "STYLES": "",
            }

            output_file = OUTPUT_DIR / f"tile_{tile_id:03d}.tif"
            if RESUME_EXISTING and output_file.exists() and output_file.stat().st_size > 0:
                print(f"Skipping existing tile {tile_id:03d}/{total_tiles}")
                tile_id += 1
                continue

            print(f"Downloading tile {tile_id:03d}/{total_tiles}")
            image_data, image_width, image_height = _download_image(params)

            _save_tile(
                output_file,
                image_data,
                (tile_min_lon, tile_min_lat, tile_max_lon, tile_max_lat),
                image_width,
                image_height,
            )
            print(
                f"Saved {output_file} "
                f"({image_width}x{image_height})"
            )
            tile_id += 1

    print(f"Finished: {total_tiles} tiles")


if __name__ == "__main__":
    download_pnoa()