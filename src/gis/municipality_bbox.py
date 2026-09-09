from typing import Tuple

import geopandas as gpd


def get_municipality_bbox(
    municipalities_file: str,
    municipality_name: str
) -> Tuple[float, float, float, float]:
    """
    Returns municipality bounding box.

    Parameters
    ----------
    municipalities_file : str
        Path to municipalities shapefile/geopackage.
    municipality_name : str
        Municipality name.

    Returns
    -------
    tuple
        (minx, miny, maxx, maxy)
    """

    gdf = gpd.read_file(municipalities_file)

    municipality = gdf[
        gdf["NAMEUNIT"].str.upper() == municipality_name.upper()
    ]

    if municipality.empty:
        raise ValueError(
            f"Municipality '{municipality_name}' not found."
        )

    return municipality.total_bounds


if __name__ == "__main__":

    bbox = get_municipality_bbox(
        municipalities_file=r"C:\repos\python\solar-roof-ai\data\raw\municipalities\municipalities.gpkg",
        municipality_name="Málaga"
    )

    print("BBox:")
    print(f"minx={bbox[0]}")
    print(f"miny={bbox[1]}")
    print(f"maxx={bbox[2]}")
    print(f"maxy={bbox[3]}")