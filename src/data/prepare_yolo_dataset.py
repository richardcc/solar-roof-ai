from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from src.common.config import CATASTRO_DIR, PROCESSED_DATA_DIR
from src.common.fs import clear_directory

DEFAULT_IMAGES_DIR = CATASTRO_DIR / "building_crops"
DEFAULT_OUTPUT_DIR = PROCESSED_DATA_DIR / "yolo"
METRIC_CRS = "EPSG:25830"


def _pixel_bounds(geometry, transform: rasterio.Affine) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = geometry.bounds
    left, top = (~transform) * (min_x, max_y)
    right, bottom = (~transform) * (max_x, min_y)
    return left, top, right, bottom


def _square_window(
    geometry,
    transform: rasterio.Affine,
    offset_pixels: int,
) -> Window:
    left, top, right, bottom = _pixel_bounds(geometry, transform)
    side = max(right - left, bottom - top) + 2 * offset_pixels
    side = max(1, math.ceil(side))
    center_col = (left + right) / 2
    center_row = (top + bottom) / 2
    start_col = math.floor(center_col - side / 2)
    start_row = math.floor(center_row - side / 2)

    # Boundless reads keep the output square even when the building touches an edge.
    return Window(start_col, start_row, side, side)


def _buffer_geometry(geometry, source_crs, offset_meters: float):
    if offset_meters == 0:
        return geometry
    return (
        gpd.GeoSeries([geometry], crs=source_crs)
        .to_crs(METRIC_CRS)
        .buffer(offset_meters)
        .to_crs(source_crs)
        .iloc[0]
    )


def _polygon_lines(geometry, transform: rasterio.Affine, window: Window) -> list[str]:
    if isinstance(geometry, Polygon):
        polygons = [geometry]
    elif isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)
    else:
        polygons = [part for part in getattr(geometry, "geoms", []) if isinstance(part, Polygon)]

    lines = []
    for polygon in polygons:
        coordinates = []
        for x, y in polygon.exterior.coords:
            col, row = (~transform) * (x, y)
            col = (col - window.col_off) / window.width
            row = (row - window.row_off) / window.height
            coordinates.extend((min(1.0, max(0.0, col)), min(1.0, max(0.0, row))))
        if len(coordinates) >= 6:
            values = " ".join(f"{value:.6f}" for value in coordinates)
            lines.append(f"0 {values}")
    return lines


def prepare_sample(
    image_path: Path,
    building_path: Path,
    image_output_dir: Path,
    label_output_dir: Path,
    offset_meters: float,
) -> bool:
    building_frame = gpd.read_file(building_path)
    if building_frame.empty or building_frame.crs is None:
        return False

    with rasterio.open(image_path) as source:
        building_frame = building_frame.to_crs(source.crs)
        building_geometry = unary_union(
            [item for item in building_frame.geometry if item is not None and not item.is_empty]
        )
        if building_geometry.is_empty:
            return False

        window = _square_window(
            _buffer_geometry(building_geometry, source.crs, offset_meters),
            source.transform,
            0,
        )
        image = source.read(window=window, boundless=True, fill_value=0)
        crop_transform = source.window_transform(window)
        profile = source.profile.copy()
        profile.update(
            height=image.shape[1],
            width=image.shape[2],
            transform=crop_transform,
            compress="deflate",
        )

    image_output_dir.mkdir(parents=True, exist_ok=True)
    label_output_dir.mkdir(parents=True, exist_ok=True)
    output_image = image_output_dir / image_path.name
    output_label = label_output_dir / f"{image_path.stem}.txt"
    with rasterio.open(output_image, "w", **profile) as destination:
        destination.write(image)

    lines = _polygon_lines(
        building_geometry,
        crop_transform,
        Window(0, 0, image.shape[2], image.shape[1]),
    )
    output_label.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return bool(lines)


def prepare_dataset(
    images_dir: str | Path = DEFAULT_IMAGES_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    offset_meters: float = 10,
) -> int:
    if offset_meters < 0:
        raise ValueError("offset_meters must be non-negative")

    images_dir = Path(images_dir)
    output_dir = clear_directory(output_dir)
    image_paths = sorted(images_dir.glob("building_*.tif"))
    if not image_paths:
        raise FileNotFoundError(f"No images found in {images_dir}")

    processed = 0
    for image_path in image_paths:
        building_path = image_path.with_suffix(".geojson")
        if not building_path.exists():
            print(f"Skipping {image_path}: Catastro geometry not found")
            continue
        if prepare_sample(
            image_path,
            building_path,
            output_dir / "images",
            output_dir / "labels",
            offset_meters,
        ):
            processed += 1

    print(f"Finished: {processed} YOLO samples")
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create square YOLO samples from Catastro building crops"
    )
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--offset-meters",
        type=float,
        default=10,
        help="Context added around the Catastro building on every side",
    )
    args = parser.parse_args()
    prepare_dataset(args.images_dir, args.output_dir, args.offset_meters)


if __name__ == "__main__":
    main()
