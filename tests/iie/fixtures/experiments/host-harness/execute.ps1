param([string]$RunName = 'verified', [switch]$DiagnosticBridge, [switch]$RTLBridge, [switch]$IRQBridge)
$ErrorActionPreference = 'Stop'
if ($IRQBridge) { $RTLBridge = $true }
$rtlExecutable = if ($IRQBridge) { 'local/experiments/card-irq-service/service.vvp' } else { 'local/experiments/card-rtl-service/service.vvp' }
if ($RTLBridge) {
    $DiagnosticBridge = $true
    if (!(Test-Path -LiteralPath $rtlExecutable)) { throw 'Prepare the RTL service first' }
}
if ($RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid run name' }
$task = "local/experiments/host-execution/$RunName"
if (Test-Path -LiteralPath $task) { throw "Run directory already exists: $task" }
New-Item -ItemType Directory -Path $task | Out-Null
$source = 'local/hardfiles/Apple-II_100MB.hda'
$before = (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
if ($before -ne '5e6b04f58dcf631748baf655d0f5d398d6ecb6729f42226f00dfd378c15f2e60') {
    throw 'Unexpected source HDA'
}
$rb = 'local/experiments/system-baseline/rb/rb-cli.exe'
$mame = 'C:/Users/Elle/Downloads/mame0289b_x64'
$romHash = (Get-FileHash -LiteralPath 'local/experiments/system-baseline/roms/maclc/350eacf0.rom').Hash.ToLowerInvariant()
if ($romHash -ne '129391cc72f84c2b321709cad8281e30a45e50b3cf6e7afe7434c4d32c7b9d5b') { throw 'Unexpected LC ROM' }
Copy-Item -LiteralPath $source -Destination "$task/autostart.hda"
& $rb cp $source '/IIe Startup' "$task/autostart.hda" '/System 7.1.2/Startup Items/IIe Startup'
if ($LASTEXITCODE) { throw 'Startup copy failed' }
& "$mame/chdman.exe" createhd -i "$task/autostart.hda" -o "$task/autostart.chd" -c none -chs 6403,1,32 -ss 512
if ($LASTEXITCODE) { throw 'CHD conversion failed' }
$previousRun = $env:IIE_EXEC_RUN
$previousDiscoveryRun = $env:IIE_DISCOVERY_RUN
$previousBridge = $env:IIE_DIAGNOSTIC_BRIDGE
$service = $null
try {
    $env:IIE_EXEC_RUN = $task
    $env:IIE_DISCOVERY_RUN = $task
    if ($DiagnosticBridge) {
        $py = 'C:/Users/Elle/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
        $env:IIE_DIAGNOSTIC_BRIDGE = '1'
        $server = if ($RTLBridge) { 'rtl_bridge_server.py' } else { 'bridge_server.py' }
        $serverArgs = @('-B', "fixtures/experiments/host-harness/$server", '--run', $task)
        if ($RTLBridge) { $serverArgs += @('--executable', $rtlExecutable) }
        $service = Start-Process -FilePath $py -ArgumentList $serverArgs -WindowStyle Hidden -PassThru
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        while (!(Test-Path -LiteralPath "$task/server.ready")) {
            if ($service.HasExited -or [DateTime]::UtcNow -gt $deadline) { throw 'Diagnostic bridge did not start' }
            Start-Sleep -Milliseconds 25
        }
    } else {
        $env:IIE_DIAGNOSTIC_BRIDGE = $null
    }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    & "$mame/mame.exe" maclc -rompath local/experiments/system-baseline/roms -hard "$task/autostart.chd" -ramsize 4M -video none -sound none -nothrottle -seconds_to_run 85 -skip_gameinfo -cfg_directory "$task/cfg" -nvram_directory "$task/nvram" -snapshot_directory "$task/capture" -noreadconfig -nowriteconfig -autoboot_script fixtures/experiments/host-harness/execute.lua -autoboot_delay 0 -debug -debugger none -debugscript fixtures/experiments/startup-discovery/debug.cmd *> "$task/mame.log"
    if ($LASTEXITCODE) { throw 'MAME failed' }
    $timer.Stop()
} finally {
    if ($service) {
        Set-Content -LiteralPath "$task/server.stop" -Value 'stop' -Encoding ascii
        if (!$service.WaitForExit(3000)) { $service.Kill() }
    }
    $env:IIE_EXEC_RUN = $previousRun
    $env:IIE_DISCOVERY_RUN = $previousDiscoveryRun
    $env:IIE_DIAGNOSTIC_BRIDGE = $previousBridge
    $after = (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
    if ($before -ne $after) { throw 'Original HDA changed' }
}
[ordered]@{
    source_sha256_before = $before
    source_sha256_after = $after
    mame_exit_code = 0
    mame_wall_seconds = $timer.Elapsed.TotalSeconds
    emulated_seconds_limit = 85
    run_name = $RunName
    diagnostic_bridge = [bool]$DiagnosticBridge
    rtl_bridge = [bool]$RTLBridge
    irq_bridge = [bool]$IRQBridge
} | ConvertTo-Json | Set-Content -LiteralPath "$task/run.json" -Encoding ascii
Write-Output "Original HDA unchanged: $after"


