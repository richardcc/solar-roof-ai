import math
from xml.etree import ElementTree

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from owslib.wfs import WebFeatureService

from src.common.config import CATASTRO_DIR, get_bbox_tuple
from src.common.logger import get_logger

logger = get_logger(__name__)

WFS_URL = "https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx"
WFS_SRS = "EPSG:25830"
GEOJSON_CRS = "EPSG:4326"
WFS_TIMEOUT_SECONDS = 120
TILE_SIZE_METERS = 1000


def _prepare_gml_frame(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Convert datetime fields to GML-compatible ISO text values."""
    gml_gdf = gdf.copy()

    for column in gml_gdf.columns:
        if pd.api.types.is_datetime64_any_dtype(gml_gdf[column]):
            gml_gdf[column] = gml_gdf[column].dt.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

    return gml_gdf


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
):
    """
    Download building data from Catastro INSPIRE WFS.
    """
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

    tile_dir = CATASTRO_DIR / "tiles"
    tile_dir.mkdir(parents=True, exist_ok=True)

    # Keep tile GML files for QGIS and remove only GDAL sidecar files.
    for tile_sidecar_file in tile_dir.glob("buildings_*.gfs"):
        tile_sidecar_file.unlink()

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

    output_file = CATASTRO_DIR / "buildings.gml"

    try:
        _prepare_gml_frame(gdf).to_file(output_file, driver="GML")

        logger.info(f"Saved GML: {output_file}")

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

        geojson_file = (
            CATASTRO_DIR / "buildings.geojson"
        )

        gdf.to_crs(GEOJSON_CRS).to_file(
            geojson_file,
            driver="GeoJSON",
        )

        logger.info(
            f"Saved GeoJSON: {geojson_file}"
        )

        return gdf

    except Exception as ex:

        logger.error("Unable to write output files: %s", ex)

        raise


if __name__ == "__main__":
    download_catastro()