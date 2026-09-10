# Pipeline de datos e IA

Este documento describe el pipeline actual de **Solar Roof AI**: desde la descarga de ortofotos y Catastro hasta la generación del dataset YOLO.

Zona piloto por defecto: **Boadilla del Monte (Madrid)**, definida en `configs/pilot_area.yaml`.

---

## Visión general

```text
configs/pilot_area.yaml
        |
        v
[1] download_pnoa          --> data/raw/pnoa/tiles/
[2] download_catastro      --> data/raw/catastro/tiles/ + buildings.*
[3] crop_buildings         --> data/raw/catastro/building_crops/
[4] prepare_yolo_dataset   --> data/processed/yolo/train/{images,labels} + data.yml

```

Cada paso **borra su carpeta de salida** al empezar (`src/common/fs.py`), para no mezclar resultados antiguos con nuevos.

Las labels YOLO se generan a partir del **polígono catastral** del edificio (no hay paso SAM de momento).

---

## Requisitos previos

1. Entorno virtual activado (`.venv`).
2. Dependencias instaladas (`pip install -r requirements.txt`).
3. Configuración de zona en `configs/pilot_area.yaml`.
4. Ejecutar siempre desde la raíz del repositorio:

```powershell
cd C:\Users\ricardo.alba\Projects\solar-roof-ai
.\.venv\Scripts\Activate.ps1
```

### Sincronizar con GitHub

```powershell
# Solo bajar y subir commits ya hechos
.\scripts\sync_github.ps1

# Commit de cambios locales + pull + push
.\scripts\sync_github.ps1 -Commit -Message "Describe tu cambio"
```

`wip.txt`, `.env` y credenciales se excluyen del commit automático.

---

## Configuración (`configs/pilot_area.yaml`)

| Sección | Uso |
|---------|-----|
| `pilot_area` | Municipio / provincia (documentación) |
| `bbox` | Área geográfica de descarga (lon/lat WGS84) |
| `pnoa` | Parámetros WMS: `grid`, `size`, `fallback_size` |

Ejemplo:

```yaml
bbox:
  min_lon: -3.93
  min_lat: 40.38
  max_lon: -3.82
  max_lat: 40.45

pnoa:
  grid: 20          # teselas en X e Y (20 => 400 tiles)
  size: 4096        # píxeles por tesela WMS
  fallback_size: 2048

crop:
  mode: rectangle
  margin_meters: 10

yolo:
  offset_meters: 10
```

**Resolución (GSD):** a mayor `grid` (misma `size`), cada tesela cubre menos terreno y la resolución por metro mejora.  
Con `grid: 20` y `size: 4096` en esta bbox ≈ **0,10–0,12 m/px** (recomendado para YOLO).  
Con `grid: 10` ≈ **0,20–0,25 m/px** (crops de tejado suelen quedar demasiado pequeños).

Prioridad de parámetros PNOA: **CLI > YAML > defaults internos**.

---

## Paso 1 — Descargar ortofotos PNOA

**Módulo:** `src/data/download_pnoa.py`  
**Salida:** `data/raw/pnoa/tiles/tile_XXX.tif`

Descarga ortofotos del WMS PNOA Máxima Actualidad (IGN) en una rejilla sobre el bbox.

```powershell
# Usa grid/size del YAML
python -m src.data.download_pnoa

# O fuerza por CLI
python -m src.data.download_pnoa --grid 20 --size 4096
python -m src.data.download_pnoa --grid 20 --size 4096 --fallback-size 2048
```

| Parámetro | Descripción |
|-----------|-------------|
| `--grid` | Número de teselas en X e Y |
| `--size` | Ancho/alto WMS en píxeles |
| `--fallback-size` | Tamaño si el WMS falla con `size` |

Al iniciar **limpia** `data/raw/pnoa/tiles/`.

---

## Paso 2 — Descargar edificios Catastro

**Módulo:** `src/data/download_catastro.py`  
**Salida:**

- `data/raw/catastro/tiles/buildings_N.gml` / `.geojson`
- `data/raw/catastro/buildings.gml`
- `data/raw/catastro/buildings.geojson`

Consulta el WFS INSPIRE de Catastro (`bu:Building`) en teselas de 1 km (EPSG:25830).

```powershell
python -m src.data.download_catastro
```

Al iniciar **limpia** `data/raw/catastro/tiles/` y borra `buildings.gml` / `buildings.geojson` previos.

---

## Paso 3 — Recortar edificios sobre PNOA

**Módulo:** `src/data/crop_buildings.py`  
**Entrada:** teselas PNOA + GeoJSON de Catastro  
**Salida:** `data/raw/catastro/building_crops/building_XXXXXX.tif` + `.geojson`

Genera un GeoTIFF (y geometría) por edificio.

```powershell
# Recomendado para YOLO (contexto alrededor del edificio)
python -m src.data.crop_buildings --crop-mode rectangle --margin-meters 10

# Solo silueta del edificio (menos contexto, crops más pequeños)
python -m src.data.crop_buildings --crop-mode shape --margin-meters 2
```

| Parámetro | Descripción |
|-----------|-------------|
| `--crop-mode` | `rectangle` (con margen) o `shape` (máscara del polígono) |
| `--margin-meters` | Buffer métrico alrededor del edificio |
| `--buildings-dir` | Carpeta de GeoJSON Catastro (default: `data/raw/catastro/tiles`) |
| `--tiles-dir` | Carpeta de teselas PNOA |
| `--output-dir` | Carpeta de crops |

Al iniciar **limpia** la carpeta de salida.

> **Nota:** la resolución del crop depende de la GSD de las teselas PNOA. Si los crops son demasiado pequeños para YOLO, aumenta `pnoa.grid` y vuelve a ejecutar desde el paso 1.

---

## Paso 4 — Preparar dataset YOLO

**Módulo:** `src/data/prepare_yolo_dataset.py`  
**Entrada:** crops + GeoJSON catastral por edificio  
**Salida:**

```text
data/processed/yolo/
  data.yml
  train/
    images/building_XXXXXX.tif
    labels/building_XXXXXX.txt   # segmentación, clase 0 = roof
```

Crea el split `train` (imágenes + labels) y genera `data.yml` listo para Ultralytics YOLO-seg.  
Las labels usan el **polígono Catastro**. Por ahora `val` apunta al mismo `train/images` (hasta tener split de validación).

```powershell
python -m src.data.prepare_yolo_dataset --offset-meters 10
```

Entrenamiento típico:

```powershell
yolo segment train data=data/processed/yolo/data.yml model=yolo11n-seg.pt
```

| Parámetro | Descripción |
|-----------|-------------|
| `--offset-meters` | Contexto alrededor del edificio en el sample cuadrado |
| `--images-dir` | Crops (default `building_crops`) |
| `--output-dir` | Dataset YOLO |

Al iniciar **limpia** `data/processed/yolo/`.

Este paso **no aumenta la resolución real** de la imagen: solo recorta. Si el GSD de PNOA es bajo, el dataset seguirá siendo insuficiente para YOLO.

---

## Ejecución completa (orden recomendado)

```powershell
# 1. Ortofotos (ajusta grid/size en YAML o CLI)
python -m src.data.download_pnoa --grid 20 --size 4096

# 2. Catastro
python -m src.data.download_catastro

# 3. Crops
python -m src.data.crop_buildings --crop-mode rectangle --margin-meters 10

# 4. Dataset YOLO
python -m src.data.prepare_yolo_dataset --offset-meters 10
```

---

## Estructura de carpetas generada

```text
data/
  raw/
    pnoa/
      tiles/                 # GeoTIFF WMS
    catastro/
      tiles/                 # edificios por tesela 1 km
      buildings.gml
      buildings.geojson
      building_crops/        # un crop por edificio
  processed/
    yolo/
      data.yml
      train/
        images/
        labels/
```

---

## Módulos de soporte

| Módulo | Rol |
|--------|-----|
| `src/common/config.py` | Rutas, bbox, settings PNOA desde YAML |
| `src/common/fs.py` | `clear_directory()` al inicio de cada paso |
| `src/common/constants.py` | CRS, clase `roof`, hipótesis solares |
| `src/common/logger.py` | Logging a consola y fichero |
| `src/common/check_gpu.py` | Comprobar CUDA / PyTorch |

---

## Fuera de este pipeline (aún no implementado)

Según el roadmap del proyecto, quedan pendientes:

- Entrenamiento YOLO11-seg real sobre el dataset generado
- Segmentación refinada (p. ej. SAM) si se retoma más adelante
- Integración espacial Catastro ↔ tejado detectado
- LiDAR (pendiente, orientación)
- Sombras
- PVGIS / potencial fotovoltaico
- PostGIS + FastAPI + visor Leaflet

---

## Solución de problemas

| Problema | Qué revisar |
|----------|-------------|
| Crops muy pequeños / YOLO no aprende | Sube `pnoa.grid` (p. ej. 20+), redescarga PNOA y repite crops → YOLO |
| `torch==...+cu128` no instala | Usa el índice CUDA de PyTorch (ver README / notas de instalación) |
| WMS falla en algunas teselas | El script reintenta y usa `fallback_size` |
| Carpeta con datos viejos | Cada paso limpia su salida; no hace falta borrar a mano |
| Rutas absolutas antiguas | El proyecto usa rutas relativas desde la raíz del repo |

---

## Resumen

El pipeline actual construye un **dataset de segmentación de tejados** a partir de PNOA + Catastro. Las máscaras YOLO usan el polígono catastral. La calidad para YOLO depende sobre todo de la **resolución de descarga PNOA** (`grid` / `size` en `configs/pilot_area.yaml` o CLI).
