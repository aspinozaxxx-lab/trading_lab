param(
    [string]$TaskName = "TradingLabForwardCnyRelativeValue",
    [string]$RepositoryRoot = "D:\Projects\trading_lab"
)

$ErrorActionPreference = "Stop"
$collectorScript = Join-Path $RepositoryRoot "scripts\collect_forward_cny_relative_value.ps1"
if (-not (Test-Path -LiteralPath $collectorScript -PathType Leaf)) {
    throw "Forward CNY collector wrapper is missing: $collectorScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File `"$collectorScript`"" `
    -WorkingDirectory $RepositoryRoot
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "18:30"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
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
    -Description "Forward-only CNYRUBF and nearest quarterly CR quotes plus prior funding." `
    -Force
