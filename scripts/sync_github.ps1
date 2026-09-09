<#
.SYNOPSIS
  Sincroniza el repositorio local con GitHub (baja y sube cambios).

.DESCRIPTION
  1. git fetch + pull (trae cambios remotos)
  2. Opcionalmente hace commit de cambios locales (-Commit o -Message)
  3. git push (sube commits locales)

.EXAMPLE
  .\scripts\sync_github.ps1
  # Solo pull + push de commits ya hechos

.EXAMPLE
  .\scripts\sync_github.ps1 -Commit -Message "Update pipeline docs"
  # Añade cambios, commit, pull y push
#>
param(
    [string]$Message = "",
    [string]$Branch = "main",
    [switch]$Commit
)

$ErrorActionPreference = "Stop"

function Get-GitExe {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $fallback = "C:\Program Files\Git\cmd\git.exe"
    if (Test-Path $fallback) {
        return $fallback
    }
    throw "Git no encontrado. Instala Git o añádelo al PATH."
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & $script:GitExe @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') fallo con codigo $LASTEXITCODE"
    }
}

$GitExe = Get-GitExe
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Repo: $RepoRoot"
Write-Host "Remote branch: origin/$Branch"
Write-Host ""

# Archivos que nunca se suben automaticamente con -Commit
$ExcludeFromAutoCommit = @(
    "wip.txt",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "credentials.json"
)

$status = & $GitExe status --porcelain
$dirty = -not [string]::IsNullOrWhiteSpace($status)

if ($dirty) {
    Write-Host "Cambios locales detectados:"
    Write-Host $status
    Write-Host ""
}

$shouldCommit = $Commit -or -not [string]::IsNullOrWhiteSpace($Message)

if ($dirty -and $shouldCommit) {
    if ([string]::IsNullOrWhiteSpace($Message)) {
        $Message = "Sync: local updates $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    }

    Write-Host "Preparando commit..."
    Invoke-Git add -A

    foreach ($pattern in $ExcludeFromAutoCommit) {
        $matches = Get-ChildItem -Path $RepoRoot -Filter $pattern -File -ErrorAction SilentlyContinue
        foreach ($file in $matches) {
            & $GitExe reset HEAD -- $file.FullName 2>$null
            Write-Host "Excluido del commit: $($file.Name)"
        }
        # Also unstage if already tracked path matches relative name
        & $GitExe reset HEAD -- $pattern 2>$null | Out-Null
    }

    $staged = & $GitExe diff --cached --name-only
    if ([string]::IsNullOrWhiteSpace($staged)) {
        Write-Host "No hay nada seguro que commitear (solo archivos excluidos o sin cambios)."
    }
    else {
        Invoke-Git commit -m $Message
        Write-Host "Commit creado: $Message"
    }
}
elseif ($dirty -and -not $shouldCommit) {
    Write-Host "AVISO: hay cambios sin commit. No se subiran hasta que hagas commit."
    Write-Host "  Ejemplo: .\scripts\sync_github.ps1 -Commit -Message `"tu mensaje`""
    Write-Host ""
}

Write-Host "Bajando cambios (fetch + pull)..."
Invoke-Git fetch origin
# --autostash guarda temporalmente cambios locales (p. ej. wip.txt) durante el rebase
Invoke-Git pull --rebase --autostash origin $Branch

Write-Host "Subiendo cambios (push)..."
Invoke-Git push -u origin $Branch

Write-Host ""
Write-Host "Sincronizacion completada con origin/$Branch"
Invoke-Git status -sb
