from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

from src.common.config import CATASTRO_DIR, PROJECT_ROOT, load_pilot_area
from src.data.pnoa_hires import (
    ensure_hires_crop,
    hires_exists,
    hires_tif_path,
    open_hires_rgb,
)
from src.gis.roof_mask import (
    ALGORITHMS,
    MaskClass,
    decode_labels_png,
    decode_mask_png,
    detect_regions,
    encode_labels_png,
    encode_mask_png,
    region_summaries,
    regions_overlay_rgba,
    run_algorithm,
    run_algorithm_on_region,
)

WEB_DIR = PROJECT_ROOT / "web"
INDEX_PATH = CATASTRO_DIR / "building_crops" / "index.geojson"
CROPS_DIR = CATASTRO_DIR / "building_crops"
MASKS_DIR = CATASTRO_DIR / "building_crops" / "masks"

app = FastAPI(title="Solar Roof AI", version="0.1.0")


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        return {
            "type": "FeatureCollection",
            "features": [],
            "message": (
                "No hay index.geojson. Ejecuta: "
                "python -m src.data.crop_buildings"
            ),
        }
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _features() -> list[dict]:
    return list(_load_index().get("features") or [])


def _find_building(building_id: str) -> dict | None:
    for feature in _features():
        props = feature.get("properties") or {}
        if props.get("building_id") == building_id:
            return feature
    return None


def _search_features(query: str) -> list[dict]:
    needle = query.strip().upper()
    if not needle:
        return _features()

    matches = []
    for feature in _features():
        props = feature.get("properties") or {}
        haystack = " ".join(
            str(props.get(key) or "")
            for key in (
                "reference",
                "localId",
                "building_id",
                "currentUse",
                "municipality",
                "province",
            )
        ).upper()
        if needle in haystack:
            matches.append(feature)
    return matches


def _stretch_rgb(rgb: np.ndarray) -> np.ndarray:
    rgb = rgb.astype("float32")
    for channel in range(rgb.shape[2]):
        band = rgb[:, :, channel]
        valid = band[band > 0]
        if valid.size == 0:
            continue
        low, high = np.percentile(valid, (2, 98))
        if high <= low:
            continue
        scaled = (band - low) / (high - low)
        rgb[:, :, channel] = np.clip(scaled, 0, 1) * 255
    return rgb.astype("uint8")


def _open_crop_rgb(building_id: str):
    feature = _find_building(building_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Building not found")

    props = feature.get("properties") or {}
    crop_name = props.get("crop_tif") or f"{building_id}.tif"
    crop_path = CROPS_DIR / Path(crop_name).name
    if not crop_path.exists():
        raise HTTPException(status_code=404, detail=f"Crop not found: {crop_name}")

    with rasterio.open(crop_path) as source:
        data = source.read()
        if data.shape[0] >= 3:
            rgb = np.stack([data[0], data[1], data[2]], axis=-1)
        else:
            band = data[0]
            rgb = np.stack([band, band, band], axis=-1)
        transform = source.transform
        crs = source.crs
    return feature, _stretch_rgb(rgb), transform, crs


def _geometry_pixel_rings(geometry, transform, crs):
    """Project GeoJSON geometry into pixel coordinate rings for PIL."""
    geom = shape(geometry)
    if crs is not None:
        # Index geometries are stored as CRS84 / WGS84 lon-lat.
        projector = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        geom = shapely_transform(projector.transform, geom)

    rings = []

    def add_ring(coords):
        points = []
        for x, y, *_ in coords:
            col, row = ~transform * (x, y)
            points.append((float(col), float(row)))
        if len(points) >= 3:
            rings.append(points)

    mapped = mapping(geom)
    geom_type = mapped.get("type")
    coords = mapped.get("coordinates")
    if geom_type == "Polygon":
        add_ring(coords[0])
    elif geom_type == "MultiPolygon":
        for polygon in coords:
            add_ring(polygon[0])
    return rings


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _crop_preview_png(building_id: str) -> bytes:
    _, rgb, _, _ = _open_crop_rgb(building_id)
    return _png_bytes(Image.fromarray(rgb, mode="RGB"))


def _crop_catastro_preview_png(building_id: str) -> bytes:
    feature, rgb, transform, crs = _open_crop_rgb(building_id)
    image = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    geometry = feature.get("geometry")
    if geometry:
        for ring in _geometry_pixel_rings(geometry, transform, crs):
            draw.polygon(ring, outline=(61, 139, 253, 255), fill=(61, 139, 253, 70))
            draw.line(ring + [ring[0]], fill=(255, 180, 84, 255), width=3)

    composed = Image.alpha_composite(image, overlay).convert("RGB")
    return _png_bytes(composed)


@app.get("/api/health")
def health():
    features = _features()
    return {
        "status": "ok",
        "buildings": len(features),
        "index_exists": INDEX_PATH.exists(),
        "index_path": str(INDEX_PATH),
    }


@app.get("/api/meta")
def meta():
    config = load_pilot_area() or {}
    pilot = config.get("pilot_area") or {}
    bbox = config.get("bbox") or {}
    return {
        "app": "Solar Roof AI",
        "pilot_area": pilot,
        "bbox": bbox,
        "buildings": len(_features()),
    }


@app.get("/api/buildings")
def list_buildings(
    q: str | None = Query(default=None, description="Search reference / id / use"),
    limit: int = Query(default=5000, ge=1, le=20000),
):
    features = _search_features(q) if q else _features()
    return {
        "type": "FeatureCollection",
        "features": features[:limit],
        "count": len(features),
        "returned": min(len(features), limit),
    }


@app.get("/api/buildings/{building_id}")
def get_building(building_id: str):
    feature = _find_building(building_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Building not found")
    return feature


@app.get("/api/buildings/{building_id}/crop.png")
def get_building_crop(building_id: str):
    png = _crop_preview_png(building_id)
    return Response(content=png, media_type="image/png")


@app.get("/api/buildings/{building_id}/crop-catastro.png")
def get_building_crop_catastro(building_id: str):
    png = _crop_catastro_preview_png(building_id)
    return Response(content=png, media_type="image/png")


@app.get("/api/buildings/{building_id}/crop-hires/status")
def get_building_hires_status(building_id: str):
    feature = _find_building(building_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Building not found")
    if not hires_exists(building_id):
        return {"building_id": building_id, "cached": False}
    path = hires_tif_path(building_id)
    with rasterio.open(path) as source:
        return {
            "building_id": building_id,
            "cached": True,
            "width": source.width,
            "height": source.height,
            "path": str(path),
        }


@app.post("/api/buildings/{building_id}/crop-hires")
def fetch_building_hires(
    building_id: str,
    force: bool = Query(default=False),
    max_side: int = Query(default=2048, ge=256, le=4096),
):
    """Download hi-res PNOA for this building only (cached on disk)."""
    feature = _find_building(building_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Building not found")
    geometry = feature.get("geometry")
    if not geometry:
        raise HTTPException(status_code=400, detail="Building has no geometry")
    try:
        info = ensure_hires_crop(
            building_id,
            geometry,
            force=force,
            max_side=max_side,
        )
    except Exception as exc:  # noqa: BLE001 — surface WMS/IO errors to UI
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return info


def _stretch_rgb_array(rgb: np.ndarray) -> np.ndarray:
    return _stretch_rgb(rgb)


def _hires_preview_png(building_id: str) -> bytes:
    rgb, _, _ = open_hires_rgb(building_id)
    return _png_bytes(Image.fromarray(_stretch_rgb_array(rgb), mode="RGB"))


def _hires_catastro_preview_png(building_id: str) -> bytes:
    feature = _find_building(building_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Building not found")
    rgb, transform, crs = open_hires_rgb(building_id)
    image = Image.fromarray(_stretch_rgb_array(rgb), mode="RGB").convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    geometry = feature.get("geometry")
    if geometry:
        for ring in _geometry_pixel_rings(geometry, transform, crs):
            draw.polygon(ring, outline=(61, 139, 253, 255), fill=(61, 139, 253, 70))
            draw.line(ring + [ring[0]], fill=(255, 180, 84, 255), width=3)
    composed = Image.alpha_composite(image, overlay).convert("RGB")
    return _png_bytes(composed)


@app.get("/api/buildings/{building_id}/crop-hires.png")
def get_building_crop_hires(building_id: str):
    if not hires_exists(building_id):
        raise HTTPException(
            status_code=404,
            detail="Hi-res crop not cached. POST /crop-hires first.",
        )
    return Response(content=_hires_preview_png(building_id), media_type="image/png")


@app.get("/api/buildings/{building_id}/crop-hires-catastro.png")
def get_building_crop_hires_catastro(building_id: str):
    if not hires_exists(building_id):
        raise HTTPException(
            status_code=404,
            detail="Hi-res crop not cached. POST /crop-hires first.",
        )
    return Response(
        content=_hires_catastro_preview_png(building_id), media_type="image/png"
    )


def _mask_path(building_id: str, source: str) -> Path:
    suffix = "hires" if source == "hires" else "local"
    return MASKS_DIR / f"{building_id}_{suffix}.png"


def _regions_path(building_id: str, source: str) -> Path:
    suffix = "hires" if source == "hires" else "local"
    return MASKS_DIR / f"{building_id}_{suffix}_regions.png"


def _load_saved_classes(building_id: str, source: str, shape_hw: tuple[int, int]):
    path = _mask_path(building_id, source)
    if not path.exists():
        return None
    try:
        loaded = decode_mask_png(path.read_bytes())
    except ValueError:
        return None
    if loaded.shape[:2] != shape_hw:
        return None
    return loaded


def _load_saved_labels(building_id: str, source: str, shape_hw: tuple[int, int]):
    path = _regions_path(building_id, source)
    if not path.exists():
        return None
    try:
        loaded = decode_labels_png(path.read_bytes())
    except ValueError:
        return None
    if loaded.shape[:2] != shape_hw:
        return None
    return loaded


def _load_rgb_for_mask(building_id: str, source: str):
    feature = _find_building(building_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Building not found")
    if source == "hires":
        if not hires_exists(building_id):
            raise HTTPException(
                status_code=404,
                detail="Hi-res not cached. Pulsa Cargar hi-res primero.",
            )
        rgb, transform, crs = open_hires_rgb(building_id)
        return feature, _stretch_rgb(rgb), transform, crs
    return _open_crop_rgb(building_id)


def _overlay_png_from_classes(classes: np.ndarray) -> bytes:
    h, w = classes.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[classes == MaskClass.ROOF] = (40, 200, 80, 120)
    rgba[classes == MaskClass.SHADOW] = (30, 40, 90, 150)
    rgba[classes == MaskClass.POOL] = (40, 160, 220, 140)
    rgba[classes == MaskClass.EXCLUDE] = (180, 60, 200, 130)
    return _png_bytes(Image.fromarray(rgba, mode="RGBA"))


@app.get("/api/mask/algorithms")
def list_mask_algorithms():
    return {
        "algorithms": list(ALGORITHMS),
        "labels": {
            "seed_catastro": "Seed Catastro",
            "dilate": "Dilatar",
            "erode": "Erosionar",
            "buffer_color": "Buffer + color",
            "region_grow": "Region growing",
            "grabcut": "GrabCut",
            "remove_shadows": "Quitar sombras",
            "remove_water": "Quitar piscinas",
            "remove_nonroof": "Quitar no-cubierta",
        },
    }


@app.get("/api/buildings/{building_id}/mask.png")
def get_mask(
    building_id: str,
    source: str = Query(default="local", pattern="^(local|hires)$"),
):
    path = _mask_path(building_id, source)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No mask saved yet")
    return Response(content=path.read_bytes(), media_type="image/png")


@app.get("/api/buildings/{building_id}/mask-overlay.png")
def get_mask_overlay(
    building_id: str,
    source: str = Query(default="local", pattern="^(local|hires)$"),
):
    path = _mask_path(building_id, source)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No mask saved yet")
    classes = decode_mask_png(path.read_bytes())
    return Response(content=_overlay_png_from_classes(classes), media_type="image/png")


@app.put("/api/buildings/{building_id}/mask.png")
async def put_mask(
    building_id: str,
    request: Request,
    source: str = Query(default="local", pattern="^(local|hires)$"),
):
    if _find_building(building_id) is None:
        raise HTTPException(status_code=404, detail="Building not found")
    content = await request.body()
    try:
        classes = decode_mask_png(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    MASKS_DIR.mkdir(parents=True, exist_ok=True)
    path = _mask_path(building_id, source)
    path.write_bytes(encode_mask_png(classes))
    return {
        "building_id": building_id,
        "source": source,
        "path": str(path),
        "roof_pixels": int((classes == MaskClass.ROOF).sum()),
    }


@app.post("/api/buildings/{building_id}/mask/regions")
def detect_building_regions(
    building_id: str,
    source: str = Query(default="local", pattern="^(local|hires)$"),
    mode: str = Query(default="auto", pattern="^(auto|catastro|mask)$"),
):
    """Detect selectable regions (Catastro parts or mask components)."""
    feature, rgb, transform, crs = _load_rgb_for_mask(building_id, source)
    geometry = feature.get("geometry")
    classes = _load_saved_classes(building_id, source, rgb.shape[:2])
    try:
        labels = detect_regions(
            geometry,
            transform,
            crs,
            rgb.shape[0],
            rgb.shape[1],
            classes=classes,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    MASKS_DIR.mkdir(parents=True, exist_ok=True)
    path = _regions_path(building_id, source)
    path.write_bytes(encode_labels_png(labels))
    summaries = region_summaries(labels)
    return {
        "building_id": building_id,
        "source": source,
        "mode": mode,
        "count": len(summaries),
        "regions": summaries,
        "path": str(path),
    }


@app.get("/api/buildings/{building_id}/mask/regions")
def get_building_regions(
    building_id: str,
    source: str = Query(default="local", pattern="^(local|hires)$"),
):
    _feature, rgb, _transform, _crs = _load_rgb_for_mask(building_id, source)
    labels = _load_saved_labels(building_id, source, rgb.shape[:2])
    if labels is None:
        raise HTTPException(status_code=404, detail="No regions detected yet")
    summaries = region_summaries(labels)
    return {
        "building_id": building_id,
        "source": source,
        "count": len(summaries),
        "regions": summaries,
    }


@app.get("/api/buildings/{building_id}/mask/regions-overlay.png")
def get_regions_overlay(
    building_id: str,
    source: str = Query(default="local", pattern="^(local|hires)$"),
    selected: int | None = Query(default=None),
):
    _feature, rgb, _transform, _crs = _load_rgb_for_mask(building_id, source)
    labels = _load_saved_labels(building_id, source, rgb.shape[:2])
    if labels is None:
        raise HTTPException(status_code=404, detail="No regions detected yet")
    rgba = regions_overlay_rgba(labels, selected_id=selected)
    return Response(
        content=_png_bytes(Image.fromarray(rgba, mode="RGBA")),
        media_type="image/png",
    )


@app.get("/api/buildings/{building_id}/mask/region-at")
def region_at_pixel(
    building_id: str,
    x: int = Query(..., ge=0),
    y: int = Query(..., ge=0),
    source: str = Query(default="local", pattern="^(local|hires)$"),
):
    _feature, rgb, _transform, _crs = _load_rgb_for_mask(building_id, source)
    labels = _load_saved_labels(building_id, source, rgb.shape[:2])
    if labels is None:
        raise HTTPException(status_code=404, detail="No regions detected yet")
    height, width = labels.shape
    if x >= width or y >= height:
        raise HTTPException(status_code=400, detail="Pixel out of bounds")
    return {"x": x, "y": y, "region_id": int(labels[y, x])}


@app.post("/api/buildings/{building_id}/mask/run")
def run_mask_algorithm(
    building_id: str,
    algo: str = Query(..., description="Algorithm name"),
    source: str = Query(default="local", pattern="^(local|hires)$"),
    region_id: int | None = Query(default=None, ge=1),
    pixels: int | None = Query(default=None),
    expand_px: int | None = Query(default=None),
    color_tol: float | None = Query(default=None),
):
    if algo not in ALGORITHMS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown algo. Choose one of: {', '.join(ALGORITHMS)}",
        )
    feature, rgb, transform, crs = _load_rgb_for_mask(building_id, source)
    geometry = feature.get("geometry")
    path = _mask_path(building_id, source)
    classes = _load_saved_classes(building_id, source, rgb.shape[:2])

    params = {}
    if pixels is not None:
        params["pixels"] = pixels
    if expand_px is not None:
        params["expand_px"] = expand_px
    if color_tol is not None:
        params["color_tol"] = color_tol

    try:
        if region_id is not None:
            labels = _load_saved_labels(building_id, source, rgb.shape[:2])
            if labels is None:
                raise HTTPException(
                    status_code=400,
                    detail="Detecta regiones antes de aplicar la herramienta a una sola",
                )
            result = run_algorithm_on_region(
                algo,
                rgb,
                classes,
                geometry,
                transform,
                crs,
                labels,
                region_id,
                params=params,
            )
        else:
            result = run_algorithm(
                algo,
                rgb,
                classes,
                geometry,
                transform,
                crs,
                params=params,
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    MASKS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_mask_png(result))
    return {
        "building_id": building_id,
        "algo": algo,
        "source": source,
        "region_id": region_id,
        "width": int(result.shape[1]),
        "height": int(result.shape[0]),
        "roof_pixels": int((result == MaskClass.ROOF).sum()),
        "shadow_pixels": int((result == MaskClass.SHADOW).sum()),
        "pool_pixels": int((result == MaskClass.POOL).sum()),
        "exclude_pixels": int((result == MaskClass.EXCLUDE).sum()),
        "path": str(path),
    }


@app.get("/", response_class=HTMLResponse)
def home():
    index_html = WEB_DIR / "index.html"
    if not index_html.exists():
        raise HTTPException(status_code=404, detail="web/index.html missing")
    return HTMLResponse(index_html.read_text(encoding="utf-8"))


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
