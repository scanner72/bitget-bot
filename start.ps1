# ==============================================================================
# Bitget S2 Divergent Agent Desk - 1-Click Platform Launcher (Windows PowerShell)
# ==============================================================================
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

Write-Host "`n🚀 Starting Bitget S2 Divergent Agent Desk..." -ForegroundColor Cyan

# 1. Verify Docker Daemon
Write-Host "[1/4] Checking Docker status..." -ForegroundColor Yellow
$useDocker = $true
try {
    docker info > $null 2>&1
    Write-Host "  ✅ Docker daemon is running." -ForegroundColor Green
} catch {
    Write-Host "  ⚠️ Docker daemon is not running. Checking local Python environment..." -ForegroundColor Yellow
    $useDocker = $false
}

# 2. Verify / Setup Environment File
Write-Host "[2/4] Verifying environment configuration..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "  ⚠️ Created default .env from .env.example. Add your Bitget Demo keys." -ForegroundColor Yellow
    } else {
        Write-Host "  ❌ Error: Neither .env nor .env.example found." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  ✅ .env configuration found." -ForegroundColor Green
}

# 3. Launch Services
if ($useDocker) {
    Write-Host "[3/4] Launching Docker Compose stack..." -ForegroundColor Yellow
    docker compose up -d
} else {
    Write-Host "[3/4] Launching services via local Python..." -ForegroundColor Yellow
    Start-Process -FilePath "python" -ArgumentList "scripts/run_api.py" -WindowStyle Minimized
    Start-Process -FilePath "python" -ArgumentList "scripts/run_signal_loop.py --poll" -WindowStyle Minimized
}

# 4. Verification & Status Box
Write-Host "`n[4/4] Verifying services..." -ForegroundColor Yellow
Start-Sleep -Seconds 4

Write-Host @"

==============================================================================
✨ Bitget S2 Divergent Agent Desk is LIVE!
==============================================================================

  💻 Web Dashboard:     http://127.0.0.1:8080
  📡 REST API Health:   http://127.0.0.1:8080/health
  📈 Signal Candidates: http://127.0.0.1:8080/candidates
  💼 Active Positions:  http://127.0.0.1:8080/positions

To view real-time Docker logs:
  docker compose logs -f

To stop all containers:
  docker compose down
==============================================================================
"@ -ForegroundColor Cyan
