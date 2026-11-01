param([string]$RunName = 'replay')
$ErrorActionPreference = 'Stop'
$task = "local/experiments/startup-runtime/$RunName"
if (Test-Path -LiteralPath $task) { throw "Run directory already exists: $task" }
New-Item -ItemType Directory -Path $task | Out-Null
$source = 'local/hardfiles/Apple-II_100MB.hda'
$before = (Get-FileHash -LiteralPath $source).Hash
$rb = 'local/experiments/system-baseline/rb/rb-cli.exe'
$mame = 'C:/Users/Elle/Downloads/mame0289b_x64'
Copy-Item -LiteralPath $source -Destination "$task/autostart.hda"
& $rb cp $source '/IIe Startup' "$task/autostart.hda" '/System 7.1.2/Startup Items/IIe Startup'
if ($LASTEXITCODE) { throw 'Startup copy failed' }
& "$mame/chdman.exe" createhd -i "$task/autostart.hda" -o "$task/autostart.chd" -c none -chs 6403,1,32 -ss 512
if ($LASTEXITCODE) { throw 'CHD conversion failed' }
& "$mame/mame.exe" maclc -rompath local/experiments/system-baseline/roms -hard "$task/autostart.chd" -ramsize 4M -video none -sound none -nothrottle -seconds_to_run 100 -skip_gameinfo -cfg_directory "$task/cfg" -nvram_directory "$task/nvram" -snapshot_directory "$task/capture" -snapname final100 -noreadconfig -nowriteconfig -autoboot_script fixtures/experiments/startup-runtime/launch.lua -autoboot_delay 0 *> "$task/mame.log"
if ($LASTEXITCODE) { throw 'MAME failed' }
$after = (Get-FileHash -LiteralPath $source).Hash
if ($before -ne $after) { throw 'Original HDA changed' }
Write-Output "Original HDA unchanged: $after"
