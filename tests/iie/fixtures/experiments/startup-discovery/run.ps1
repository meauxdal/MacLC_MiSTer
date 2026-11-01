param([string]$RunName = 'verified')
$ErrorActionPreference = 'Stop'
if ($RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid run name' }
$task = "local/experiments/startup-discovery/$RunName"
if (Test-Path -LiteralPath $task) { throw "Run directory already exists: $task" }
New-Item -ItemType Directory -Path $task | Out-Null
$source = 'local/hardfiles/Apple-II_100MB.hda'
$before = (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
if ($before -ne '5e6b04f58dcf631748baf655d0f5d398d6ecb6729f42226f00dfd378c15f2e60') {
    throw 'Unexpected source HDA'
}
$rb = 'local/experiments/system-baseline/rb/rb-cli.exe'
$mame = 'C:/Users/Elle/Downloads/mame0289b_x64'
Copy-Item -LiteralPath $source -Destination "$task/autostart.hda"
& $rb cp $source '/IIe Startup' "$task/autostart.hda" '/System 7.1.2/Startup Items/IIe Startup'
if ($LASTEXITCODE) { throw 'Startup copy failed' }
& "$mame/chdman.exe" createhd -i "$task/autostart.hda" -o "$task/autostart.chd" -c none -chs 6403,1,32 -ss 512
if ($LASTEXITCODE) { throw 'CHD conversion failed' }
$previousRun = $env:IIE_DISCOVERY_RUN
try {
    $env:IIE_DISCOVERY_RUN = $task
    $timer = [Diagnostics.Stopwatch]::StartNew()
    & "$mame/mame.exe" maclc -rompath local/experiments/system-baseline/roms -hard "$task/autostart.chd" -ramsize 4M -video none -sound none -nothrottle -seconds_to_run 85 -skip_gameinfo -cfg_directory "$task/cfg" -nvram_directory "$task/nvram" -snapshot_directory "$task/capture" -noreadconfig -nowriteconfig -autoboot_script fixtures/experiments/startup-discovery/trace.lua -autoboot_delay 0 -debug -debugger none -debugscript fixtures/experiments/startup-discovery/debug.cmd *> "$task/mame.log"
    if ($LASTEXITCODE) { throw 'MAME failed' }
    $timer.Stop()
} finally {
    $env:IIE_DISCOVERY_RUN = $previousRun
    $after = (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
    if ($before -ne $after) { throw 'Original HDA changed' }
}
[ordered]@{
    source_sha256_before = $before
    source_sha256_after = $after
    mame_exit_code = 0
    mame_wall_seconds = $timer.Elapsed.TotalSeconds
    emulated_seconds = 85
    run_name = $RunName
} | ConvertTo-Json | Set-Content -LiteralPath "$task/run.json" -Encoding ascii
Write-Output "Original HDA unchanged: $after"
