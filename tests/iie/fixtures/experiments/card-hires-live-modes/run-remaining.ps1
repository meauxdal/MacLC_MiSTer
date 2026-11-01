param(
    [string]$Python = 'C:/Users/Elle/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
)

$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
$runner = Join-Path $PSScriptRoot 'run.py'
foreach ($case in @(
    @('--driver', '6'),
    @('--driver', '6', '--page2'),
    @('--driver', '5', '--page2', '--mixed', '80'),
    @('--driver', '6', '--page2', '--mixed', '40')
)) {
    & $Python -B $runner @case
    if ($LASTEXITCODE -ne 0) { throw "Hires case failed: $($case -join ' ')" }
}
