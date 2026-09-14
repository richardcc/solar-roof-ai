# Comandos y scripts

Referencia rápida de **Solar Roof AI**: entorno, datos, UI y GitHub.

Documentos relacionados: [`pipeline.md`](pipeline.md) · [`proyecto.md`](proyecto.md) · [`ui-roadmap.md`](ui-roadmap.md)

---

## 0. Preparación (siempre)

```powershell
cd C:\Users\ricardo.alba\Projects\solar-roof-ai
.\.venv\Scripts\Activate.ps1
```

Si aún no hay venv / dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

Comprobar GPU (opcional):

```powershell
python -m src.common.check_gpu
```

---

## 1. Pipeline de datos

Orden: **Catastro → PNOA → crops** (ver [`pipeline.md`](pipeline.md)).

Filtros de edificios y PNOA: `configs/pilot_area.yaml`.

### 1.1 Catastro

```powershell
python -m src.data.download_catastro
```

Salida: `data/raw/catastro/tiles/`, `buildings.geojson`, `buildings.gml`  
(aplica filtros `catastro.*` del YAML)

### 1.2 PNOA

```powershell
# Usa grid/size/only_buildings del YAML (requiere Catastro previo)
python -m src.data.download_pnoa

# Opciones
python -m src.data.download_pnoa --grid 20 --size 4096
python -m src.data.download_pnoa --no-only-buildings
```

Salida: `data/raw/pnoa/tiles/tile_XXX.tif`

### 1.3 Crops + índice UI

```powershell
python -m src.data.crop_buildings

# Opciones
python -m src.data.crop_buildings --crop-mode rectangle --margin-meters 10
python -m src.data.crop_buildings --crop-mode shape --margin-meters 2
```

Salida:

- `data/raw/catastro/building_crops/building_XXXXXX.tif`
- `data/raw/catastro/building_crops/building_XXXXXX.geojson`
- `data/raw/catastro/building_crops/index.geojson`

### 1.4 Dataset YOLO (opcional)

```powershell
python -m src.data.prepare_yolo_dataset
python -m src.data.prepare_yolo_dataset --offset-meters 10
```

Salida: `data/processed/yolo/train/{images,labels}` + `data.yml`

### 1.5 Secuencia completa

```powershell
python -m src.data.download_catastro
python -m src.data.download_pnoa
python -m src.data.crop_buildings
python -m src.data.prepare_yolo_dataset
```

---

## 2. Interfaz gráfica (API + web)

Requiere `index.geojson` (paso crops).

```powershell
.\scripts\run_api.ps1
```

Equivalente:

```powershell
.\scripts\run_api.bat
# o
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Abrir: [http://127.0.0.1:8000](http://127.0.0.1:8000)

| Endpoint | Uso |
|----------|-----|
| `GET /` | UI Leaflet |
| `GET /api/health` | Estado |
| `GET /api/meta` | Zona piloto / conteo |
| `GET /api/buildings?q=` | Lista / búsqueda |
| `GET /api/buildings/{id}` | Ficha |
| `GET /api/buildings/{id}/crop.png` | Preview del crop |

Más detalle de pantallas: [`ui-roadmap.md`](ui-roadmap.md).

---

## 3. GitHub (sync)

Desde la raíz del repo:

```powershell
# Solo bajar y subir commits ya hechos
.\scripts\sync_github.ps1

# Commit de cambios locales + pull + push
.\scripts\sync_github.ps1 -Commit -Message "Describe tu cambio"
```

También: `.\scripts\sync_github.bat`

Notas:

- Excluye del commit automático: `wip.txt`, `.env`, claves.
- Usa `pull --rebase --autostash` para no fallar con cambios locales menores.
- Rama por defecto: `main`.

Manual equivalente:

```powershell
git status
git add -A
git commit -m "mensaje"
git pull --rebase --autostash origin main
git push origin main
```

---

## 4. Scripts en `scripts/`

| Script | Qué hace |
|--------|----------|
| `sync_github.ps1` / `.bat` | Sincronizar con GitHub |
| `run_api.ps1` / `.bat` | Levantar UI en el puerto 8000 |

---

## 5. Configuración útil (`configs/pilot_area.yaml`)

| Bloque | Ejemplo |
|--------|---------|
| `bbox` | Zona geográfica |
| `catastro` | `only_functional`, `min_area_m2`, `min_dwellings`, `current_use` |
| `pnoa` | `grid`, `size`, `only_buildings` |
| `crop` | `mode`, `margin_meters` |
| `yolo` | `offset_meters` |

Filtro residencial actual (ejemplo):

```yaml
catastro:
  only_functional: true
  min_area_m2: 80
  min_dwellings: 1
  current_use: ["1_residential"]
```

---

## 6. Rutas de datos clave

```text
data/raw/catastro/buildings.geojson
data/raw/catastro/building_crops/index.geojson
data/raw/pnoa/tiles/
data/processed/yolo/data.yml
configs/pilot_area.yaml
```

---

*Mantén este fichero como chuleta operativa; el detalle del flujo está en [`pipeline.md`](pipeline.md).*
