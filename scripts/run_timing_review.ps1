# User-run only. Preserve evidence, check settings, compile, then inspect the
# fresh fit. No cleanup, commit, deployment, or modification of project settings.
param([string]$QuartusBin = 'C:\intelFPGA_lite\17.0\quartus\bin64')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$runPath = Join-Path 'scratch/timing_runs' (Get-Date -Format 'yyyyMMdd_HHmmss')
New-Item -ItemType Directory -Path $runPath | Out-Null
$previousReports = Join-Path $runPath 'previous_reports'
New-Item -ItemType Directory -Path $previousReports | Out-Null
Get-ChildItem -LiteralPath 'output_files' -File |
    Where-Object { $_.Name -match '^MacLC\.(map|fit|sta|flow|asm)\.(rpt|summary)$' } |
    Copy-Item -Destination $previousReports
git rev-parse HEAD | Out-File (Join-Path $runPath 'source-head.txt') -Encoding ascii
git status --short | Out-File (Join-Path $runPath 'source-status.txt') -Encoding utf8
git diff --binary | Out-File (Join-Path $runPath 'source-diff.txt') -Encoding utf8
# Snapshot changed files, including new review scripts, before Quartus can
# rewrite anything. Keep their relative paths alongside the source diff.
$sourcePath = Join-Path $runPath 'sources'
foreach ($relative in @('MacLC.qsf', 'MacLC.sdc', 'MacLC.sv',
    'rtl/tv525_video.sv', 'rtl/tv_ddram_bridge.sv', 'rtl/tv_ddram_cdc.sv', 'rtl/tv_capture_fifo.sv',
    'rtl/tv_buffered_canvas.sv', 'rtl/tv_frame_store.sv',
    'scripts/check_project_settings.tcl', 'scripts/check_tv525_timing.tcl',
    'scripts/run_timing_review.ps1')) {
    $destination = Join-Path $sourcePath $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $relative -Destination $destination
}
Copy-Item -LiteralPath 'MacLC.qsf' -Destination (Join-Path $runPath 'MacLC.before.qsf')

function Invoke-ReviewStage {
    param([string]$Stage, [string]$Executable, [string[]]$Arguments)
    # Native stderr must be logged without PowerShell stopping before the
    # executable's exit code and post-run QSF can be preserved.
    $ErrorActionPreference = 'Continue'
    & $Executable @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $runPath "$Stage.log")
    $stageExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $stageExit | Out-File (Join-Path $runPath "$Stage.exit.txt") -Encoding ascii
    Copy-Item -LiteralPath 'MacLC.qsf' -Destination (Join-Path $runPath "MacLC.after_$Stage.qsf")
    Write-Host "REVIEW $Stage exit=$stageExit reports=$runPath"
    if ($stageExit -ne 0) { exit $stageExit }
}

Invoke-ReviewStage 'settings' (Join-Path $QuartusBin 'quartus_sh.exe') @('-t', 'scripts/check_project_settings.tcl')
$compileStarted = Get-Date
Invoke-ReviewStage 'compile' (Join-Path $QuartusBin 'quartus_sh.exe') @('--flow', 'compile', 'MacLC')
# A stale fitted database must never stand in for this compilation.
$fitReport = Get-Item -LiteralPath 'output_files/MacLC.fit.rpt'
if ($fitReport.LastWriteTime -lt $compileStarted -or
    !(Select-String -LiteralPath $fitReport.FullName -Pattern 'Fitter Status\s*;\s*Successful' -Quiet)) {
    throw "No fresh successful fitter report. Stop here and inspect $runPath/compile.log."
}
Invoke-ReviewStage 'timing_gate' (Join-Path $QuartusBin 'quartus_sta.exe') @('-t', 'scripts/check_tv525_timing.tcl')
Write-Host "REVIEW complete: inspect diagnostics and unconstrained paths as well as gate results. Reports: $runPath"
