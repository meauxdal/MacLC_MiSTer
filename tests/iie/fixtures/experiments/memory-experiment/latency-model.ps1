param(
    [ValidateRange(1, 1000)][int]$MemoryMHz = 65,
    [ValidateRange(1, 1000)][int]$ServiceTicks = 8,
    [ValidateRange(0, 1000)][int]$ResidualTicks = 8,
    [ValidateRange(0, 1000)][int]$RefreshTicks = 6,
    [ValidateRange(0, 1000)][int]$ParityTicks = 1,
    [ValidateRange(0, 1000)][int]$TurnaroundTicks = 4
)

$ErrorActionPreference = 'Stop'
# Conditional response-time bounds, not an SDRAM controller simulation.
$rows = foreach ($speedMHz in @(1.02, 1.9)) {
    $deadline = [math]::Floor($MemoryMHz / $speedMHz)
    foreach ($adapterTicks in @(4, 12)) {
        foreach ($blackoutTicks in @(0, 8, 16, 32)) {
            foreach ($ahead in @(0, 1, 2, 4, 8)) {
                $latency = $adapterTicks + $ResidualTicks + $RefreshTicks +
                    $blackoutTicks + $ParityTicks + $ServiceTicks +
                    $ahead * ($ServiceTicks + $TurnaroundTicks)
                [pscustomobject]@{
                    card_mhz = $speedMHz
                    adapter_ticks = $adapterTicks
                    blackout_ticks = $blackoutTicks
                    transactions_ahead = $ahead
                    deadline_ticks = $deadline
                    bound_ticks = $latency
                    bound_ns = [math]::Round(1000 * $latency / $MemoryMHz, 3)
                    margin_ticks = $deadline - $latency
                    within_budget = ($latency -le $deadline)
                }
            }
        }
    }
}

if ($PSBoundParameters.Count -eq 0) {
    $fast = @($rows | Where-Object {
        $_.card_mhz -eq 1.9 -and $_.adapter_ticks -eq 4 -and
        $_.blackout_ticks -eq 0 -and $_.transactions_ahead -eq 0
    })
    if ($rows.Count -ne 80 -or $fast.Count -ne 1 -or
        $fast[0].bound_ticks -ne 27 -or $fast[0].deadline_ticks -ne 34 -or
        !$fast[0].within_budget) { throw 'Default bound check failed' }
    if (@($rows | Where-Object {
        $_.card_mhz -eq 1.9 -and $_.adapter_ticks -eq 12 -and $_.within_budget
    }).Count -ne 0) { throw 'Crossing sensitivity check failed' }
}
$rows | ConvertTo-Csv -NoTypeInformation
