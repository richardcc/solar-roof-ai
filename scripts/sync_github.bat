@echo off
REM Sincroniza con GitHub (pull + push). Pasa -Commit -Message "..." para subir cambios locales.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1" %*
