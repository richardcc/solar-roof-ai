# Arranca la UI de Solar Roof AI (FastAPI + Leaflet)
Set-Location (Split-Path -Parent $PSScriptRoot)
if (Test-Path .\.venv\Scripts\Activate.ps1) {
    .\.venv\Scripts\Activate.ps1
}
Write-Host "UI: http://127.0.0.1:8000"
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
