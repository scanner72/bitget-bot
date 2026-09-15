# Bitget S2 — offline smoke suite
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

$py = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "Python not found" }
    $py = $cmd.Source
}

$smokes = @(
    "scripts/smoke_signal.py",
    "scripts/smoke_candidate_log.py",
    "scripts/smoke_risk.py",
    "scripts/smoke_decide.py",
    "scripts/smoke_llm_decide.py",
    "scripts/smoke_paper.py",
    "scripts/smoke_account.py",
    "scripts/smoke_exits.py",
    "scripts/smoke_pair_blocker.py",
    "scripts/smoke_symbols.py",
    "scripts/smoke_upnl.py",
    "scripts/smoke_tick_stops.py",
    "scripts/smoke_paper_fallback.py",
    "scripts/smoke_hub_leverage.py",
    "scripts/smoke_reconcile.py",
    "scripts/smoke_chart.py",
    "scripts/smoke_export_paper_log.py"
)

Write-Host "Smokes via $py"
foreach ($s in $smokes) {
    Write-Host "  $s"
    & $py $s
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL $s (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
}
Write-Host "All smokes passed."
