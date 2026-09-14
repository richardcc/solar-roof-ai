"""Roof mask algorithms for the workbench (Catastro + orthophoto)."""

from __future__ import annotations

from enum import IntEnum

import cv2
import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform


class MaskClass(IntEnum):
    EMPTY = 0
    ROOF = 1
    SHADOW = 2
    POOL = 3
    EXCLUDE = 4


ALGORITHMS = (
    "seed_catastro",
    "dilate",
    "erode",
    "buffer_color",
    "region_grow",
    "grabcut",
    "remove_shadows",
    "remove_water",
    "remove_nonroof",
)


def _geometry_in_raster_crs(geometry: dict, crs):
    geom = shape(geometry)
    if crs is None:
        return geom
    projector = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return shapely_transform(projector.transform, geom)


def rasterize_catastro(
    geometry: dict,
    transform,
    crs,
    height: int,
    width: int,
) -> np.ndarray:
    """Binary roof seed from Catastro polygon (1 = roof)."""
    geom = _geometry_in_raster_crs(geometry, crs)
    return rasterize(
        [(geom, 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    )


def class_mask_from_binary(roof: np.ndarray) -> np.ndarray:
    out = np.zeros(roof.shape, dtype=np.uint8)
    out[roof.astype(bool)] = MaskClass.ROOF
    return out


def binary_roof(classes: np.ndarray) -> np.ndarray:
    return (classes == MaskClass.ROOF).astype(np.uint8)


def dilate_roof(classes: np.ndarray, pixels: int = 8) -> np.ndarray:
    roof = binary_roof(classes)
    k = max(1, pixels * 2 + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    grown = cv2.dilate(roof, kernel, iterations=1)
    out = classes.copy()
    add = (grown > 0) & (out == MaskClass.EMPTY)
    out[add] = MaskClass.ROOF
    return out


def erode_roof(classes: np.ndarray, pixels: int = 4) -> np.ndarray:
    roof = binary_roof(classes)
    k = max(1, pixels * 2 + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    shrunk = cv2.erode(roof, kernel, iterations=1)
    out = classes.copy()
    lost = (roof > 0) & (shrunk == 0)
    out[lost] = MaskClass.EMPTY
    return out


def buffer_color(
    rgb: np.ndarray,
    classes: np.ndarray,
    expand_px: int = 12,
    color_tol: float = 42.0,
) -> np.ndarray:
    """Expand seed then keep only pixels similar to mean roof color."""
    roof = binary_roof(classes)
    if roof.sum() == 0:
        return classes

    mean = rgb[roof.astype(bool)].astype(np.float32).mean(axis=0)
    k = expand_px * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    band = cv2.dilate(roof, kernel, iterations=1).astype(bool)
    dist = np.linalg.norm(rgb.astype(np.float32) - mean, axis=2)
    keep = band & (dist <= color_tol)

    out = classes.copy()
    clear = band & (out == MaskClass.ROOF)
    out[clear] = MaskClass.EMPTY
    out[keep & (out == MaskClass.EMPTY)] = MaskClass.ROOF
    out[roof.astype(bool)] = MaskClass.ROOF
    return out


def region_grow(
    rgb: np.ndarray,
    classes: np.ndarray,
    color_tol: float = 28.0,
    max_expand_px: int = 24,
) -> np.ndarray:
    """Grow roof from seed while neighbors stay color-similar."""
    roof = binary_roof(classes)
    if roof.sum() == 0:
        return classes

    seed_mean = rgb[roof.astype(bool)].astype(np.float32).mean(axis=0)
    current = roof.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    for _ in range(max_expand_px):
        ring = cv2.dilate(current, kernel, iterations=1)
        candidates = (ring > 0) & (current == 0) & (classes != MaskClass.EXCLUDE)
        if not candidates.any():
            break
        dist = np.linalg.norm(rgb.astype(np.float32) - seed_mean, axis=2)
        accept = candidates & (dist <= color_tol)
        if not accept.any():
            break
        current[accept] = 1

    out = classes.copy()
    out[current.astype(bool) & (out == MaskClass.EMPTY)] = MaskClass.ROOF
    out[roof.astype(bool)] = MaskClass.ROOF
    return out


def grabcut_roof(
    rgb: np.ndarray,
    classes: np.ndarray,
    pad_px: int = 18,
) -> np.ndarray:
    """OpenCV GrabCut around the Catastro/roof seed."""
    roof = binary_roof(classes)
    if roof.sum() < 16:
        return classes

    h, w = roof.shape
    k = pad_px * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    probable = cv2.dilate(roof, kernel, iterations=1)

    gc = np.full((h, w), cv2.GC_BGD, dtype=np.uint8)
    gc[probable.astype(bool)] = cv2.GC_PR_FGD
    gc[roof.astype(bool)] = cv2.GC_FGD

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, gc, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)

    result = np.where(
        (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD),
        1,
        0,
    ).astype(np.uint8)

    out = classes.copy()
    band = probable.astype(bool)
    out[band & (out == MaskClass.ROOF)] = MaskClass.EMPTY
    out[band & (result > 0) & (out == MaskClass.EMPTY)] = MaskClass.ROOF
    return out


def remove_shadows(rgb: np.ndarray, classes: np.ndarray, luma_max: float = 70.0) -> np.ndarray:
    roof = binary_roof(classes)
    luma = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    dark = roof.astype(bool) & (luma <= luma_max)
    out = classes.copy()
    out[dark] = MaskClass.SHADOW
    return out


def remove_water(rgb: np.ndarray, classes: np.ndarray) -> np.ndarray:
    roof = binary_roof(classes)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    near = cv2.dilate(roof, kernel, iterations=1).astype(bool)
    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)
    blueish = (b > r + 15) & (b > g + 5) & (b > 70)
    water = near & blueish
    out = classes.copy()
    out[water] = MaskClass.POOL
    return out


def remove_nonroof(rgb: np.ndarray, classes: np.ndarray, color_tol: float = 55.0) -> np.ndarray:
    roof = binary_roof(classes)
    if roof.sum() == 0:
        return classes
    mean = rgb[roof.astype(bool)].astype(np.float32).mean(axis=0)
    dist = np.linalg.norm(rgb.astype(np.float32) - mean, axis=2)
    drop = roof.astype(bool) & (dist > color_tol)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    green = (g.astype(np.int16) > r.astype(np.int16) + 12) & (
        g.astype(np.int16) > b.astype(np.int16) + 12
    )
    out = classes.copy()
    out[drop & green] = MaskClass.EXCLUDE
    out[drop & ~green] = MaskClass.EMPTY
    return out


def run_algorithm(
    name: str,
    rgb: np.ndarray,
    classes: np.ndarray | None,
    geometry: dict | None,
    transform,
    crs,
    params: dict | None = None,
) -> np.ndarray:
    params = params or {}
    h, w = rgb.shape[:2]

    if classes is None:
        classes = np.zeros((h, w), dtype=np.uint8)

    if name == "seed_catastro":
        if not geometry:
            raise ValueError("seed_catastro requires geometry")
        return class_mask_from_binary(
            rasterize_catastro(geometry, transform, crs, h, w)
        )

    if binary_roof(classes).sum() == 0:
        if not geometry:
            raise ValueError("No roof seed and no Catastro geometry")
        classes = class_mask_from_binary(
            rasterize_catastro(geometry, transform, crs, h, w)
        )

    if name == "dilate":
        return dilate_roof(classes, pixels=int(params.get("pixels", 8)))
    if name == "erode":
        return erode_roof(classes, pixels=int(params.get("pixels", 4)))
    if name == "buffer_color":
        return buffer_color(
            rgb,
            classes,
            expand_px=int(params.get("expand_px", 12)),
            color_tol=float(params.get("color_tol", 42.0)),
        )
    if name == "region_grow":
        return region_grow(
            rgb,
            classes,
            color_tol=float(params.get("color_tol", 28.0)),
            max_expand_px=int(params.get("max_expand_px", 24)),
        )
    if name == "grabcut":
        return grabcut_roof(rgb, classes, pad_px=int(params.get("pad_px", 18)))
    if name == "remove_shadows":
        return remove_shadows(rgb, classes, luma_max=float(params.get("luma_max", 70.0)))
    if name == "remove_water":
        return remove_water(rgb, classes)
    if name == "remove_nonroof":
        return remove_nonroof(rgb, classes, color_tol=float(params.get("color_tol", 55.0)))

    raise ValueError(f"Unknown algorithm: {name}")


def encode_mask_png(classes: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", classes.astype(np.uint8))
    if not ok:
        raise RuntimeError("Failed to encode mask PNG")
    return buf.tobytes()


def decode_mask_png(content: bytes) -> np.ndarray:
    arr = np.frombuffer(content, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Invalid mask PNG")
    if img.ndim == 3:
        img = img[:, :, 0]
    return img.astype(np.uint8)


def encode_labels_png(labels: np.ndarray) -> bytes:
    """Store region labels as 16-bit PNG."""
    ok, buf = cv2.imencode(".png", labels.astype(np.uint16))
    if not ok:
        raise RuntimeError("Failed to encode region labels PNG")
    return buf.tobytes()


def decode_labels_png(content: bytes) -> np.ndarray:
    arr = np.frombuffer(content, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Invalid region labels PNG")
    if img.ndim == 3:
        img = img[:, :, 0]
    return img.astype(np.int32)


REGION_COLORS = [
    (255, 140, 40),
    (60, 160, 255),
    (80, 220, 120),
    (240, 80, 160),
    (250, 220, 60),
    (160, 100, 255),
    (40, 210, 210),
    (255, 100, 80),
]


def rasterize_catastro_regions(
    geometry: dict,
    transform,
    crs,
    height: int,
    width: int,
) -> np.ndarray:
    """Label each Catastro polygon part with a distinct id (1..N)."""
    geom = _geometry_in_raster_crs(geometry, crs)
    if geom.is_empty:
        return np.zeros((height, width), dtype=np.int32)

    if geom.geom_type == "Polygon":
        parts = [geom]
    elif geom.geom_type == "MultiPolygon":
        parts = list(geom.geoms)
    else:
        parts = [g for g in getattr(geom, "geoms", [geom]) if not g.is_empty]

    labels = np.zeros((height, width), dtype=np.int32)
    for index, part in enumerate(parts, start=1):
        if part.is_empty:
            continue
        mask = rasterize(
            [(part, 1)],
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        )
        labels[mask > 0] = index
    return labels


def labels_from_connected_components(binary: np.ndarray, min_area: int = 40) -> np.ndarray:
    """Connected components of a binary mask → labels 1..N (largest first)."""
    binary_u8 = (binary.astype(bool)).astype(np.uint8)
    count, raw, stats, _ = cv2.connectedComponentsWithStats(binary_u8, connectivity=8)
    # stats: [label, x, y, w, h, area] — label 0 is background
    regions = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        regions.append((area, label))
    regions.sort(reverse=True)

    out = np.zeros(binary.shape, dtype=np.int32)
    for new_id, (_, old_label) in enumerate(regions, start=1):
        out[raw == old_label] = new_id
    return out


def detect_regions(
    geometry: dict | None,
    transform,
    crs,
    height: int,
    width: int,
    classes: np.ndarray | None = None,
    mode: str = "auto",
) -> np.ndarray:
    """
    Detect selectable regions.

    mode:
      - catastro: one label per Catastro polygon part
      - mask: connected components of current roof mask
      - auto: catastro if multiparts / else mask if present / else catastro
    """
    catastro_labels = None
    if geometry is not None:
        catastro_labels = rasterize_catastro_regions(geometry, transform, crs, height, width)

    mask_labels = None
    if classes is not None and binary_roof(classes).sum() > 0:
        mask_labels = labels_from_connected_components(binary_roof(classes))

    if mode == "catastro":
        if catastro_labels is None or catastro_labels.max() == 0:
            raise ValueError("No Catastro geometry to split into regions")
        return catastro_labels
    if mode == "mask":
        if mask_labels is None or mask_labels.max() == 0:
            raise ValueError("No roof mask to split into regions")
        return mask_labels

    # auto
    if catastro_labels is not None and catastro_labels.max() >= 2:
        return catastro_labels
    if mask_labels is not None and mask_labels.max() >= 1:
        return mask_labels
    if catastro_labels is not None and catastro_labels.max() >= 1:
        return catastro_labels
    raise ValueError("Could not detect regions (need Catastro or roof mask)")


def region_summaries(labels: np.ndarray) -> list[dict]:
    """JSON-friendly list of regions sorted by id."""
    summaries = []
    max_id = int(labels.max()) if labels.size else 0
    for region_id in range(1, max_id + 1):
        ys, xs = np.where(labels == region_id)
        if len(xs) == 0:
            continue
        color = REGION_COLORS[(region_id - 1) % len(REGION_COLORS)]
        summaries.append(
            {
                "id": region_id,
                "pixels": int(len(xs)),
                "centroid": [float(xs.mean()), float(ys.mean())],
                "bbox": [
                    int(xs.min()),
                    int(ys.min()),
                    int(xs.max()),
                    int(ys.max()),
                ],
                "color": list(color),
            }
        )
    return summaries


def regions_overlay_rgba(labels: np.ndarray, selected_id: int | None = None) -> np.ndarray:
    """Colored translucent overlay; selected region is stronger + outline."""
    h, w = labels.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    max_id = int(labels.max()) if labels.size else 0
    for region_id in range(1, max_id + 1):
        mask = labels == region_id
        if not mask.any():
            continue
        r, g, b = REGION_COLORS[(region_id - 1) % len(REGION_COLORS)]
        alpha = 160 if selected_id == region_id else 90
        rgba[mask] = (r, g, b, alpha)

    if selected_id and selected_id > 0:
        selected = (labels == selected_id).astype(np.uint8)
        if selected.any():
            contours, _ = cv2.findContours(
                selected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            # Draw on a temp BGR then copy outline into RGBA.
            outline = np.zeros((h, w), dtype=np.uint8)
            cv2.drawContours(outline, contours, -1, 255, 2)
            rgba[outline > 0] = (255, 255, 255, 220)
    return rgba


def run_algorithm_on_region(
    name: str,
    rgb: np.ndarray,
    classes: np.ndarray | None,
    geometry: dict | None,
    transform,
    crs,
    labels: np.ndarray,
    region_id: int,
    params: dict | None = None,
) -> np.ndarray:
    """
    Run an algorithm affecting only the selected region.
    Other regions are preserved.
    """
    params = params or {}
    h, w = rgb.shape[:2]
    if classes is None:
        classes = np.zeros((h, w), dtype=np.uint8)
    if labels.shape != (h, w):
        raise ValueError("Region labels size does not match image")
    if region_id < 1 or not (labels == region_id).any():
        raise ValueError(f"Region {region_id} not found")

    selected = labels == region_id
    other = (labels > 0) & ~selected
    frozen = classes.copy()

    # Working mask: only the selected region keeps roof (and its classes).
    work = classes.copy()
    roof_elsewhere = binary_roof(work).astype(bool) & other
    work[roof_elsewhere] = MaskClass.EMPTY
    # Ensure selected area is seeded as roof for refine algos.
    if name != "seed_catastro" and binary_roof(work).sum() == 0:
        work[selected] = MaskClass.ROOF

    if name == "seed_catastro":
        # Re-seed only this Catastro part.
        if geometry is None:
            raise ValueError("seed_catastro requires geometry")
        full_seed = rasterize_catastro_regions(geometry, transform, crs, h, w)
        part = full_seed == region_id
        if not part.any():
            # Fallback: use current region footprint.
            part = selected
        result = frozen.copy()
        # Clear previous roof in this region, paint seed.
        result[selected & (result == MaskClass.ROOF)] = MaskClass.EMPTY
        result[part] = MaskClass.ROOF
        result[other] = frozen[other]
        return result

    result = run_algorithm(name, rgb, work, geometry, transform, crs, params=params)

    # Influence zone for expand-style tools: selected + dilation band.
    pad = int(params.get("expand_px", params.get("pixels", params.get("pad_px", 18))))
    pad = max(pad, 8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad * 2 + 1, pad * 2 + 1))
    influence = cv2.dilate(selected.astype(np.uint8), kernel, iterations=1).astype(bool)
    # Never overwrite other labeled regions.
    influence &= ~other

    out = frozen.copy()
    if name.startswith("remove_"):
        out[selected] = result[selected]
    else:
        out[influence] = result[influence]
        out[other] = frozen[other]
    return out
