from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"

RAW_DIR = DATA_DIR / "raw"

PNOA_DIR = RAW_DIR / "pnoa"
CATASTRO_DIR = RAW_DIR / "catastro"
LIDAR_DIR = RAW_DIR / "lidar"
BUILDINGS_DIR = RAW_DIR / "buildings"

OUTPUTS_DIR = PROJECT_ROOT / "outputs"