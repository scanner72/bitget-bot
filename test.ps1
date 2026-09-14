# ==============================================================================
# Bitget S2 Divergent Agent Desk - Automated Test Suite
# ==============================================================================
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

Write-Host "`n🧪 Running Bitget S2 Divergent Agent Desk Test Suite..." -ForegroundColor Cyan

# 1. Smoke Tests
Write-Host "`n[1/2] Running Risk Gate Smoke Test..." -ForegroundColor Yellow
python scripts/smoke_risk.py

Write-Host "`n[2/2] Running Paper Shadow Book Smoke Test..." -ForegroundColor Yellow
python scripts/smoke_paper.py

Write-Host "`n✅ Test suite execution complete." -ForegroundColor Green
