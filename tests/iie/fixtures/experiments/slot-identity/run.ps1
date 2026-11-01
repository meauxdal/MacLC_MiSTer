param([string]$RunName = 'verified')
$ErrorActionPreference = 'Stop'
if ($RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid run name' }
$task = "local/experiments/slot-identity/$RunName"
if (Test-Path -LiteralPath $task) { throw "Run directory already exists: $task" }
New-Item -ItemType Directory -Path $task | Out-Null
$source = 'local/hardfiles/Apple-II_100MB.hda'
$before = (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
if ($before -ne '5e6b04f58dcf631748baf655d0f5d398d6ecb6729f42226f00dfd378c15f2e60') { throw 'Unexpected source HDA' }
$mame = 'C:/Users/Elle/Downloads/mame0289b_x64'
$romHash = (Get-FileHash -LiteralPath 'local/experiments/system-baseline/roms/maclc/350eacf0.rom').Hash.ToLowerInvariant()
if ($romHash -ne '129391cc72f84c2b321709cad8281e30a45e50b3cf6e7afe7434c4d32c7b9d5b') { throw 'Unexpected LC ROM' }
& "$mame/chdman.exe" createhd -i $source -o "$task/disk.chd" -c none -chs 6403,1,32 -ss 512
if ($LASTEXITCODE) { throw 'CHD conversion failed' }
$previousRun = $env:IIE_SLOT_RUN
try {
    $env:IIE_SLOT_RUN = $task
    $timer = [Diagnostics.Stopwatch]::StartNew()
    & "$mame/mame.exe" maclc -rompath local/experiments/system-baseline/roms -hard "$task/disk.chd" -ramsize 4M -video none -sound none -nothrottle -seconds_to_run 20 -skip_gameinfo -cfg_directory "$task/cfg" -nvram_directory "$task/nvram" -noreadconfig -nowriteconfig -autoboot_script fixtures/experiments/slot-identity/trace.lua -autoboot_delay 0 -debug -debugger none -debugscript fixtures/experiments/slot-identity/debug.cmd *> "$task/mame.log"
    if ($LASTEXITCODE) { throw 'MAME failed' }
    $timer.Stop()
} finally {
    $env:IIE_SLOT_RUN = $previousRun
    $after = (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
    if ($before -ne $after) { throw 'Original HDA changed' }
}
[ordered]@{
    source_sha256_before = $before
    source_sha256_after = $after
    mame_exit_code = 0
    mame_wall_seconds = $timer.Elapsed.TotalSeconds
    emulated_seconds = 20
    run_name = $RunName
} | ConvertTo-Json | Set-Content -LiteralPath "$task/run.json" -Encoding ascii
Write-Output "Original HDA unchanged: $after"
