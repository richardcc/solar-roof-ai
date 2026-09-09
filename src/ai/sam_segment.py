from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from shapely.geometry import box, mapping, shape
from ultralytics import SAM

from src.common.config import CATASTRO_DIR

DEFAULT_INPUT_DIR = CATASTRO_DIR / "building_crops"
DEFAULT_OUTPUT_DIR = CATASTRO_DIR / "sam_masks"
DEFAULT_MODEL = "sam2_b.pt"


def _pixel_box(geometry, transform, width: int, height: int) -> list[float]:
    """Convert a projected geometry bounds to a clamped pixel box."""
    min_x, min_y, max_x, max_y = geometry.bounds
    col_left, row_top = (~transform) * (min_x, max_y)
    col_right, row_bottom = (~transform) * (max_x, min_y)
    return [
        max(0.0, min(float(width), col_left)),
        max(0.0, min(float(height), row_top)),
        max(0.0, min(float(width), col_right)),
        max(0.0, min(float(height), row_bottom)),
    ]


def _save_mask(mask: np.ndarray, source: rasterio.DatasetReader, output_file: Path) -> None:
    profile = source.profile.copy()
    profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=0,
        compress="deflate",
    )
    with rasterio.open(output_file, "w", **profile) as destination:
        destination.write((mask > 0).astype("uint8") * 255, 1)


def _save_mask_geojson(
    mask: np.ndarray,
    source: rasterio.DatasetReader,
    output_file: Path,
    building_id: str,
    model_name: str,
    score: float | None,
) -> None:
    features = []
    binary_mask = (mask > 0).astype("uint8")
    for geometry, value in shapes(
        binary_mask,
        mask=binary_mask.astype(bool),
        transform=source.transform,
    ):
        if value != 1:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "building_id": building_id,
                    "model": model_name,
                    "score": score,
                },
                "geometry": mapping(shape(geometry)),
            }
        )

    document = {
        "type": "FeatureCollection",
        "name": f"{building_id}_sam_mask",
        "crs": {
            "type": "name",
            "properties": {"name": source.crs.to_string()},
        },
        "features": features,
    }
    output_file.write_text(json.dumps(document), encoding="utf-8")


def _prompt_mask(geometry, source: rasterio.DatasetReader) -> np.ndarray:
    """Rasterize the Catastro polygon on the image pixel grid."""
    return rasterize(
        [(geometry, 1)],
        out_shape=(source.height, source.width),
        transform=source.transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)


def _select_mask(masks: np.ndarray, prompt_mask: np.ndarray) -> np.ndarray | None:
    """Select the SAM mask with the strongest overlap with the building prompt."""
    if masks.ndim != 3 or masks.shape[0] == 0:
        return None

    binary_masks = masks > 0.5
    prompt_area = np.count_nonzero(prompt_mask)
    if prompt_area == 0:
        return None

    scores = []
    for candidate in binary_masks:
        intersection = np.count_nonzero(candidate & prompt_mask)
        union = np.count_nonzero(candidate | prompt_mask)
        scores.append(intersection / union if union else 0.0)

    best_index = int(np.argmax(scores))
    if scores[best_index] == 0:
        return None
    return binary_masks[best_index].astype("uint8")


def segment_building(
    model: SAM,
    image_path: Path,
    prompt_path: Path,
    output_dir: Path,
) -> bool:
    """Generate a SAM mask from one building crop and its Catastro polygon."""
    with rasterio.open(image_path) as source:
        image = source.read()
        if image.shape[0] < 3:
            raise ValueError(f"Expected an RGB image: {image_path}")
        image = np.moveaxis(image[:3], 0, -1)
        prompt = gpd.read_file(prompt_path)
        if prompt.empty or prompt.crs is None:
            return False
        prompt = prompt.to_crs(source.crs)
        geometry = prompt.geometry.iloc[0]
        if geometry.is_empty:
            return False

        bbox = _pixel_box(geometry, source.transform, source.width, source.height)
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            return False

        results = model.predict(source=image, bboxes=[bbox], verbose=False)
        if not results or results[0].masks is None:
            print(f"Skipping {image_path}: SAM returned no masks")
            return False

        masks = results[0].masks.data.detach().cpu().numpy()
        if masks.shape[0] == 0:
            print(f"Skipping {image_path}: SAM returned an empty mask set")
            return False

        mask = _select_mask(masks, _prompt_mask(geometry, source))
        if mask is None:
            print(f"Skipping {image_path}: no SAM mask overlaps the building prompt")
            return False
        if mask.shape != (source.height, source.width):
            raise ValueError(
                f"SAM mask shape {mask.shape} does not match image "
                f"{(source.height, source.width)}"
            )

        building_id = image_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        mask_path = output_dir / f"{building_id}_mask.tif"
        geojson_path = output_dir / f"{building_id}_mask.geojson"
        score = None
        if results[0].boxes is not None and len(results[0].boxes.conf) > 0:
            score = float(results[0].boxes.conf[0])
        _save_mask(mask, source, mask_path)
        _save_mask_geojson(
            mask,
            source,
            geojson_path,
            building_id,
            model.model_name if hasattr(model, "model_name") else "SAM",
            score,
        )
        print(f"Saved {mask_path} and {geojson_path}")
        return True


def segment_all(
    input_dir: str | Path = DEFAULT_INPUT_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    model_path: str = DEFAULT_MODEL,
) -> int:
    """Generate SAM masks for all TIFF/GeoJSON building crop pairs."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    model = SAM(model_path)
    processed = 0

    for image_path in sorted(input_dir.glob("building_*.tif")):
        prompt_path = image_path.with_suffix(".geojson")
        if not prompt_path.exists():
            print(f"Skipping {image_path}: prompt not found")
            continue
        if segment_building(model, image_path, prompt_path, output_dir):
            processed += 1

    print(f"Finished: {processed} SAM masks")
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SAM roof masks from building crops")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="SAM checkpoint or model name")
    args = parser.parse_args()
    segment_all(args.input_dir, args.output_dir, args.model)


if __name__ == "__main__":
    main()
