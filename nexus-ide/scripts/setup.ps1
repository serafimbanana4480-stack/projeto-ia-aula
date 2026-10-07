<#
.SYNOPSIS
NEXUS IDE — initial bootstrap for Windows (PowerShell, no WSL required).

.PARAMETER SkipDocker
If set, skips Docker infrastructure (Redis, Prometheus).

.PARAMETER SkipModels
If set, skips AirLLM model pre-download.

.EXAMPLE
.\setup.ps1

.EXAMPLE
.\setup.ps1 -SkipDocker -SkipModels
#>

[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [switch]$SkipModels
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "`n🚀 NEXUS IDE — initial setup (Windows / PowerShell)`n" -ForegroundColor Cyan

# 1. Validate .env
if (-not (Test-Path ".env")) {
    Write-Host "ℹ️  Creating .env from .env.example (edit BRAVE_API_KEY etc.)" -ForegroundColor Yellow
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
    } else {
        Write-Host "⚠️  .env.example not found — skipping .env creation" -ForegroundColor Yellow
    }
} else {
    Write-Host "✅ .env already exists" -ForegroundColor Green
}

# 2. Start infrastructure (Redis, Prometheus) unless skipped
if (-not $SkipDocker) {
    Write-Host "`n🐳 Starting infrastructure..." -ForegroundColor Cyan
    Push-Location docker
    try {
        docker compose up -d redis prometheus 2>&1 | Out-Null
        Write-Host "✅ Redis and Prometheus started" -ForegroundColor Green
        Write-Host "   Waiting 5s for services to become ready..." -ForegroundColor Gray
        Start-Sleep -Seconds 5
    } catch {
        Write-Host "⚠️  Docker failed: $_" -ForegroundColor Yellow
        Write-Host "   Continue without Docker infrastructure." -ForegroundColor Yellow
    }
    Pop-Location
} else {
    Write-Host "`n⏭️  Skipping Docker (--SkipDocker)" -ForegroundColor Gray
}

# 2b. Clean up stale pytest tmp directories
Write-Host "`n🧹 Cleaning stale .pytest_tmp* directories..." -ForegroundColor Cyan
$staleDirs = Get-ChildItem -Path $RepoRoot -Filter ".pytest_tmp*" -Directory
if ($staleDirs) {
    Remove-Item -Path $staleDirs.FullName -Recurse -Force
    Write-Host "   Removed $($staleDirs.Count) stale directories" -ForegroundColor Green
} else {
    Write-Host "   No stale directories found" -ForegroundColor Gray
}

# 3. Install Python dependencies
Write-Host "`n📦 Installing Python dependencies..." -ForegroundColor Cyan
if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m pip install -r backend/requirements.txt --quiet
    Write-Host "✅ Python dependencies installed" -ForegroundColor Green
} else {
    Write-Host "❌ Python not found in PATH. Install Python 3.12+ and retry." -ForegroundColor Red
    exit 1
}

# 4. Pre-download essential AirLLM models (optional)
if (-not $SkipModels) {
    Write-Host "`n⬇️  Pre-downloading AirLLM models (this may take a while)..." -ForegroundColor Cyan
    python scripts/setup-airllm-models.py micro fast coder 2>&1 | Out-Null
    Write-Host "✅ Model download complete (or skipped on failure)" -ForegroundColor Green
} else {
    Write-Host "`n⏭️  Skipping model download (--SkipModels)" -ForegroundColor Gray
}

# 5. Build sandbox image used by the code_executor
Write-Host "`n🔨 Building sandbox image..." -ForegroundColor Cyan
try {
    docker build -t nexus-sandbox -f docker/sandbox.Dockerfile . 2>&1 | Out-Null
    Write-Host "✅ Sandbox image built" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Sandbox build skipped: $_" -ForegroundColor Yellow
}

Write-Host "`n✅ Setup complete!" -ForegroundColor Green
Write-Host "   Start backend:  uvicorn backend.orchestrator.main:app --reload" -ForegroundColor Cyan
Write-Host "   Start frontend: cd frontend; npm run dev`n" -ForegroundColor Cyan
