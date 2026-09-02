param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab"
)

$ErrorActionPreference = "Stop"
$collectorScript = Join-Path $RepositoryRoot "scripts\collect_v27_forward_snapshot.ps1"
if (-not (Test-Path -LiteralPath $collectorScript -PathType Leaf)) {
    throw "V27 forward collector wrapper is missing: $collectorScript"
}

function Register-V27Task {
    param(
        [string]$TaskName,
        [string]$SnapshotKind,
        [string]$At,
        [string]$Description
    )
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$collectorScript`" -SnapshotKind $SnapshotKind" `
        -WorkingDirectory $RepositoryRoot
    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
        -At $At
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
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

Register-V27Task `
    -TaskName "TradingLabV27ForwardExecution" `
    -SnapshotKind "execution_observation" `
    -At "10:05" `
    -Description "V27 forward-only next-session open/quote observation plus macro vintage."
Register-V27Task `
    -TaskName "TradingLabV27ForwardDecision" `
    -SnapshotKind "decision_eod" `
    -At "23:45" `
    -Description "V27 forward-only EOD full futures chains plus macro vintage."
