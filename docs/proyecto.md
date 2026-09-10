# Solar Roof AI — Descripción del proyecto

## 1. Qué es

**Solar Roof AI** estima el **potencial fotovoltaico de inmuebles** en España a partir de datos públicos:

- **Catastro** → localiza el edificio (geometría + referencia catastral)
- **PNOA** → ortofoto para delimitar/refinar la cubierta visible
- **LiDAR PNOA** → altura, planos, inclinación y orientación
- **PVGIS** → irradiación y estimación de producción (kWh)

Zona piloto: **Boadilla del Monte (Madrid)** (`configs/pilot_area.yaml`).

---

## 2. Idea central

En España el Catastro cubre prácticamente todos los edificios.  
**No hace falta detectar inmuebles con YOLO.**

El flujo es:

```text
Catastro (edificio conocido)
        │
        ▼
  Delimitar tejado dentro del edificio   ← ortofoto / refinamiento
        │
        ▼
  Limpiar superficie útil                ← vegetación, huecos, obstáculos
        │
        ▼
  Inclinación y orientación              ← LiDAR
        │
        ▼
  Potencial solar                        ← PVGIS + hipótesis de paneles
        │
        ▼
  Almacenar y visualizar                 ← PostGIS + API + mapa web
```

### Rol de YOLO (opcional)

YOLO **no es el motor del sistema**. Podría usarse más adelante solo para:

- refinar la máscara de cubierta dentro del edificio
- detectar obstáculos en tejado (chimeneas, HVAC…)
- control de calidad Catastro ↔ ortofoto
- comparación metodológica en la memoria del TFM

---

## 3. Objetivos

1. Asociar cada análisis a un **inmueble catastral**.
2. Obtener una **geometría de cubierta** (mejor que la huella cruda del edificio).
3. Estimar **superficie útil** instalable.
4. Calcular **pendiente y orientación** con LiDAR.
5. Estimar **pérdidas por sombra** (aproximación).
6. Consultar **irradiación** (PVGIS) y estimar **kWh/año**, ahorro y CO₂.
7. Persistencia en **PostGIS** y consulta en un **visor web**.

---

## 4. Fuentes de datos

| Fuente | Uso |
|--------|-----|
| Catastro INSPIRE WFS (`bu:Building`) | Edificio, referencia, geometría base |
| PNOA WMS (IGN) | Ortofoto para delimitar/refinar cubierta |
| LiDAR PNOA | Alturas, planos de tejado, pendiente, azimuth |
| PVGIS | Series / irradiación para producción |

Configuración de área y descarga PNOA: `configs/pilot_area.yaml`  
(p. ej. `pnoa.grid: 20`, `size: 4096` ≈ 0,10–0,12 m/px en la bbox piloto).

---

## 5. Arquitectura objetivo

```text
┌────────────┐   ┌────────────┐   ┌────────────┐
│  Catastro  │   │    PNOA    │   │ LiDAR PNOA │
└─────┬──────┘   └─────┬──────┘   └─────┬──────┘
      │                │                │
      └──────────┬─────┴────────┬───────┘
                 ▼              ▼
         Building context   Roof mask / planes
                 │              │
                 └──────┬───────┘
                        ▼
              Geospatial analysis
              (área, slope, aspect, shadows)
                        │
                        ▼
                     PVGIS
                        │
                        ▼
                   Solar results
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
           PostGIS            FastAPI + Leaflet
```

Detalle del pipeline de datos ya implementado: [`docs/pipeline.md`](pipeline.md).

---

## 6. Fases del proyecto

### Fase 0 — Entorno y repositorio *(hecho en gran parte)*

- Repo GitHub, estructura `src/`, configs, dependencias Python.
- Documentación básica y script de sync con GitHub.
- **Criterio de cierre:** entorno reproducible y docs de arranque.

### Fase 1 — Datos base (Catastro + PNOA) *(en curso)*

- Descargar ortofotos PNOA de la zona piloto (resolución suficiente para cubierta).
- Descargar edificios Catastro (WFS INSPIRE).
- Generar un crop / contexto por edificio.
- **Criterio de cierre:** cada edificio piloto tiene ortofoto + geometría catastral asociadas.
- **Estado:** scripts `download_pnoa`, `download_catastro`, `crop_buildings` operativos.

### Fase 2 — Delimitación de cubierta

- Partir del polígono Catastro como ancla.
- Refinar automáticamente la **máscara de tejado** (alineación ortofoto, erosión, quitar vegetación; SAM opcional como refinador).
- Exportar polígono de cubierta por inmueble.
- **Criterio de cierre:** GeoJSON/máscara de cubierta por edificio, revisada en muestra visual.
- **YOLO:** opcional, no bloqueante.

### Fase 3 — Superficie útil

- Limpiar huecos (patios), vegetación y obstáculos gruesos.
- Aplicar ratio de uso / setbacks si hace falta.
- Calcular **m² útiles** instalables.
- **Criterio de cierre:** área útil por referencia catastral, con reglas documentadas.

### Fase 4 — LiDAR: inclinación y orientación

- Descargar/procesar LiDAR PNOA de la zona.
- Extraer planos de cubierta (p. ej. RANSAC).
- Calcular pendiente (°), orientación (azimuth) y altura.
- Filtrar planos no aptos (pendiente excesiva, etc.).
- **Criterio de cierre:** atributos geométricos de cubierta por plano/edificio.

### Fase 5 — Sombras (aproximación)

- Obstáculos cercanos (edificios vecinos, vegetación alta vía LiDAR).
- Factor de sombreado simplificado.
- **Criterio de cierre:** coeficiente de pérdidas por sombra usable en el cálculo energético.

### Fase 6 — Potencial fotovoltaico (PVGIS)

- Consultar irradiación / producción según lat/lon, inclinación y orientación.
- Estimar kWp, kWh/año, ahorro económico y CO₂ (hipótesis en `constants.py`).
- **Criterio de cierre:** resultado energético por inmueble.

### Fase 7 — Base de datos (PostGIS)

- Modelo: `buildings`, `roofs`, `lidar_stats`, `solar_results`.
- Carga de geometrías y métricas.
- **Criterio de cierre:** consultas por referencia catastral y por bbox.

### Fase 8 — API y visor web

- Backend FastAPI.
- Frontend Leaflet (edificios, cubiertas, potencial).
- Consulta por referencia catastral.
- **Criterio de cierre:** demo usable en la zona piloto.

### Fase 9 — Evaluación y memoria TFM

- Validar geometría (muestra manual / IoU si hay labels).
- Validar energía (orden de magnitud vs casos reales o literatura).
- Redactar memoria: estado del arte, metodología, resultados, limitaciones.
- **Criterio de cierre:** entregable TFM + demo.

---

## 7. Prioridad inmediata (siguiente sprint)

1. Cerrar **Fase 1** con PNOA a `grid: 20` (crops con más píxeles de cubierta).
2. Empezar **Fase 2**: módulo de refinamiento de cubierta a partir de Catastro + ortofoto.
3. Preparar descarga LiDAR (**Fase 4**) en paralelo cuando la máscara de cubierta sea estable.
4. Aparcar YOLO salvo que se necesite como experimento opcional.

---

## 8. Estructura del código (actual)

```text
configs/               # pilot_area.yaml, development.yaml
docs/                  # pipeline.md, este documento
scripts/               # sync_github, utilidades
src/
  common/              # config, paths, constants, logger, fs
  data/                # download_pnoa, download_catastro, crop_buildings, …
  gis/                 # análisis espacial (a completar: cubierta, slope, …)
  solar/               # PVGIS / energía (stubs)
  database/            # PostGIS (stubs)
  api/                 # FastAPI (stub)
  ai/                  # opcional (YOLO / SAM) — no núcleo
```

---

## 9. Entregable final

Un sistema capaz de, para un edificio catastral de la zona piloto:

1. Obtener / refinar la **cubierta**.
2. Calcular **área útil**, **pendiente** y **orientación**.
3. Estimar **producción fotovoltaica**.
4. Guardar el resultado y **mostrarlo en un mapa**.

---

## 10. Documentos relacionados

| Documento | Contenido |
|-----------|-----------|
| [`docs/pipeline.md`](pipeline.md) | Pipeline de datos implementado (comandos, carpetas) |
| [`docs/ui-roadmap.md`](ui-roadmap.md) | Roadmap de interfaz (localizar → crop → cubierta → inclinación) |
| [`ROADMAP.md`](../ROADMAP.md) | Roadmap histórico (orientado a YOLO); este doc es la visión actual |
| `configs/pilot_area.yaml` | BBOX, PNOA, defaults de crop |

---

*Última actualización: visión del proyecto centrada en Catastro → cubierta → LiDAR → PVGIS (YOLO opcional).*
