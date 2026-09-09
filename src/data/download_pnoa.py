from __future__ import annotations

import argparse
import os
import time

import requests
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from src.common.config import (
    PNOA_DIR,
    get_bbox_tuple,
    get_pnoa_settings,
)
from src.common.fs import clear_directory

REQUEST_RETRIES = 3
OUTPUT_DIR = PNOA_DIR / "tiles"

# Servicio WMS PNOA
WMS_URL = "https://www.ign.es/wms-inspire/pnoa-ma"


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


def _download_image(
    params: dict,
    fallback_size: int,
) -> tuple[bytes, int, int]:
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
    fallback_params["WIDTH"] = fallback_size
    fallback_params["HEIGHT"] = fallback_size
    print(f"Retrying tile at fallback resolution {fallback_size}x{fallback_size}")
    fallback_response = requests.get(WMS_URL, params=fallback_params, timeout=120)
    fallback_response.raise_for_status()
    return fallback_response.content, fallback_size, fallback_size


def download_pnoa(
    grid: int | None = None,
    size: int | None = None,
    fallback_size: int | None = None,
) -> None:
    """Download PNOA imagery for the configured pilot area."""
    settings = get_pnoa_settings()
    grid_x = grid if grid is not None else settings["grid"]
    grid_y = grid_x
    image_size = size if size is not None else settings["size"]
    fallback = (
        fallback_size if fallback_size is not None else settings["fallback_size"]
    )

    if grid_x < 1:
        raise ValueError("grid must be >= 1")
    if image_size < 1:
        raise ValueError("size must be >= 1")
    if fallback < 1:
        raise ValueError("fallback_size must be >= 1")

    clear_directory(OUTPUT_DIR)
    min_lon, min_lat, max_lon, max_lat = get_bbox_tuple()
    lon_step = (max_lon - min_lon) / grid_x
    lat_step = (max_lat - min_lat) / grid_y
    tile_id = 1
    total_tiles = grid_x * grid_y

    print(
        f"PNOA download: grid={grid_x}x{grid_y}, "
        f"size={image_size}, fallback={fallback}, tiles={total_tiles}"
    )

    for row in range(grid_y):
        for col in range(grid_x):
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
                "WIDTH": image_size,
                "HEIGHT": image_size,
                "FORMAT": "image/png",
                "STYLES": "",
            }

            output_file = OUTPUT_DIR / f"tile_{tile_id:03d}.tif"
            print(f"Downloading tile {tile_id:03d}/{total_tiles}")
            image_data, image_width, image_height = _download_image(params, fallback)

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


def main() -> None:
    defaults = get_pnoa_settings()
    parser = argparse.ArgumentParser(
        description="Download PNOA WMS tiles for the configured pilot area"
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=None,
        help=(
            "Tiles along X and Y "
            f"(default from configs/pilot_area.yaml: {defaults['grid']})"
        ),
    )
    parser.add_argument(
        "--size",
        type=int,
        default=None,
        help=(
            "WMS tile width/height in pixels "
            f"(default from configs/pilot_area.yaml: {defaults['size']})"
        ),
    )
    parser.add_argument(
        "--fallback-size",
        type=int,
        default=None,
        help=(
            "Fallback WMS size after errors "
            f"(default from configs/pilot_area.yaml: {defaults['fallback_size']})"
        ),
    )
    args = parser.parse_args()
    download_pnoa(
        grid=args.grid,
        size=args.size,
        fallback_size=args.fallback_size,
    )


if __name__ == "__main__":
    main()
