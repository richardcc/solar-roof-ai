from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.merge import merge
from rasterio.transform import array_bounds
from shapely.geometry import box, mapping

from src.common.config import CATASTRO_DIR, PNOA_DIR, get_crop_settings, load_pilot_area
from src.common.fs import clear_directory
from src.data.catastro_filter import filter_buildings

DEFAULT_BUILDINGS_DIR = CATASTRO_DIR / "tiles"
DEFAULT_TILES_DIR = PNOA_DIR / "tiles"
DEFAULT_OUTPUT_DIR = CATASTRO_DIR / "building_crops"
METRIC_CRS = "EPSG:25830"
GEOJSON_CRS = "EPSG:4326"
ID_COLUMNS = ("reference", "localId", "gml_id")
INDEX_NAME = "index.geojson"

# Catastro attributes kept for UI localization / ficha del inmueble.
CATASTRO_INDEX_FIELDS = (
    "reference",
    "localId",
    "gml_id",
    "namespace",
    "currentUse",
    "conditionOfConstruction",
    "numberOfBuildingUnits",
    "numberOfDwellings",
    "numberOfFloorsAboveGround",
    "officialAreaReference",
    "value",
    "value_uom",
    "beginLifespanVersion",
    "beginning",
    "end",
    "documentLink",
    "informationSystem",
    "horizontalGeometryReference",
)


def _safe_id(value: object, fallback: int) -> str:
    """Return a filesystem-safe stable identifier."""
    text = str(value) if value is not None else ""
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return text or f"building_{fallback:06d}"


def _json_safe(value: object):
    """Convert pandas/numpy values into JSON-serializable Python objects."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return value


def _pilot_metadata() -> dict:
    config = load_pilot_area() or {}
    pilot = config.get("pilot_area") or {}
    return {
        "municipality": pilot.get("municipality"),
        "province": pilot.get("province"),
    }


def _catastro_properties(row: pd.Series) -> dict:
    properties = {}
    for field in CATASTRO_INDEX_FIELDS:
        if field in row.index:
            properties[field] = _json_safe(row[field])
    return properties


def load_buildings(buildings_dir: str | Path = DEFAULT_BUILDINGS_DIR) -> gpd.GeoDataFrame:
    """Load and deduplicate Catastro buildings (prefers buildings.geojson)."""
    buildings_dir = Path(buildings_dir)
    master = CATASTRO_DIR / "buildings.geojson"
    if master.exists():
        buildings = gpd.read_file(master)
    else:
        files = sorted(buildings_dir.glob("buildings_*.geojson"))
        if not files:
            raise FileNotFoundError(
                f"No building GeoJSON found in {master} or {buildings_dir}"
            )
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
    buildings = filter_buildings(buildings)
    if buildings.empty:
        raise RuntimeError(
            "No buildings left after Catastro filter. "
            "Relax catastro.* in configs/pilot_area.yaml"
        )
    buildings = buildings.reset_index(drop=True)
    buildings["_crop_id"] = range(1, len(buildings) + 1)
    return buildings


def _build_record(
    row: pd.Series,
    building_id: str,
    crop_id: int,
    building_geometry,
    source_crs,
    margin_meters: float,
    crop_mode: str,
    output_dir: Path,
    pilot: dict,
    source_tiles: list[str],
) -> dict:
    geometry_wgs84 = (
        gpd.GeoSeries([building_geometry], crs=source_crs)
        .to_crs(GEOJSON_CRS)
        .iloc[0]
    )
    centroid = geometry_wgs84.centroid
    min_lon, min_lat, max_lon, max_lat = geometry_wgs84.bounds
    properties = {
        "building_id": building_id,
        "crop_id": crop_id,
        "source_id": _json_safe(row.get("_building_id", "")),
        "margin_meters": margin_meters,
        "crop_mode": crop_mode,
        "source_tiles": ",".join(source_tiles),
        "source_tile_count": len(source_tiles),
        "crop_tif": f"{building_id}.tif",
        "crop_geojson": f"{building_id}.geojson",
        "crop_tif_path": str((output_dir / f"{building_id}.tif").resolve()),
        "crop_geojson_path": str((output_dir / f"{building_id}.geojson").resolve()),
        "centroid_lon": float(centroid.x),
        "centroid_lat": float(centroid.y),
        "bbox_min_lon": float(min_lon),
        "bbox_min_lat": float(min_lat),
        "bbox_max_lon": float(max_lon),
        "bbox_max_lat": float(max_lat),
        "municipality": pilot.get("municipality"),
        "province": pilot.get("province"),
        "status": "crop_ready",
        **_catastro_properties(row),
    }
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": mapping(geometry_wgs84),
    }


def write_building_index(features: list[dict], output_dir: Path) -> Path:
    """Write Catastro↔crop index used by the UI to locate parcels."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / INDEX_NAME
    document = {
        "type": "FeatureCollection",
        "name": "building_crops_index",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": features,
    }
    index_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {index_path} ({len(features)} buildings)")
    return index_path


def rebuild_index_from_crops(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> Path:
    """Rebuild index.geojson from existing building_*.geojson sidecars (no re-crop)."""
    output_dir = Path(output_dir)
    features: list[dict] = []
    for path in sorted(output_dir.glob("building_*.geojson")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("type") == "FeatureCollection":
            features.extend(document.get("features") or [])
        elif document.get("type") == "Feature":
            features.append(document)
    if not features:
        raise FileNotFoundError(
            f"No building_*.geojson sidecars found in {output_dir}. "
            "Run crop_buildings first."
        )
    return write_building_index(features, output_dir)


def _load_tile_index(tile_paths: list[Path]) -> gpd.GeoDataFrame:
    """Spatial index of PNOA tile footprints."""
    records = []
    for path in tile_paths:
        with rasterio.open(path) as source:
            records.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "crs": source.crs.to_string() if source.crs else None,
                    "geometry": box(*source.bounds),
                }
            )
    if not records:
        raise FileNotFoundError("No readable PNOA tiles")
    tile_index = gpd.GeoDataFrame(records, crs=records[0]["crs"])
    if tile_index.crs is None:
        raise ValueError("PNOA tiles have no CRS")
    return tile_index


def _mosaic_crop(
    tile_paths: list[Path],
    crop_geometry,
    nodata: int = 0,
) -> tuple[np.ndarray, rasterio.Affine, dict]:
    """Merge one or more PNOA tiles covering the full crop geometry bounds."""
    datasets = [rasterio.open(path) for path in tile_paths]
    try:
        mosaic, transform = merge(
            datasets,
            bounds=tuple(crop_geometry.bounds),
            nodata=nodata,
        )
        profile = datasets[0].profile.copy()
        profile.update(
            height=mosaic.shape[1],
            width=mosaic.shape[2],
            transform=transform,
            compress="deflate",
            nodata=nodata,
        )
        return mosaic, transform, profile
    finally:
        for dataset in datasets:
            dataset.close()


def crop_one_building(
    row: pd.Series,
    geometry_metric,
    tile_index: gpd.GeoDataFrame,
    output_dir: Path,
    margin_meters: float,
    crop_mode: str,
    pilot: dict,
) -> dict | None:
    """Crop the full building footprint, mosaicking tiles when it crosses edges."""
    if geometry_metric is None or geometry_metric.is_empty:
        return None

    buffered_metric = geometry_metric.buffer(margin_meters)
    crop_metric = buffered_metric if crop_mode == "rectangle" else geometry_metric
    if crop_metric.is_empty:
        return None

    crop_geom = (
        gpd.GeoSeries([crop_metric], crs=METRIC_CRS)
        .to_crs(tile_index.crs)
        .iloc[0]
    )
    building_geom = (
        gpd.GeoSeries([geometry_metric], crs=METRIC_CRS)
        .to_crs(tile_index.crs)
        .iloc[0]
    )

    hits = tile_index[tile_index.intersects(crop_geom)].copy()
    if hits.empty:
        return None

    # Prefer a single tile that fully contains the crop; else mosaic all hits.
    fully_containing = hits[hits.contains(crop_geom)]
    if len(fully_containing) == 1:
        selected = fully_containing
    elif len(fully_containing) > 1:
        # Area must be computed in a projected CRS (tiles are often EPSG:4326).
        overlap_metric = (
            fully_containing.to_crs(METRIC_CRS)
            .intersection(
                gpd.GeoSeries([crop_metric], crs=METRIC_CRS).iloc[0]
            )
            .area
        )
        selected = fully_containing.loc[[overlap_metric.idxmax()]]
    else:
        selected = hits

    tile_paths = [Path(path) for path in selected["path"].tolist()]
    try:
        mosaic, transform, profile = _mosaic_crop(tile_paths, crop_geom)
    except (ValueError, rasterio.errors.RasterioIOError, rasterio.errors.WindowError):
        return None

    if mosaic.size == 0 or mosaic.shape[1] == 0 or mosaic.shape[2] == 0:
        return None

    # Ensure mosaic covers crop bounds; trim nodata-only borders is optional.
    left, bottom, right, top = array_bounds(mosaic.shape[1], mosaic.shape[2], transform)
    mosaic_box = box(left, bottom, right, top)
    if not mosaic_box.intersects(crop_geom):
        return None

    if crop_mode == "shape":
        shape_mask = rasterize(
            [(building_geom, 1)],
            out_shape=(mosaic.shape[1], mosaic.shape[2]),
            transform=transform,
            fill=0,
            dtype="uint8",
        ).astype(bool)
        mosaic[:, ~shape_mask] = 0
        profile.update(nodata=0)

    crop_id = int(row["_crop_id"])
    building_id = f"building_{crop_id:06d}"
    output_file = output_dir / f"{building_id}.tif"
    with rasterio.open(output_file, "w", **profile) as destination:
        destination.write(mosaic)

    feature = _build_record(
        row=row,
        building_id=building_id,
        crop_id=crop_id,
        building_geometry=building_geom,
        source_crs=tile_index.crs,
        margin_meters=margin_meters,
        crop_mode=crop_mode,
        output_dir=output_dir,
        pilot=pilot,
        source_tiles=[path.name for path in tile_paths],
    )
    geometry_file = output_dir / f"{building_id}.geojson"
    geometry_file.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": [feature]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    reference = feature["properties"].get("reference") or building_id
    tile_note = (
        tile_paths[0].name
        if len(tile_paths) == 1
        else f"mosaic:{len(tile_paths)} tiles"
    )
    print(f"Saved {output_file} ({reference}, {tile_note})")
    return feature


def crop_all_buildings(
    buildings_dir: str | Path = DEFAULT_BUILDINGS_DIR,
    tiles_dir: str | Path = DEFAULT_TILES_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    margin_meters: float = 10,
    crop_mode: str = "rectangle",
) -> int:
    """Crop each building fully (single tile or mosaic across tile edges)."""
    if margin_meters < 0:
        raise ValueError("margin_meters must be non-negative")
    if crop_mode not in {"rectangle", "shape"}:
        raise ValueError("crop_mode must be 'rectangle' or 'shape'")

    buildings = load_buildings(buildings_dir)
    tile_paths = sorted(Path(tiles_dir).glob("*.tif"))
    if not tile_paths:
        raise FileNotFoundError(f"No GeoTIFF tiles found in {tiles_dir}")

    print(f"Loaded {len(buildings)} Catastro buildings, {len(tile_paths)} PNOA tiles")
    output_dir = clear_directory(output_dir)
    pilot = _pilot_metadata()
    tile_index = _load_tile_index(tile_paths)
    buildings_metric = buildings.to_crs(METRIC_CRS)

    index_features: list[dict] = []
    for index, row in buildings.iterrows():
        feature = crop_one_building(
            row=row,
            geometry_metric=buildings_metric.loc[index].geometry,
            tile_index=tile_index,
            output_dir=output_dir,
            margin_meters=margin_meters,
            crop_mode=crop_mode,
            pilot=pilot,
        )
        if feature is not None:
            index_features.append(feature)

    pending_count = len(buildings) - len(index_features)
    if pending_count:
        print(
            f"Warning: {pending_count} buildings were not cropped "
            "(outside PNOA tiles or failed mosaic)"
        )

    write_building_index(index_features, output_dir)
    print(f"Finished: {len(index_features)} building crops")
    return len(index_features)


def main() -> None:
    defaults = get_crop_settings()
    parser = argparse.ArgumentParser(
        description=(
            "Create one full GeoTIFF crop per Catastro building (mosaics PNOA "
            "tiles when a building crosses tile edges) and index.geojson"
        )
    )
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
    parser.add_argument(
        "--rebuild-index-only",
        action="store_true",
        help="Rebuild index.geojson from existing building_*.geojson without re-cropping",
    )
    args = parser.parse_args()

    if args.rebuild_index_only:
        rebuild_index_from_crops(args.output_dir)
        return

    crop_all_buildings(
        buildings_dir=args.buildings_dir,
        tiles_dir=args.tiles_dir,
        output_dir=args.output_dir,
        margin_meters=args.margin_meters,
        crop_mode=args.crop_mode,
    )


if __name__ == "__main__":
    main()
