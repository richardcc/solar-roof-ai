from pathlib import Path
import yaml

# -----------------------------------------------------
# Project
# -----------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# -----------------------------------------------------
# Data
# -----------------------------------------------------

DATA_DIR = PROJECT_ROOT / "data"

RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Sources

PNOA_DIR = RAW_DATA_DIR / "pnoa"
CATASTRO_DIR = RAW_DATA_DIR / "catastro"
LIDAR_DIR = RAW_DATA_DIR / "lidar"
PVGIS_DIR = RAW_DATA_DIR / "pvgis"

# Processed data

TRAIN_DIR = PROCESSED_DATA_DIR / "training"
VALIDATION_DIR = PROCESSED_DATA_DIR / "validation"
TEST_DIR = PROCESSED_DATA_DIR / "test"

# Labels

YOLO_LABELS_DIR = DATA_DIR / "labels" / "yolo"
SEGMENTATION_LABELS_DIR = DATA_DIR / "labels" / "segmentation"

# -----------------------------------------------------
# Models
# -----------------------------------------------------

MODELS_DIR = PROJECT_ROOT / "models"

CHECKPOINTS_DIR = MODELS_DIR / "checkpoints"
BEST_MODELS_DIR = MODELS_DIR / "best"
EXPORTED_MODELS_DIR = MODELS_DIR / "exported"

# -----------------------------------------------------
# Outputs
# -----------------------------------------------------

OUTPUTS_DIR = PROJECT_ROOT / "outputs"

MAPS_DIR = OUTPUTS_DIR / "maps"
REPORTS_DIR = OUTPUTS_DIR / "reports"
FIGURES_DIR = OUTPUTS_DIR / "figures"
METRICS_DIR = OUTPUTS_DIR / "metrics"

# -----------------------------------------------------
# Runs & Logs
# -----------------------------------------------------

RUNS_DIR = PROJECT_ROOT / "runs"
LOGS_DIR = PROJECT_ROOT / "logs"

# -----------------------------------------------------
# Configs
# -----------------------------------------------------

CONFIGS_DIR = PROJECT_ROOT / "configs"

# -----------------------------------------------------
# Notebooks
# -----------------------------------------------------

NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"


# -----------------------------------------------------
# Utilities
# -----------------------------------------------------

def ensure_directories() -> None:
    """
    Create all required project directories if they do not exist.
    """

    directories = [
        DATA_DIR,
        RAW_DATA_DIR,
        INTERIM_DATA_DIR,
        PROCESSED_DATA_DIR,
        PNOA_DIR,
        CATASTRO_DIR,
        LIDAR_DIR,
        PVGIS_DIR,
        TRAIN_DIR,
        VALIDATION_DIR,
        TEST_DIR,
        YOLO_LABELS_DIR,
        SEGMENTATION_LABELS_DIR,
        MODELS_DIR,
        CHECKPOINTS_DIR,
        BEST_MODELS_DIR,
        EXPORTED_MODELS_DIR,
        OUTPUTS_DIR,
        MAPS_DIR,
        REPORTS_DIR,
        FIGURES_DIR,
        METRICS_DIR,
        RUNS_DIR,
        LOGS_DIR,
        CONFIGS_DIR,
        NOTEBOOKS_DIR,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_directories()

    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"DATA_DIR: {DATA_DIR}")
    print(f"PNOA_DIR: {PNOA_DIR}")
    print(f"CATASTRO_DIR: {CATASTRO_DIR}")
    print(f"LIDAR_DIR: {LIDAR_DIR}")
    print(f"PVGIS_DIR: {PVGIS_DIR}")

PILOT_AREA_CONFIG = CONFIGS_DIR / "pilot_area.yaml"


def load_pilot_area() -> dict:
    """
    Load pilot area configuration.
    """

    with open(PILOT_AREA_CONFIG, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def get_bbox() -> dict:
    """
    Return configured bounding box.
    """

    config = load_pilot_area()

    return config["bbox"]


def get_bbox_tuple() -> tuple:
    """
    Return bbox as tuple.

    Returns:
        (min_x, min_y, max_x, max_y)
    """

    bbox = get_bbox()

    # Support either "min_x/min_y/max_x/max_y" or "min_lon/min_lat/max_lon/max_lat"
    min_x = bbox.get("min_x", bbox.get("min_lon"))
    min_y = bbox.get("min_y", bbox.get("min_lat"))
    max_x = bbox.get("max_x", bbox.get("max_lon"))
    max_y = bbox.get("max_y", bbox.get("max_lat"))

    if None in (min_x, min_y, max_x, max_y):
        raise KeyError("Bounding box is missing required keys in pilot_area config")

    return (
        min_x,
        min_y,
        max_x,
        max_y,
    )


def get_bbox_string() -> str:
    """
    Return bbox formatted for web services.
    """

    min_x, min_y, max_x, max_y = get_bbox_tuple()

    return f"{min_x},{min_y},{max_x},{max_y}"


DEFAULT_PNOA_GRID = 20
DEFAULT_PNOA_SIZE = 4096
DEFAULT_PNOA_FALLBACK_SIZE = 2048
DEFAULT_CROP_MODE = "rectangle"
DEFAULT_CROP_MARGIN_METERS = 10.0
DEFAULT_YOLO_OFFSET_METERS = 10.0


def get_pnoa_settings() -> dict:
    """
    Return PNOA download settings from pilot_area.yaml.

    Keys:
        grid (int): number of tiles along X and Y
        size (int): WMS request width/height in pixels
        fallback_size (int): smaller size used after WMS failures
    """

    config = load_pilot_area() or {}
    pnoa = config.get("pnoa") or {}

    grid = int(pnoa.get("grid", DEFAULT_PNOA_GRID))
    size = int(pnoa.get("size", DEFAULT_PNOA_SIZE))
    fallback_size = int(pnoa.get("fallback_size", DEFAULT_PNOA_FALLBACK_SIZE))

    if grid < 1:
        raise ValueError("pnoa.grid must be >= 1")
    if size < 1:
        raise ValueError("pnoa.size must be >= 1")
    if fallback_size < 1:
        raise ValueError("pnoa.fallback_size must be >= 1")

    return {
        "grid": grid,
        "size": size,
        "fallback_size": fallback_size,
    }


def get_crop_settings() -> dict:
    """Return building-crop defaults from pilot_area.yaml."""
    config = load_pilot_area() or {}
    crop = config.get("crop") or {}
    mode = str(crop.get("mode", DEFAULT_CROP_MODE)).lower()
    margin_meters = float(crop.get("margin_meters", DEFAULT_CROP_MARGIN_METERS))
    if mode not in {"rectangle", "shape"}:
        raise ValueError("crop.mode must be 'rectangle' or 'shape'")
    if margin_meters < 0:
        raise ValueError("crop.margin_meters must be non-negative")
    return {
        "mode": mode,
        "margin_meters": margin_meters,
    }


def get_yolo_dataset_settings() -> dict:
    """Return YOLO dataset preparation defaults from pilot_area.yaml."""
    config = load_pilot_area() or {}
    yolo = config.get("yolo") or {}
    offset_meters = float(yolo.get("offset_meters", DEFAULT_YOLO_OFFSET_METERS))
    if offset_meters < 0:
        raise ValueError("yolo.offset_meters must be non-negative")
    return {
        "offset_meters": offset_meters,
    }
