param(
    [string]$Python = 'C:/Users/Elle/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
)

$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
$runner = Join-Path $PSScriptRoot 'run.py'
foreach ($case in @(
    @('--driver', '5', '--mixed', '40'),
    @('--driver', '5', '--mixed', '80'),
    @('--driver', '6', '--mixed', '40'),
    @('--driver', '6', '--mixed', '80'),
    @('--driver', '5', '--mixed', '40', '--control')
)) {
    & $Python -B $runner @case
    if ($LASTEXITCODE -ne 0) { throw "PAGE1 mixed case failed: $($case -join ' ')" }
}
