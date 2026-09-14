from pathlib import Path

path = Path(__file__).resolve().parents[1] / "data" / "download_catastro.py"
# script placed in tools/ or run from src - better use absolute
path = Path(r"C:\Users\ricardo.alba\Projects\solar-roof-ai\src\data\download_catastro.py")
text = path.read_text(encoding="utf-8")
start = text.index('    logger.info("Catastro buildings after filter:')
end = text.index('if __name__ == "__main__":')
new_tail = '''    logger.info("Catastro buildings after filter: %s / %s", len(gdf), raw_count)

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

    return gdf


'''
path.write_text(text[:start] + new_tail + text[end:], encoding="utf-8")
print("ok")
