# Bitget S2 Divergent Agent Desk — Windows launcher
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

Write-Host "Starting Divergent Agent Desk..."

function Get-Python {
    $venv = Join-Path $ScriptDir ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python not found. Install 3.11+ or start Docker Desktop."
}

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
cmd /c "docker info >nul 2>&1" | Out-Null
$useDocker = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap

if ($useDocker) {
    Write-Host "Docker is up."
} else {
    Write-Host "Docker not running — using local Python."
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example — add Bitget Demo keys (and Groq if AGENT_MODE=llm)."
    } else {
        Write-Host "Missing .env and .env.example"
        exit 1
    }
}

if ($useDocker) {
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    $py = Get-Python
    Write-Host "API + desk via $py"
    Start-Process -FilePath $py -ArgumentList @("scripts/run_api.py") -WorkingDirectory $ScriptDir -WindowStyle Minimized
    Start-Process -FilePath $py -ArgumentList @("scripts/run_signal_loop.py", "--poll") -WorkingDirectory $ScriptDir -WindowStyle Minimized
}

$health = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 2
        if ($health.ok -eq $true) { break }
    } catch {
        $health = $null
    }
}

if ($health -and $health.ok -eq $true) {
    Write-Host "Health ok  exec_mode=$($health.exec_mode)  http://127.0.0.1:8080"
} else {
    Write-Host "Dashboard not healthy yet. Check: docker compose logs -f"
    Write-Host "Expected GET /health -> { ok: true, exec_mode: hub_demo }"
    exit 1
}
