param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab"
)

$ErrorActionPreference = "Stop"
$collector = Join-Path $RepositoryRoot "scripts\collect_forward_lqdt_idle_cash.ps1"
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw "Forward LQDT wrapper is missing: $collector"
}

function Register-LqdtTask {
    param(
        [string]$TaskName,
        [string]$Stage,
        [string]$At,
        [string]$Description
    )
    $timeParts = $At.Split(":")
    if ($timeParts.Count -ne 2) {
        throw "Scheduled time must be HH:mm: $At"
    }
    $triggerTime = [datetime]::Today.AddHours([int]$timeParts[0]).AddMinutes(
        [int]$timeParts[1]
    )
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$collector`" -Stage $Stage" `
        -WorkingDirectory $RepositoryRoot
    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At $triggerTime
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $Description `
        -Force
}

Register-LqdtTask `
    -TaskName "TradingLabForwardLqdtDecision" `
    -Stage "decision" `
    -At "15:49" `
    -Description "Forward-only LQDT liquidation BID/OFFER after the cash-carry decision."
Register-LqdtTask `
    -TaskName "TradingLabForwardLqdtFill" `
    -Stage "fill" `
    -At "15:59" `
    -Description "Forward-only following LQDT BID/OFFER and settlement observation."
