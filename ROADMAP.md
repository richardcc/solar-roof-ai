# Solar Roof AI - Roadmap del Proyecto

> **Visión actual del proyecto (fases actualizadas):**  
> ver [`docs/proyecto.md`](docs/proyecto.md) — enfoque **Catastro → cubierta → LiDAR → PVGIS** (YOLO opcional).
>
> El resto de este fichero es el roadmap histórico inicial (más centrado en detección YOLO).

## Descripción

Sistema basado en Inteligencia Artificial y Sistemas de Información Geográfica (SIG) para la detección automática de tejados y evaluación de su potencial fotovoltaico utilizando:

- PNOA
- Catastro
- LiDAR PNOA
- PVGIS
- Deep Learning (YOLO)
- PostGIS
- FastAPI
- Leaflet

---

# Objetivo General

Desarrollar una plataforma capaz de:

1. Detectar automáticamente tejados en imágenes aéreas.
2. Asociar cada tejado a un inmueble catastral.
3. Calcular superficie útil.
4. Calcular orientación e inclinación mediante LiDAR.
5. Evaluar sombras potenciales.
6. Consultar irradiación solar mediante PVGIS.
7. Estimar producción fotovoltaica.
8. Mostrar resultados en un visor web GIS.

---

# Arquitectura General

```text
PNOA
  |
  v
YOLO Segmentation
  |
  v
Roof Polygons
  |
  +------ Catastro
  |
  +------ LiDAR
  |
  v
Geospatial Analysis
  |
  v
PVGIS
  |
  v
Solar Potential
  |
  v
PostGIS
  |
  v
Web GIS
```

---

# FASE 1 - Preparación del entorno

## Objetivos

- Crear repositorio GitHub.
- Crear estructura de carpetas.
- Configurar entorno Python.
- Configurar VS Code.
- Preparar documentación del proyecto.

## Resultado

Repositorio preparado para desarrollo.

Estado:

- [x] GitHub
- [x] Estructura inicial
- [ ] Entorno IA
- [ ] Entorno GIS

---

# FASE 2 - Obtención de datos

## Objetivos

Descargar y organizar:

### PNOA

- Ortofotos RGB

### Catastro

- Parcelas
- Construcciones
- Referencias catastrales

### LiDAR PNOA

- Datos LAS/LAZ

### PVGIS

- Datos de irradiación

## Resultado

Directorio:

data/raw/

completo.

Estado:

- [ ] PNOA
- [ ] Catastro
- [ ] LiDAR
- [ ] PVGIS

---

# FASE 3 - Dataset IA

## Objetivos

- Crear muestras de entrenamiento.
- Asociar edificios a imágenes.
- Generar etiquetas.
- Crear conjuntos train/val/test.

## Resultado

Dataset listo para entrenamiento.

Estado:

- [ ] Dataset inicial
- [ ] Etiquetado
- [ ] Validación

---

# FASE 4 - Detección de tejados

## Objetivos

Entrenar modelo:

- YOLOv11-seg

Evaluar:

- Precision
- Recall
- F1
- IoU
- mAP

## Resultado

Modelo capaz de detectar tejados.

Estado:

- [ ] Entrenamiento inicial
- [ ] Evaluación
- [ ] Optimización

---

# FASE 5 - Integración Catastro

## Objetivos

Relacionar:

Tejado detectado
→ Edificio
→ Parcela
→ Referencia catastral

## Resultado

Base de inmuebles identificados.

Estado:

- [ ] Integración
- [ ] Validación

---

# FASE 6 - Procesamiento LiDAR

## Objetivos

Calcular:

- Altura
- Planos de cubierta
- Pendiente
- Orientación

## Resultado

Caracterización geométrica de cubiertas.

Estado:

- [ ] Alturas
- [ ] Pendientes
- [ ] Orientaciones

---

# FASE 7 - Sombras

## Objetivos

Detectar obstáculos:

- Edificios
- Vegetación

Calcular:

- Factor de sombreado

## Resultado

Estimación de pérdidas por sombra.

Estado:

- [ ] Modelo de sombreado
- [ ] Validación

---

# FASE 8 - Potencial Fotovoltaico

## Objetivos

Integrar PVGIS.

Calcular:

- kWp instalables
- kWh/año
- ahorro económico
- reducción CO₂

## Resultado

Potencial solar por inmueble.

Estado:

- [ ] Irradiación
- [ ] Producción
- [ ] Cálculos económicos

---

# FASE 9 - Base de Datos

## Objetivos

Implementar:

- PostgreSQL
- PostGIS

Tablas:

- buildings
- roofs
- lidar
- solar_results

## Resultado

Repositorio central de datos.

Estado:

- [ ] Diseño
- [ ] Implementación

---

# FASE 10 - Aplicación Web

## Backend

- FastAPI

## Frontend

- Leaflet

## Funcionalidades

- Visualizar edificios
- Visualizar tejados
- Mostrar potencial solar
- Consulta por referencia catastral

Estado:

- [ ] Backend
- [ ] Frontend
- [ ] Integración

---

# FASE 11 - Evaluación

## Métricas IA

- Precision
- Recall
- F1
- IoU
- mAP

## Métricas GIS

- Error espacial
- Error geométrico

## Métricas energéticas

- Producción estimada
- Diferencia respecto a valores reales

Estado:

- [ ] IA
- [ ] GIS
- [ ] Energía

---

# FASE 12 - Memoria TFM

## Documentos

- Introducción
- Estado del arte
- Metodología
- Desarrollo
- Resultados
- Conclusiones

Estado:

- [ ] Introducción
- [ ] Estado del arte
- [ ] Metodología
- [ ] Desarrollo
- [ ] Resultados
- [ ] Conclusiones

---

# Entregable Final

Sistema capaz de:

- Detectar tejados automáticamente.
- Caracterizarlos mediante LiDAR.
- Estimar producción fotovoltaica.
- Almacenar resultados en PostGIS.
- Visualizar resultados en un GIS web.