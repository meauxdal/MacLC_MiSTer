param(
    [string]$Python = 'C:/Users/Elle/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
    [string]$Unidasm = 'C:/Users/Elle/Downloads/mame0289b_x64/unidasm.exe'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
$work = "$repo/local/experiments/firmware-memory"
New-Item -ItemType Directory -Force $work | Out-Null
if (!(Test-Path "$work/rb/rb-cli.exe")) {
    Expand-Archive -LiteralPath "$repo/local/rb/rb-cli-windows-x64-2026-10-11-23-59.zip" -DestinationPath "$work/rb"
}
$rb = "$work/rb/rb-cli.exe"
if (!(Test-Path "$work/v221/Apple IIe Card 2.2.1.image")) {
    & $rb archive extract "$repo/local/software/Apple-IIe-Card-221-image.sit" "$work/v221" --format raw
    if ($LASTEXITCODE) { throw 'Disk extraction failed' }
}
if (!(Test-Path "$work/app221/IIe Startup.rsrc")) {
    & $rb get-binhex "$work/v221/Apple IIe Card 2.2.1.image" '/IIe Startup' "$work/Startup221.hqx"
    if ($LASTEXITCODE) { throw 'Fork export failed' }
    & $rb archive extract "$work/Startup221.hqx" "$work/app221" --format raw
    if ($LASTEXITCODE) { throw 'Application extraction failed' }
}
& $Python "$repo/fixtures/research/software-bringup/inspect_resources.py" "$work/app221/IIe Startup.rsrc" --json "$work/resources.json" --export "$work/code"
if ($LASTEXITCODE) { throw 'Resource inspection failed' }
& $Python "$PSScriptRoot/inspect_firmware.py" "$work/app221/IIe Startup.rsrc" --json "$PSScriptRoot/metadata.json" --export "$work/decoded"
if ($LASTEXITCODE) { throw 'Firmware inspection failed' }
foreach ($segment in @(1, 5, 6, 7)) {
    & $Unidasm "$work/code/CODE_$segment.bin" -arch m68020 -skip 4 -basepc 4 | Set-Content "$work/CODE_$segment.txt"
    if ($LASTEXITCODE) { throw 'Disassembly failed' }
}
& $Unidasm "$work/code/Conf_1000.bin" -arch m68020 | Set-Content "$work/Conf_1000.txt"
if ($LASTEXITCODE) { throw 'Diagnostic host disassembly failed' }
& $Unidasm "$work/decoded/Conf_1001.payload.bin" -arch w65c02 -basepc 0x2000 | Set-Content "$work/diagnostic.txt"
if ($LASTEXITCODE) { throw 'Diagnostic disassembly failed' }
& $Unidasm "$work/decoded/Monx_2606.payload.bin" -arch w65c02 -skip 0x3a62 -basepc 0xfa62 -count 128 | Set-Content "$work/reset.txt"
if ($LASTEXITCODE) { throw 'Reset disassembly failed' }
