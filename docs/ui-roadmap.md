# Roadmap de interfaz de usuario

## 1. Visión

La UI no es un detector genérico de tejados: es una **herramienta por inmueble**.

Flujo principal:

```text
1. Localizar inmueble (Catastro + búsqueda)
        │
        ▼
2. Ver crop PNOA del edificio
        │
        ▼
3. Limpiar / delimitar la cubierta
        │
        ▼
4. Revisar inclinación / orientación (LiDAR)
        │
        ▼
5. (Luego) potencial solar
```

Navegar solo por `building_000022.tif` **no basta**: hace falta **metadatos catastrales** (referencia, dirección/municipio, parcela) para encontrar el edificio correcto.

---

## 2. Principio de diseño

| Capa | Contenido |
|------|-----------|
| **Identidad** | Datos Catastro (localizar) |
| **Contexto** | Crop ortofoto + huella catastral |
| **Cubierta** | Máscara/polígono editable o semi-automático |
| **Geometría 3D** | Pendiente, azimuth, planos LiDAR |
| **Energía** | PVGIS (fase posterior) |

Una pantalla = un trabajo. No mezclar búsqueda, edición de máscara y cálculo solar en un único caos.

---

## 3. Datos Catastro que debe mostrar / indexar la UI

Mínimo para localizar:

| Campo | Uso en UI |
|-------|-----------|
| Referencia catastral | Búsqueda exacta / pegar RC |
| `localId` / id INSPIRE | Enlace interno estable |
| Municipio / provincia | Filtros |
| Geometría edificio | Mapa + overlay en el crop |
| Centroide / bbox | Zoom en mapa |

Deseable (si el WFS/GML lo trae o se enriquece):

| Campo | Uso |
|-------|-----|
| Dirección / vía | Búsqueda textual |
| Uso / tipología | Filtros |
| Nº de plantas (si existe) | Contexto |
| Parcela / ref. parcela | Agrupar inmuebles |

**Implicación técnica:** al hacer `crop_buildings`, persistir un índice (p. ej. `building_crops/index.geojson` o tabla PostGIS) con `building_id`, RC, attrs catastrales, path del crop y bbox.

Sin ese índice, la UI solo puede hacer “siguiente / anterior archivo”.

---

## 4. Pantallas (wireflow)

### A. Explorador / localización

- Mapa Leaflet de la zona piloto (huellas Catastro).
- Buscador: referencia catastral, texto (si hay dirección), filtros municipio.
- Lista de resultados + miniatura del crop si existe.
- Acción: **Abrir inmueble**.

### B. Ficha del inmueble (crop inicial)

- Panel izquierdo: datos Catastro (RC, attrs, enlace a sede catastral si aplica).
- Panel central: **ortofoto crop** con overlay de polígono Catastro.
- Controles: zoom, capas (orto / catastro on-off).
- CTA: **Delimitar cubierta**.

### C. Limpieza y detección de tejado

- Misma ortofoto.
- Capas: Catastro, máscara actual, vegetación/excluido (si hay).
- Acciones:
  - Auto-refinar (botón → backend).
  - Herramientas manuales ligeras: pincel, borrar, polígono, reset.
  - Aceptar / guardar máscara de cubierta.
- Salida: GeoJSON/máscara versionada por `building_id`.

### D. Inclinación / orientación

- Vista del plano(s) de cubierta sobre el crop o esquema 2D.
- Tabla: pendiente (°), azimuth, área del plano, válido sí/no.
- Origen: LiDAR (cuando exista); hasta entonces placeholder “pendiente de datos LiDAR”.
- CTA: **Calcular potencial** (fase posterior).

### E. (Futuro) Resultado solar

- kWp, kWh/año, CO₂, resumen para el inmueble.

---

## 5. Navegación entre crops

Además de la búsqueda catastral:

- **Anterior / siguiente** en la lista filtrada actual (no en todo el disco a ciegas).
- Atajos teclado en modo revisión masiva (QA de máscaras).
- Estado: sin procesar / cubierta OK / LiDAR OK / solar OK (badges).

Así “navegar crops” tiene sentido **dentro de un contexto** (filtro, municipio, pendientes de revisión).

---

## 6. Fases de UI

### UI-0 — Preparación de datos para la interfaz *(implementado en crop_buildings)*

- Ampliar el artefacto por edificio: crop + attrs catastrales.
- Generar **`data/raw/catastro/building_crops/index.geojson`** (RC, uso, paths, centroide, bbox).
- Cada `building_XXXXXX.geojson` incluye los mismos attrs para la ficha.
- **Criterio:** se puede buscar un edificio por `reference` (RC) en el índice y abrir su crop.

### UI-1 — Explorador + ficha (MVP)

- Mapa + búsqueda por RC.
- Ficha con crop + overlay Catastro + datos básicos.
- Navegación anterior/siguiente en resultados.
- Stack sugerido: FastAPI + Leaflet (o MapLibre) + frontend simple.
- **Criterio:** localizar un inmueble de Boadilla y ver su crop.

### UI-2 — Taller de cubierta

- Auto-refinar + edición básica de máscara.
- Guardar resultado por inmueble.
- **Criterio:** operador limpia/delimita tejado y lo persiste.

### UI-3 — Panel de inclinación

- Integrar resultados LiDAR (planos, slope, aspect).
- Visualización y tabla por plano.
- **Criterio:** tras cubierta aceptada, se ven pendientes.

### UI-4 — Potencial solar + pulido

- PVGIS, resumen, export PDF/JSON.
- Mejoras UX (estados, cola de revisión, auth si hace falta).

---

## 7. Dependencias con el backend (alineado a `docs/proyecto.md`)

| UI | Necesita de backend / datos |
|----|-----------------------------|
| UI-0 / UI-1 | Fase 1 datos + índice Catastro enriquecido |
| UI-2 | Fase 2 delimitación de cubierta (API refine + save) |
| UI-3 | Fase 4 LiDAR |
| UI-4 | Fases 5–6 sombras / PVGIS |

La UI se construye **encima** del flujo Catastro → cubierta → LiDAR; no al revés.

---

## 8. Stack orientativo

| Pieza | Opción |
|-------|--------|
| API | FastAPI |
| Mapa | Leaflet o MapLibre |
| Front | HTML/JS ligero o React (si crece) |
| Datos | GeoJSON índice al inicio → PostGIS después |
| Auth | Más adelante (TFM local puede ir sin ella) |

---

## 9. Prioridad inmediata (UI)

1. ~~**UI-0:** índice Catastro↔crop~~ → `python -m src.data.crop_buildings` genera `index.geojson`.
2. **UI-1:** pantalla mapa + búsqueda RC + ficha con crop.
3. Luego UI-2 cuando exista el refinador de cubierta.

---

## 10. Resumen

Sí tiene sentido la UI que planteas, con este orden:

1. **Más info Catastro** para localizar.  
2. **Mostrar crop** del inmueble elegido.  
3. **Interfaz de limpiar / delimitar tejado.**  
4. **Inclinación** (LiDAR).  

Documentos relacionados: [`proyecto.md`](proyecto.md) (fases de producto), [`pipeline.md`](pipeline.md) (datos).
