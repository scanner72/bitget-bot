param (
    [string]$RemoteHost = "10.10.10.11",
    [string]$RemoteUser = "operator",
    [string]$RemotePath = "/opt/bitget-bot",
    [int]$AppPort = 8080
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

Write-Host "`n🚀 Deploying Bitget S2 Divergent Agent Desk to $RemoteHost ($RemoteUser)..." -ForegroundColor Cyan
Write-Host "Remote Path: $RemotePath | Port: $AppPort" -ForegroundColor Gray

Write-Host "[1/4] Ensuring remote directory $RemotePath..." -ForegroundColor Yellow
ssh "${RemoteUser}@${RemoteHost}" "mkdir -p $RemotePath"

Write-Host "[2/4] Packaging repository (excluding .git, venv, caches)..." -ForegroundColor Yellow
tar --exclude=".git" --exclude=".venv" --exclude="*__pycache__*" --exclude="*.pytest_cache*" --exclude="data/decisions.jsonl" -czf bitget_bot_deploy.tar.gz .
scp bitget_bot_deploy.tar.gz "${RemoteUser}@${RemoteHost}:${RemotePath}/"
ssh "${RemoteUser}@${RemoteHost}" "cd $RemotePath && tar -xzf bitget_bot_deploy.tar.gz && rm bitget_bot_deploy.tar.gz"
Remove-Item -Force bitget_bot_deploy.tar.gz

Write-Host "[3/4] Launching Docker stack on remote host..." -ForegroundColor Yellow
ssh "${RemoteUser}@${RemoteHost}" "cd $RemotePath && docker compose up -d --build"

Write-Host "[4/4] Verifying remote health..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
try {
    $health = Invoke-RestMethod -Uri "http://${RemoteHost}:${AppPort}/health" -TimeoutSec 10
    Write-Host "✅ Deployment successful! Service status: $($health.status)" -ForegroundColor Green
    Write-Host "Web Dashboard available at: http://${RemoteHost}:${AppPort}" -ForegroundColor Cyan
} catch {
    Write-Host "⚠️ Service initializing. Check logs with: ssh ${RemoteUser}@${RemoteHost} 'docker logs bitget-desk-api'" -ForegroundColor Yellow
}
