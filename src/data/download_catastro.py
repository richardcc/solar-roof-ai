import math
from xml.etree import ElementTree

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from owslib.wfs import WebFeatureService

from src.common.config import CATASTRO_DIR, get_bbox_tuple
from src.common.fs import clear_directory
from src.common.logger import get_logger
from src.data.catastro_filter import filter_buildings

logger = get_logger(__name__)

WFS_URL = "https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx"
WFS_SRS = "EPSG:25830"
GEOJSON_CRS = "EPSG:4326"
WFS_TIMEOUT_SECONDS = 120
TILE_SIZE_METERS = 1000


def _prepare_export_frame(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Normalize dtypes so GeoJSON/GML writers do not choke on datetimes."""
    export_gdf = gdf.copy()

    for column in export_gdf.columns:
        if column == "geometry":
            continue
        series = export_gdf[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            export_gdf[column] = (
                pd.to_datetime(series, utc=True, errors="coerce")
                .dt.strftime("%Y-%m-%dT%H:%M:%S")
            )
            continue
        if pd.api.types.is_timedelta64_dtype(series):
            export_gdf[column] = series.astype(str)
            continue
        if series.dtype == object:
            sample = series.dropna().head(5)
            if not sample.empty and all(
                hasattr(value, "isoformat") for value in sample
            ):
                export_gdf[column] = series.map(
                    lambda value: value.isoformat() if hasattr(value, "isoformat") else value
                )

    return export_gdf


def _iter_tiles(
    bbox: tuple[float, float, float, float],
    tile_size: int = TILE_SIZE_METERS,
):
    """Yield projected BBOX tiles covering the requested area."""
    min_x, min_y, max_x, max_y = bbox
    x_steps = range(math.floor(min_x), math.ceil(max_x), tile_size)
    y_steps = range(math.floor(min_y), math.ceil(max_y), tile_size)

    for x in x_steps:
        for y in y_steps:
            yield (
                x,
                y,
                min(x + tile_size, max_x),
                min(y + tile_size, max_y),
            )


def download_catastro(
    min_lon: float | None = None,
    min_lat: float | None = None,
    max_lon: float | None = None,
    max_lat: float | None = None,
    bbox: tuple | None = None,
    from_existing_tiles: bool = False,
):
    """
    Download building data from Catastro INSPIRE WFS.
    """
    if from_existing_tiles:
        return export_buildings_from_existing_tiles()

    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
    elif min_lon is None or min_lat is None or max_lon is None or max_lat is None:
        min_lon, min_lat, max_lon, max_lat = get_bbox_tuple()

    logger.info("Connecting to Catastro WFS")

    wfs = WebFeatureService(
        url=WFS_URL,
        version="2.0.0",
        timeout=WFS_TIMEOUT_SECONDS,
    )

    transformer = Transformer.from_crs("EPSG:4326", WFS_SRS, always_xy=True)
    projected_bbox = (
        *transformer.transform(min_lon, min_lat),
        *transformer.transform(max_lon, max_lat),
    )

    CATASTRO_DIR.mkdir(parents=True, exist_ok=True)
    tile_dir = clear_directory(CATASTRO_DIR / "tiles")
    for stale_file in (
        CATASTRO_DIR / "buildings.gml",
        CATASTRO_DIR / "buildings.geojson",
        CATASTRO_DIR / "response_preview.xml",
    ):
        stale_file.unlink(missing_ok=True)

    tile_frames = []
    tiles = list(_iter_tiles(projected_bbox))
    skipped_tiles = 0

    logger.info(
        "Requesting bu:Building layer in %s tiles of 1 km",
        len(tiles),
    )

    for tile_number, tile_bbox in enumerate(tiles, start=1):
        logger.info("Downloading tile %s/%s", tile_number, len(tiles))
        response = wfs.getfeature(
            typename=["bu:Building"],
            bbox=tile_bbox,
            srsname=WFS_SRS,
        )
        data = response.read()

        if b"ExceptionReport" in data:
            try:
                root = ElementTree.fromstring(data)
                exception_node = next(
                    node for node in root.iter() if node.tag.endswith("ExceptionText")
                )
                exception_text = " ".join((exception_node.text or "").split())
            except (ElementTree.ParseError, StopIteration):
                exception_text = "Unknown Catastro WFS error"

            if "No records" in exception_text:
                logger.info("Tile %s has no buildings", tile_number)
                skipped_tiles += 1
                continue

            preview_file = CATASTRO_DIR / "response_preview.xml"
            preview_file.write_bytes(data[:5000])
            raise RuntimeError(
                f"Catastro rejected tile {tile_number}: {exception_text}. "
                f"See the server response in {preview_file}."
            )

        tile_file = tile_dir / f"buildings_{tile_number}.gml"
        tile_file.write_bytes(data)
        try:
            tile_frame = gpd.read_file(tile_file)
        except (IndexError, ValueError, RuntimeError) as ex:
            logger.warning(
                "Skipping unreadable or empty tile %s: %s",
                tile_number,
                ex,
            )
            skipped_tiles += 1
            continue
        finally:
            tile_file.with_suffix(".gfs").unlink(missing_ok=True)

        if tile_frame.empty:
            logger.info("Tile %s contains no buildings", tile_number)
            skipped_tiles += 1
            continue

        tile_geojson_file = tile_dir / f"buildings_{tile_number}.geojson"
        tile_frame.to_crs(GEOJSON_CRS).to_file(
            tile_geojson_file,
            driver="GeoJSON",
        )
        logger.info("Saved tile GeoJSON: %s", tile_geojson_file)

        tile_frames.append(tile_frame)
        logger.info(
            "Tile %s/%s complete: %s buildings",
            tile_number,
            len(tiles),
            len(tile_frame),
        )

    if not tile_frames:
        raise RuntimeError("Catastro returned no buildings for the configured pilot area")

    gdf = gpd.GeoDataFrame(
        pd.concat(tile_frames, ignore_index=True),
        crs=tile_frames[0].crs,
    )
    raw_count = len(gdf)
    gdf = filter_buildings(gdf)
    if gdf.empty:
        raise RuntimeError(
            "Catastro filter removed all buildings. "
            "Relax catastro.* settings in configs/pilot_area.yaml"
        )
    logger.info("Catastro buildings after filter: %s / %s", len(gdf), raw_count)

    export_gdf = _prepare_export_frame(gdf)
    geojson_file = CATASTRO_DIR / "buildings.geojson"
    gml_file = CATASTRO_DIR / "buildings.gml"

    try:
        export_gdf.to_crs(GEOJSON_CRS).to_file(geojson_file, driver="GeoJSON")
        logger.info("Saved GeoJSON: %s", geojson_file)
    except Exception as ex:
        logger.error("Unable to write GeoJSON: %s", ex)
        raise

    try:
        export_gdf.to_file(gml_file, driver="GML")
        logger.info("Saved GML: %s", gml_file)
    except Exception as ex:
        logger.warning("Unable to write GML (GeoJSON is available): %s", ex)

    logger.info(
        "Final statistics: tiles=%s, valid_tiles=%s, skipped_tiles=%s, "
        "buildings=%s, crs=%s, bounds=%s",
        len(tiles),
        len(tile_frames),
        skipped_tiles,
        len(gdf),
        gdf.crs,
        tuple(round(value, 2) for value in gdf.total_bounds),
    )

    return export_gdf


def export_buildings_from_existing_tiles() -> gpd.GeoDataFrame:
    """Rebuild filtered buildings.geojson from already downloaded tile GeoJSONs."""
    tile_dir = CATASTRO_DIR / "tiles"
    files = sorted(tile_dir.glob("buildings_*.geojson"))
    if not files:
        raise FileNotFoundError(f"No tile GeoJSON files found in {tile_dir}")

    frames = [gpd.read_file(path) for path in files]
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    raw_count = len(gdf)
    gdf = filter_buildings(gdf)
    if gdf.empty:
        raise RuntimeError(
            "Catastro filter removed all buildings. "
            "Relax catastro.* settings in configs/pilot_area.yaml"
        )
    logger.info("Catastro buildings after filter: %s / %s", len(gdf), raw_count)

    export_gdf = _prepare_export_frame(gdf)
    geojson_file = CATASTRO_DIR / "buildings.geojson"
    gml_file = CATASTRO_DIR / "buildings.gml"
    export_gdf.to_crs(GEOJSON_CRS).to_file(geojson_file, driver="GeoJSON")
    logger.info("Saved GeoJSON: %s", geojson_file)
    try:
        export_gdf.to_file(gml_file, driver="GML")
        logger.info("Saved GML: %s", gml_file)
    except Exception as ex:
        logger.warning("Unable to write GML (GeoJSON is available): %s", ex)
    return export_gdf


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download Catastro buildings")
    parser.add_argument(
        "--from-existing-tiles",
        action="store_true",
        help="Rebuild buildings.geojson from data/raw/catastro/tiles without WFS download",
    )
    args = parser.parse_args()
    download_catastro(from_existing_tiles=args.from_existing_tiles)
