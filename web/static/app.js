const state = {
  features: [],
  filtered: [],
  selectedId: null,
  layer: null,
  orthoMode: "local", // local | hires
  hiresCached: false,
  regions: [],
  selectedRegionId: null,
};

const map = L.map("map", { zoomControl: true }).setView([40.405, -3.875], 13);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 20,
  attribution: "&copy; OpenStreetMap",
}).addTo(map);

const appEl = document.querySelector(".app");
const resultsEl = document.getElementById("results");
const detailEl = document.getElementById("detail");
const workSplitterEl = document.getElementById("work-splitter");
const detailFieldsEl = document.getElementById("detail-fields");
const detailRefEl = document.getElementById("detail-ref");
const cropImageEl = document.getElementById("crop-image");
const cropCatastroImageEl = document.getElementById("crop-catastro-image");
const cropCatastroThumbEl = document.getElementById("crop-catastro-thumb");
const canvasStageEl = document.getElementById("canvas-stage");
const canvasWorldEl = document.getElementById("canvas-world");
const maskCanvasEl = document.getElementById("mask-canvas");
const maskOverlayEl = document.getElementById("mask-overlay");
const regionsOverlayEl = document.getElementById("regions-overlay");
const maskStatusEl = document.getElementById("mask-status");
const regionStatusEl = document.getElementById("region-status");
const regionsListEl = document.getElementById("regions-list");
const orthoResLabelEl = document.getElementById("ortho-res-label");
const viewerZoomLabelEl = document.getElementById("viewer-zoom-label");
const hiresBtn = document.getElementById("hires-btn");
const resultCountEl = document.getElementById("result-count");
const statusEl = document.getElementById("status");
const searchInput = document.getElementById("search-input");
const catastroLink = document.getElementById("catastro-link");
const pilotLabel = document.getElementById("pilot-label");

const viewer = {
  scale: 1,
  x: 0,
  y: 0,
  naturalW: 0,
  naturalH: 0,
  panning: false,
  panStartX: 0,
  panStartY: 0,
  originX: 0,
  originY: 0,
};

function applyViewerTransform() {
  canvasWorldEl.style.transform = `translate(${viewer.x}px, ${viewer.y}px) scale(${viewer.scale})`;
  viewerZoomLabelEl.textContent = `${Math.round(viewer.scale * 100)}%`;
}

function syncOverlaySizes() {
  const w = cropImageEl.naturalWidth;
  const h = cropImageEl.naturalHeight;
  if (!w || !h) return;
  viewer.naturalW = w;
  viewer.naturalH = h;
  canvasWorldEl.style.width = `${w}px`;
  canvasWorldEl.style.height = `${h}px`;
  cropCatastroImageEl.style.width = `${w}px`;
  cropCatastroImageEl.style.height = `${h}px`;
  if (maskOverlayEl) {
    maskOverlayEl.style.width = `${w}px`;
    maskOverlayEl.style.height = `${h}px`;
  }
  if (regionsOverlayEl) {
    regionsOverlayEl.style.width = `${w}px`;
    regionsOverlayEl.style.height = `${h}px`;
  }
  maskCanvasEl.width = w;
  maskCanvasEl.height = h;
  maskCanvasEl.style.width = `${w}px`;
  maskCanvasEl.style.height = `${h}px`;
}

function updateRegionStatus() {
  if (!regionStatusEl) return;
  if (state.selectedRegionId) {
    regionStatusEl.textContent = `Región ${state.selectedRegionId} seleccionada`;
  } else if (state.regions.length) {
    regionStatusEl.textContent = `${state.regions.length} región(es) · elige una`;
  } else {
    regionStatusEl.textContent = "Ninguna seleccionada";
  }
}

function renderRegionsList() {
  if (!regionsListEl) return;
  if (!state.regions.length) {
    regionsListEl.innerHTML = `<li class="muted">Pulsa «Detectar regiones»</li>`;
    updateRegionStatus();
    return;
  }
  regionsListEl.innerHTML = state.regions
    .map((region) => {
      const active = region.id === state.selectedRegionId ? "active" : "";
      const [r, g, b] = region.color || [200, 200, 200];
      return `<li class="${active}" data-region-id="${region.id}">
        <span class="swatch" style="background:rgb(${r},${g},${b})"></span>
        <span>Región ${region.id}</span>
        <span class="meta">${region.pixels} px</span>
      </li>`;
    })
    .join("");
  updateRegionStatus();
}

function showRegionsOverlay() {
  if (!state.selectedId || !regionsOverlayEl) return;
  const src = maskSource();
  const selected = state.selectedRegionId ? `&selected=${state.selectedRegionId}` : "";
  regionsOverlayEl.style.display = "block";
  regionsOverlayEl.src = `/api/buildings/${encodeURIComponent(
    state.selectedId
  )}/mask/regions-overlay.png?source=${src}${selected}&ts=${Date.now()}`;
}

function clearRegions() {
  state.regions = [];
  state.selectedRegionId = null;
  if (regionsOverlayEl) {
    regionsOverlayEl.removeAttribute("src");
    regionsOverlayEl.style.display = "none";
  }
  renderRegionsList();
}

function selectRegion(regionId) {
  state.selectedRegionId = regionId || null;
  renderRegionsList();
  if (state.regions.length) showRegionsOverlay();
  updateRegionStatus();
}

async function detectRegions(mode = "auto") {
  if (!state.selectedId) return;
  const src = maskSource();
  setStatus("Detectando regiones…");
  if (regionStatusEl) regionStatusEl.textContent = "Detectando…";
  try {
    const response = await fetch(
      `/api/buildings/${encodeURIComponent(
        state.selectedId
      )}/mask/regions?source=${src}&mode=${encodeURIComponent(mode)}`,
      { method: "POST" }
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Error detectando regiones");
    state.regions = data.regions || [];
    state.selectedRegionId = null;
    renderRegionsList();
    showRegionsOverlay();
    setStatus(
      `${data.count} región(es). Selecciona una (lista o clic en la imagen) y luego aplica la herramienta.`
    );
  } catch (error) {
    console.error(error);
    setStatus(`Error regiones: ${error.message}`);
    if (regionStatusEl) regionStatusEl.textContent = `Error: ${error.message}`;
  }
}

async function pickRegionAtEvent(event) {
  if (!state.selectedId || !state.regions.length) return false;
  const rect = canvasStageEl.getBoundingClientRect();
  const screenX = event.clientX - rect.left;
  const screenY = event.clientY - rect.top;
  const imgX = Math.floor((screenX - viewer.x) / viewer.scale);
  const imgY = Math.floor((screenY - viewer.y) / viewer.scale);
  if (imgX < 0 || imgY < 0 || imgX >= viewer.naturalW || imgY >= viewer.naturalH) {
    return false;
  }
  const src = maskSource();
  try {
    const response = await fetch(
      `/api/buildings/${encodeURIComponent(
        state.selectedId
      )}/mask/region-at?source=${src}&x=${imgX}&y=${imgY}`
    );
    const data = await response.json();
    if (!response.ok) return false;
    if (data.region_id > 0) {
      selectRegion(data.region_id);
      setStatus(`Región ${data.region_id} seleccionada`);
      return true;
    }
  } catch (_) {
    /* ignore */
  }
  return false;
}

function maskSource() {
  return state.orthoMode === "hires" ? "hires" : "local";
}

function clearMaskOverlay() {
  if (maskOverlayEl) {
    maskOverlayEl.removeAttribute("src");
    maskOverlayEl.style.display = "none";
  }
  if (maskStatusEl) maskStatusEl.textContent = "Sin máscara";
}

function showMaskOverlay() {
  if (!state.selectedId || !maskOverlayEl) return;
  const src = maskSource();
  maskOverlayEl.style.display = "block";
  maskOverlayEl.src = `/api/buildings/${encodeURIComponent(
    state.selectedId
  )}/mask-overlay.png?source=${src}&ts=${Date.now()}`;
}

async function loadExistingMask() {
  if (!state.selectedId) return;
  const src = maskSource();
  try {
    const response = await fetch(
      `/api/buildings/${encodeURIComponent(state.selectedId)}/mask-overlay.png?source=${src}`
    );
    if (!response.ok) {
      clearMaskOverlay();
      return;
    }
    showMaskOverlay();
    if (maskStatusEl) maskStatusEl.textContent = `Máscara (${src}) cargada`;
  } catch (_) {
    clearMaskOverlay();
  }
}

async function runMaskAlgo(algo) {
  if (!state.selectedId) return;
  const src = maskSource();
  if (!state.selectedRegionId && state.regions.length > 1) {
    const ok = window.confirm(
      "No hay región seleccionada. ¿Aplicar a TODAS las regiones?"
    );
    if (!ok) return;
  }
  const regionQuery = state.selectedRegionId
    ? `&region_id=${state.selectedRegionId}`
    : "";
  const target = state.selectedRegionId
    ? `región ${state.selectedRegionId}`
    : "todas";
  if (maskStatusEl) maskStatusEl.textContent = `Ejecutando ${algo} (${target})…`;
  setStatus(`${algo} → ${target} (${src})…`);
  try {
    const response = await fetch(
      `/api/buildings/${encodeURIComponent(state.selectedId)}/mask/run?algo=${encodeURIComponent(
        algo
      )}&source=${src}${regionQuery}`,
      { method: "POST" }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Error algoritmo");
    }
    showMaskOverlay();
    if (state.regions.length) showRegionsOverlay();
    if (maskStatusEl) {
      maskStatusEl.textContent = `${algo}${
        data.region_id ? ` · región ${data.region_id}` : ""
      }: tejado ${data.roof_pixels} px · sombra ${data.shadow_pixels} · piscina ${data.pool_pixels}`;
    }
    setStatus(`${algo} OK (${data.width}×${data.height})`);
  } catch (error) {
    console.error(error);
    setStatus(`Error ${algo}: ${error.message}`);
    if (maskStatusEl) maskStatusEl.textContent = `Error: ${error.message}`;
  }
}

function fitViewer() {
  syncOverlaySizes();
  const stage = canvasStageEl.getBoundingClientRect();
  if (!viewer.naturalW || !viewer.naturalH || !stage.width || !stage.height) return;
  const pad = 8;
  const scale = Math.min(
    (stage.width - pad * 2) / viewer.naturalW,
    (stage.height - pad * 2) / viewer.naturalH,
    1 // never upscale on fit — use 1:1 or zoom-in instead
  );
  viewer.scale = Math.max(0.05, scale);
  viewer.x = (stage.width - viewer.naturalW * viewer.scale) / 2;
  viewer.y = (stage.height - viewer.naturalH * viewer.scale) / 2;
  applyViewerTransform();
}

function zoomToNatural() {
  syncOverlaySizes();
  const stage = canvasStageEl.getBoundingClientRect();
  if (!viewer.naturalW || !stage.width) return;
  viewer.scale = 1;
  viewer.x = (stage.width - viewer.naturalW) / 2;
  viewer.y = (stage.height - viewer.naturalH) / 2;
  applyViewerTransform();
}

function zoomBy(factor, centerX, centerY) {
  const stage = canvasStageEl.getBoundingClientRect();
  const cx = centerX == null ? stage.width / 2 : centerX;
  const cy = centerY == null ? stage.height / 2 : centerY;
  const prev = viewer.scale;
  const next = Math.min(8, Math.max(0.05, prev * factor));
  if (next === prev) return;
  // Keep point under cursor stable.
  const worldX = (cx - viewer.x) / prev;
  const worldY = (cy - viewer.y) / prev;
  viewer.scale = next;
  viewer.x = cx - worldX * next;
  viewer.y = cy - worldY * next;
  applyViewerTransform();
}

function initViewerInteractions() {
  canvasStageEl.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const rect = canvasStageEl.getBoundingClientRect();
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoomBy(factor, event.clientX - rect.left, event.clientY - rect.top);
    },
    { passive: false }
  );

  canvasStageEl.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    viewer.panning = true;
    viewer.didPan = false;
    canvasStageEl.classList.add("is-panning");
    canvasStageEl.setPointerCapture(event.pointerId);
    viewer.panStartX = event.clientX;
    viewer.panStartY = event.clientY;
    viewer.originX = viewer.x;
    viewer.originY = viewer.y;
  });

  canvasStageEl.addEventListener("pointermove", (event) => {
    if (!viewer.panning) return;
    const dx = event.clientX - viewer.panStartX;
    const dy = event.clientY - viewer.panStartY;
    if (Math.abs(dx) + Math.abs(dy) > 4) viewer.didPan = true;
    viewer.x = viewer.originX + dx;
    viewer.y = viewer.originY + dy;
    applyViewerTransform();
  });

  async function endPan(event) {
    if (!viewer.panning) return;
    const wasClick = !viewer.didPan;
    viewer.panning = false;
    canvasStageEl.classList.remove("is-panning");
    try {
      canvasStageEl.releasePointerCapture(event.pointerId);
    } catch (_) {
      /* ignore */
    }
    if (wasClick && state.regions.length) {
      await pickRegionAtEvent(event);
    }
  }

  canvasStageEl.addEventListener("pointerup", endPan);
  canvasStageEl.addEventListener("pointercancel", endPan);

  document.getElementById("zoom-fit-btn").addEventListener("click", fitViewer);
  document.getElementById("zoom-100-btn").addEventListener("click", zoomToNatural);
  document.getElementById("zoom-in-btn").addEventListener("click", () => zoomBy(1.25));
  document.getElementById("zoom-out-btn").addEventListener("click", () => zoomBy(1 / 1.25));

  cropImageEl.addEventListener("load", () => {
    syncOverlaySizes();
    const stage = canvasStageEl.getBoundingClientRect();
    if (viewer.naturalW > stage.width * 1.15 || viewer.naturalH > stage.height * 1.15) {
      fitViewer();
    } else {
      zoomToNatural();
    }
    loadExistingMask();
  });
}

initViewerInteractions();

const WORK_W_KEY = "solar-roof-ai.work-w";
const WORK_W_MIN = 280;
const MAP_W_MIN = 80;

function setWorkWidth(px) {
  const rect = appEl.getBoundingClientRect();
  const leftW = parseFloat(getComputedStyle(appEl).getPropertyValue("--left-w")) || 320;
  const splitterW = parseFloat(getComputedStyle(appEl).getPropertyValue("--splitter-w")) || 6;
  const maxByMap = Math.max(WORK_W_MIN, rect.width - leftW - splitterW - MAP_W_MIN);
  const width = Math.max(WORK_W_MIN, Math.min(maxByMap, Math.round(px)));
  appEl.style.setProperty("--work-w", `${width}px`);
  localStorage.setItem(WORK_W_KEY, String(width));
  requestAnimationFrame(() => map.invalidateSize());
}

function showWorkPanel(show) {
  detailEl.classList.toggle("hidden", !show);
  workSplitterEl.classList.toggle("hidden", !show);
  appEl.classList.toggle("work-collapsed", !show);
  requestAnimationFrame(() => map.invalidateSize());
}

(function initWorkResize() {
  const saved = Number(localStorage.getItem(WORK_W_KEY));
  if (Number.isFinite(saved) && saved > 0) {
    setWorkWidth(saved);
  }

  let dragging = false;

  workSplitterEl.addEventListener("pointerdown", (event) => {
    if (detailEl.classList.contains("hidden")) return;
    dragging = true;
    appEl.classList.add("resizing");
    workSplitterEl.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  workSplitterEl.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const rect = appEl.getBoundingClientRect();
    setWorkWidth(rect.right - event.clientX);
  });

  function endDrag(event) {
    if (!dragging) return;
    dragging = false;
    appEl.classList.remove("resizing");
    try {
      workSplitterEl.releasePointerCapture(event.pointerId);
    } catch (_) {
      /* ignore */
    }
    map.invalidateSize();
  }

  workSplitterEl.addEventListener("pointerup", endDrag);
  workSplitterEl.addEventListener("pointercancel", endDrag);
})();

function setStatus(text) {
  statusEl.textContent = text;
}

function propsOf(feature) {
  return feature.properties || {};
}

function labelOf(feature) {
  const p = propsOf(feature);
  return p.reference || p.localId || p.building_id || "sin-id";
}

function renderList(features) {
  resultsEl.innerHTML = "";
  features.forEach((feature) => {
    const p = propsOf(feature);
    const li = document.createElement("li");
    li.dataset.id = p.building_id;
    if (p.building_id === state.selectedId) li.classList.add("active");
    li.innerHTML = `
      <div class="ref">${labelOf(feature)}</div>
      <div class="meta">${p.building_id || ""} · ${p.currentUse || "uso n/d"} · ${
      p.value != null ? `${p.value} ${p.value_uom || "m2"}` : "área n/d"
    }</div>
    `;
    li.addEventListener("click", () => selectBuilding(p.building_id));
    resultsEl.appendChild(li);
  });
  resultCountEl.textContent = `${features.length} inmueble(s)`;
}

function setOrthoSources(buildingId, mode) {
  const ts = Date.now();
  const base = `/api/buildings/${encodeURIComponent(buildingId)}`;
  if (mode === "hires") {
    cropImageEl.src = `${base}/crop-hires.png?ts=${ts}`;
    cropCatastroImageEl.src = `${base}/crop-hires-catastro.png?ts=${ts}`;
  } else {
    cropImageEl.src = `${base}/crop.png?ts=${ts}`;
    cropCatastroImageEl.src = `${base}/crop-catastro.png?ts=${ts}`;
  }
  // Thumb always from local catastro preview (fast).
  cropCatastroThumbEl.src = `${base}/crop-catastro.png?ts=${ts}`;
  cropCatastroThumbEl.alt = `Catastro ${buildingId}`;
}

function updateOrthoLabel(extra = "") {
  const mode = state.orthoMode === "hires" ? "Hi-res WMS" : "Crop local";
  orthoResLabelEl.textContent = extra ? `${mode} · ${extra}` : mode;
  hiresBtn.textContent = state.orthoMode === "hires" ? "Usar crop local" : "Cargar hi-res";
  hiresBtn.disabled = false;
}

async function refreshHiresStatus(buildingId) {
  try {
    const response = await fetch(
      `/api/buildings/${encodeURIComponent(buildingId)}/crop-hires/status`
    );
    const data = await response.json();
    state.hiresCached = Boolean(data.cached);
    if (data.cached) {
      updateOrthoLabel(`${data.width}×${data.height} (caché)`);
      return data;
    }
    updateOrthoLabel();
    return data;
  } catch (_) {
    state.hiresCached = false;
    updateOrthoLabel();
    return null;
  }
}

async function loadHiresForSelection(force = false) {
  if (!state.selectedId) return;
  const buildingId = state.selectedId;
  hiresBtn.disabled = true;
  hiresBtn.textContent = "Descargando…";
  orthoResLabelEl.textContent = "WMS PNOA…";
  setStatus(`Descargando hi-res de ${buildingId}…`);

  try {
    // If cache is lower-res than target, force refresh.
    const statusResponse = await fetch(
      `/api/buildings/${encodeURIComponent(buildingId)}/crop-hires/status`
    );
    const status = await statusResponse.json();
    const needUpgrade =
      status.cached && Math.max(status.width || 0, status.height || 0) < 3000;
    const response = await fetch(
      `/api/buildings/${encodeURIComponent(buildingId)}/crop-hires?force=${
        force || needUpgrade ? "true" : "false"
      }&max_side=4096`,
      { method: "POST" }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Error hi-res");
    }
    state.orthoMode = "hires";
    state.hiresCached = true;
    setOrthoSources(buildingId, "hires");
    updateOrthoLabel(`${data.width}×${data.height}${data.cached ? " (caché)" : " (nuevo)"}`);
    setStatus(
      data.cached
        ? `Hi-res en caché: ${data.width}×${data.height}`
        : `Hi-res descargado: ${data.width}×${data.height}`
    );
    if (maskStatusEl) {
      maskStatusEl.textContent = "Ortofoto hi-res lista para análisis";
    }
  } catch (error) {
    console.error(error);
    setStatus(`Error hi-res: ${error.message}`);
    updateOrthoLabel("falló descarga");
  } finally {
    hiresBtn.disabled = false;
    if (state.orthoMode !== "hires") {
      hiresBtn.textContent = "Cargar hi-res";
    }
  }
}

function useLocalOrtho() {
  if (!state.selectedId) return;
  state.orthoMode = "local";
  setOrthoSources(state.selectedId, "local");
  refreshHiresStatus(state.selectedId);
  setStatus("Usando crop local");
}

function renderDetail(feature) {
  const p = propsOf(feature);
  const fields = [
    ["RC", p.reference],
    ["ID", p.building_id],
    ["Uso", p.currentUse],
    ["Estado", p.conditionOfConstruction],
    ["Viviendas", p.numberOfDwellings],
    ["Área", p.value != null ? `${p.value} ${p.value_uom || ""}` : null],
    ["Municipio", p.municipality],
    ["Teselas", p.source_tiles || p.source_tile_count],
  ];

  detailFieldsEl.innerHTML = fields
    .filter(([, value]) => value != null && value !== "")
    .map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`)
    .join("");

  detailRefEl.textContent = labelOf(feature);

  cropImageEl.alt = `Crop ${labelOf(feature)}`;
  cropCatastroImageEl.alt = `Catastro ${labelOf(feature)}`;

  // Prefer cached hi-res if already downloaded for this building.
  state.orthoMode = "local";
  setOrthoSources(p.building_id, "local");
  refreshHiresStatus(p.building_id).then((status) => {
    if (status?.cached && state.selectedId === p.building_id) {
      state.orthoMode = "hires";
      setOrthoSources(p.building_id, "hires");
      updateOrthoLabel(`${status.width}×${status.height} (caché)`);
    }
  });

  if (maskStatusEl) {
    maskStatusEl.textContent = "Sin máscara · usa Detectar cubierta o pincel";
  }

  if (p.informationSystem) {
    catastroLink.href = p.informationSystem;
    catastroLink.style.display = "inline-block";
  } else {
    catastroLink.removeAttribute("href");
    catastroLink.style.display = "none";
  }

  showWorkPanel(true);
}

function paintMap(features) {
  if (state.layer) {
    map.removeLayer(state.layer);
  }
  state.layer = L.geoJSON(
    { type: "FeatureCollection", features },
    {
      style: (feature) => {
        const selected = propsOf(feature).building_id === state.selectedId;
        return {
          color: selected ? "#ffb454" : "#3d8bfd",
          weight: selected ? 3 : 1.5,
          fillColor: selected ? "#ffb454" : "#3d8bfd",
          fillOpacity: selected ? 0.45 : 0.2,
        };
      },
      onEachFeature: (feature, layer) => {
        layer.bindTooltip(labelOf(feature));
        layer.on("click", () => selectBuilding(propsOf(feature).building_id));
      },
    }
  ).addTo(map);

  if (features.length) {
    map.fitBounds(state.layer.getBounds(), { padding: [24, 24] });
  }
}

function selectBuilding(buildingId) {
  const feature = state.filtered.find((f) => propsOf(f).building_id === buildingId);
  if (!feature) return;
  state.selectedId = buildingId;
  clearRegions();
  renderList(state.filtered);
  renderDetail(feature);
  paintMap(state.filtered);

  const layer = state.layer.getLayers().find((l) => {
    const f = l.feature;
    return f && propsOf(f).building_id === buildingId;
  });
  if (layer) {
    map.fitBounds(layer.getBounds(), { maxZoom: 19, padding: [40, 40] });
  }
  setStatus(`Seleccionado: ${labelOf(feature)}`);
}

function moveSelection(delta) {
  if (!state.filtered.length || !state.selectedId) return;
  const ids = state.filtered.map((f) => propsOf(f).building_id);
  const index = ids.indexOf(state.selectedId);
  if (index < 0) return;
  const next = (index + delta + ids.length) % ids.length;
  selectBuilding(ids[next]);
}

async function loadMeta() {
  const response = await fetch("/api/meta");
  const meta = await response.json();
  const muni = meta.pilot_area?.municipality || "Zona piloto";
  const prov = meta.pilot_area?.province || "";
  pilotLabel.textContent = `${muni}${prov ? `, ${prov}` : ""} · ${meta.buildings} edificios`;
  if (meta.bbox?.min_lat != null) {
    map.fitBounds([
      [meta.bbox.min_lat, meta.bbox.min_lon],
      [meta.bbox.max_lat, meta.bbox.max_lon],
    ]);
  }
}

async function loadBuildings(query = "") {
  setStatus("Cargando edificios…");
  const url = query
    ? `/api/buildings?q=${encodeURIComponent(query)}`
    : "/api/buildings";
  const response = await fetch(url);
  const data = await response.json();
  state.features = data.features || [];
  state.filtered = state.features;
  renderList(state.filtered);
  paintMap(state.filtered);
  if (!state.filtered.length) {
    showWorkPanel(false);
    setStatus(data.message || "Sin edificios. Genera index.geojson con crop_buildings.");
    return;
  }
  setStatus(`${state.filtered.length} inmuebles cargados`);
  if (!state.selectedId) {
    selectBuilding(propsOf(state.filtered[0]).building_id);
  }
}

document.getElementById("search-btn").addEventListener("click", () => {
  loadBuildings(searchInput.value.trim());
});
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadBuildings(searchInput.value.trim());
});
document.getElementById("prev-btn").addEventListener("click", () => moveSelection(-1));
document.getElementById("next-btn").addEventListener("click", () => moveSelection(1));

hiresBtn.addEventListener("click", () => {
  if (state.orthoMode === "hires") {
    useLocalOrtho();
  } else {
    loadHiresForSelection(false);
  }
});

document.getElementById("layer-toggles")?.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;
  if (input.dataset.layer === "catastro") {
    canvasStageEl.classList.toggle("catastro-hidden", !input.checked);
  }
});

document.getElementById("tool-bar")?.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.dataset.mode) {
    document.querySelectorAll(".tool-mode").forEach((el) => el.classList.remove("active"));
    button.classList.add("active");
    if (maskStatusEl) {
      maskStatusEl.textContent = `Herramienta manual: ${button.textContent.trim()} (pincel próximamente)`;
    }
    return;
  }

  if (button.dataset.algo) {
    runMaskAlgo(button.dataset.algo);
    return;
  }

  const action = button.dataset.action;
  if (action === "reload-mask") {
    loadExistingMask();
  } else if (action === "clear-mask") {
    clearMaskOverlay();
  } else if (action === "detect-regions") {
    detectRegions("auto");
  } else if (action === "clear-region") {
    selectRegion(null);
    setStatus("Herramientas se aplicarán a todas las regiones");
  }
});

regionsListEl?.addEventListener("click", (event) => {
  const item = event.target.closest("[data-region-id]");
  if (!item) return;
  const regionId = Number(item.dataset.regionId);
  if (Number.isFinite(regionId) && regionId > 0) {
    selectRegion(regionId);
    setStatus(`Región ${regionId} seleccionada`);
  }
});

(async function init() {
  try {
    await loadMeta();
    await loadBuildings();
  } catch (error) {
    console.error(error);
    setStatus("Error cargando la API. ¿Está el servidor en marcha?");
  }
})();
