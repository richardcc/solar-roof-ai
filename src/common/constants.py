# -----------------------------------------------------
# Coordinate Reference Systems (CRS)
# -----------------------------------------------------

WGS84 = "EPSG:4326"

# España peninsular
ETRS89_UTM30 = "EPSG:25830"

# -----------------------------------------------------
# Application
# -----------------------------------------------------

APP_NAME = "Solar Roof AI"
APP_VERSION = "0.1.0"

# -----------------------------------------------------
# YOLO
# -----------------------------------------------------

YOLO_MODEL = "yolo11n-seg.pt"

DEFAULT_IMAGE_SIZE = 1024
DEFAULT_BATCH_SIZE = 8
DEFAULT_EPOCHS = 100

DEFAULT_CONFIDENCE_THRESHOLD = 0.25
DEFAULT_IOU_THRESHOLD = 0.50

# -----------------------------------------------------
# Roof Detection
# -----------------------------------------------------

ROOF_CLASS_ID = 0
ROOF_CLASS_NAME = "roof"

# -----------------------------------------------------
# LiDAR (ASPRS Classification Standard)
# -----------------------------------------------------

LIDAR_UNCLASSIFIED = 1
LIDAR_GROUND = 2

LIDAR_LOW_VEGETATION = 3
LIDAR_MEDIUM_VEGETATION = 4
LIDAR_HIGH_VEGETATION = 5

LIDAR_BUILDING = 6

# -----------------------------------------------------
# Solar
# -----------------------------------------------------

PANEL_EFFICIENCY = 0.22

SYSTEM_LOSSES = 0.14

DEFAULT_PANEL_POWER_WP = 450

DEFAULT_PANEL_AREA_M2 = 2.0

USABLE_ROOF_RATIO = 0.80

# -----------------------------------------------------
# PVGIS
# -----------------------------------------------------

DEFAULT_PVGIS_YEAR_START = 2020
DEFAULT_PVGIS_YEAR_END = 2024

# -----------------------------------------------------
# Geometry
# -----------------------------------------------------

MIN_ROOF_AREA_M2 = 10.0

MAX_ROOF_SLOPE_DEGREES = 60.0

# -----------------------------------------------------
# Database
# -----------------------------------------------------

DEFAULT_SCHEMA = "public"

# -----------------------------------------------------
# Debug
# -----------------------------------------------------

if __name__ == "__main__":
    print(APP_NAME)
    print(APP_VERSION)
    print(YOLO_MODEL)
    print(WGS84)