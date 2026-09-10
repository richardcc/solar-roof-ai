from __future__ import annotations

import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.features import geometry_window, rasterize
from shapely.geometry import box

from src.common.config import CATASTRO_DIR, PNOA_DIR, get_crop_settings
from src.common.fs import clear_directory

DEFAULT_BUILDINGS_DIR = CATASTRO_DIR / "tiles"
DEFAULT_TILES_DIR = PNOA_DIR / "tiles"
DEFAULT_OUTPUT_DIR = CATASTRO_DIR / "building_crops"
METRIC_CRS = "EPSG:25830"
ID_COLUMNS = ("reference", "localId", "gml_id")


def _safe_id(value: object, fallback: int) -> str:
    """Return a filesystem-safe stable identifier."""
    text = str(value) if value is not None else ""
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return text or f"building_{fallback:06d}"


def load_buildings(buildings_dir: str | Path = DEFAULT_BUILDINGS_DIR) -> gpd.GeoDataFrame:
    """Load and deduplicate Catastro building GeoJSON files."""
    buildings_dir = Path(buildings_dir)
    files = sorted(buildings_dir.glob("buildings_*.geojson"))
    if not files:
        raise FileNotFoundError(f"No building GeoJSON files found in {buildings_dir}")

    frames = [gpd.read_file(path) for path in files]
    buildings = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        crs=frames[0].crs,
    )
    if buildings.crs is None:
        raise ValueError("Building data has no CRS")

    id_column = next((column for column in ID_COLUMNS if column in buildings), None)
    if id_column is None:
        buildings["_building_id"] = [f"building_{idx:06d}" for idx in buildings.index]
    else:
        buildings["_building_key"] = buildings[id_column].fillna("").map(str)
        buildings = buildings.drop_duplicates("_building_key", keep="first")
        buildings["_building_id"] = [
            _safe_id(value, idx)
            for idx, value in zip(buildings.index, buildings["_building_key"])
        ]
        buildings = buildings.drop(columns="_building_key")

    buildings = buildings[buildings.geometry.notna() & ~buildings.geometry.is_empty].copy()
    buildings = buildings.reset_index(drop=True)
    buildings["_crop_id"] = range(1, len(buildings) + 1)
    return buildings


def crop_buildings(
    tile_path: str | Path,
    buildings_gdf: gpd.GeoDataFrame,
    output_dir: str | Path,
    margin_meters: float = 10,
    crop_mode: str = "rectangle",
) -> set[int]:
    """Crop one image per building using a rectangle or the building shape.

    Returns the set of ``_crop_id`` values successfully written from this tile.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if buildings_gdf.crs is None:
        raise ValueError("Building data has no CRS")
    if margin_meters < 0:
        raise ValueError("margin_meters must be non-negative")
    if crop_mode not in {"rectangle", "shape"}:
        raise ValueError("crop_mode must be 'rectangle' or 'shape'")

    buildings_metric = buildings_gdf.to_crs(METRIC_CRS)
    saved_ids: set[int] = set()
    with rasterio.open(tile_path) as source:
        buildings = buildings_metric.to_crs(source.crs)
        tile_geometry = box(*source.bounds)
        buildings = buildings[buildings.geometry.intersects(tile_geometry)]

        for fallback_index, row in buildings.iterrows():
            geometry_metric = buildings_metric.loc[row.name].geometry
            buffered_geometry = geometry_metric.buffer(margin_meters)
            buffered_geometry = gpd.GeoSeries(
                [buffered_geometry], crs=METRIC_CRS
            ).to_crs(source.crs).iloc[0]
            building_geometry = row.geometry

            crop_geometry = (
                buffered_geometry if crop_mode == "rectangle" else building_geometry
            ).intersection(tile_geometry)
            if crop_geometry.is_empty or building_geometry.is_empty:
                continue

            try:
                window = geometry_window(
                    source,
                    [crop_geometry],
                )
                cropped_image = source.read(window=window)
                cropped_transform = source.window_transform(window)
            except (ValueError, rasterio.errors.WindowError):
                continue

            profile = source.profile.copy()
            profile.update(
                height=cropped_image.shape[1],
                width=cropped_image.shape[2],
                transform=cropped_transform,
                compress="deflate",
            )

            if crop_mode == "shape":
                shape_mask = rasterize(
                    [(crop_geometry, 1)],
                    out_shape=(cropped_image.shape[1], cropped_image.shape[2]),
                    transform=cropped_transform,
                    fill=0,
                    dtype="uint8",
                ).astype(bool)
                cropped_image[:, ~shape_mask] = 0
                profile.update(nodata=0)

            crop_id = int(row.get("_crop_id", fallback_index + 1))
            building_id = f"building_{crop_id:06d}"
            output_file = output_dir / f"{building_id}.tif"
            with rasterio.open(output_file, "w", **profile) as destination:
                destination.write(cropped_image)

            geometry_file = output_dir / f"{building_id}.geojson"
            geometry_frame = gpd.GeoDataFrame(
                [
                    {
                        "building_id": building_id,
                        "source_id": row.get("_building_id", ""),
                        "margin_meters": margin_meters,
                        "crop_mode": crop_mode,
                        "geometry": building_geometry,
                    }
                ],
                crs=source.crs,
            )
            geometry_frame.to_file(geometry_file, driver="GeoJSON")
            saved_ids.add(crop_id)
            print(f"Saved {output_file} and {geometry_file}")

    return saved_ids


def crop_all_buildings(
    buildings_dir: str | Path = DEFAULT_BUILDINGS_DIR,
    tiles_dir: str | Path = DEFAULT_TILES_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    margin_meters: float = 10,
    crop_mode: str = "rectangle",
) -> int:
    """Load all Catastro buildings and crop them from all PNOA tiles."""
    buildings = load_buildings(buildings_dir)
    tile_paths = sorted(Path(tiles_dir).glob("*.tif"))
    if not tile_paths:
        raise FileNotFoundError(f"No GeoTIFF tiles found in {tiles_dir}")

    print(f"Loaded {len(buildings)} Catastro buildings, {len(tile_paths)} PNOA tiles")
    output_dir = clear_directory(output_dir)
    processed_ids: set[int] = set()
    total_saved = 0
    for tile_path in tile_paths:
        pending = buildings[~buildings["_crop_id"].isin(processed_ids)]
        if pending.empty:
            break
        saved_ids = crop_buildings(
            tile_path,
            pending,
            output_dir,
            margin_meters,
            crop_mode,
        )
        total_saved += len(saved_ids)
        processed_ids.update(saved_ids)

    pending_count = len(buildings) - len(processed_ids)
    if pending_count:
        print(
            f"Warning: {pending_count} buildings were not cropped "
            "(outside PNOA tiles or failed window)"
        )
    print(f"Finished: {total_saved} building crops")
    return total_saved


def main() -> None:
    defaults = get_crop_settings()
    parser = argparse.ArgumentParser(description="Create one GeoTIFF crop per Catastro building")
    parser.add_argument("--buildings-dir", type=Path, default=DEFAULT_BUILDINGS_DIR)
    parser.add_argument("--tiles-dir", type=Path, default=DEFAULT_TILES_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--margin-meters",
        type=float,
        default=defaults["margin_meters"],
        help=f"Buffer around building (default from config: {defaults['margin_meters']})",
    )
    parser.add_argument(
        "--crop-mode",
        choices=("rectangle", "shape"),
        default=defaults["mode"],
        help="rectangle keeps context around the building; shape masks outside it",
    )
    args = parser.parse_args()

    crop_all_buildings(
        buildings_dir=args.buildings_dir,
        tiles_dir=args.tiles_dir,
        output_dir=args.output_dir,
        margin_meters=args.margin_meters,
        crop_mode=args.crop_mode,
    )


if __name__ == "__main__":
    main()
