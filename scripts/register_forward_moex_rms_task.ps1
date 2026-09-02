param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab"
)

$ErrorActionPreference = "Stop"
$collector = Join-Path $RepositoryRoot "scripts\collect_forward_moex_rms.ps1"
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw "MOEX RMS collector wrapper is missing: $collector"
}
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File `"$collector`"" `
    -WorkingDirectory $RepositoryRoot
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "23:35"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
Register-ScheduledTask `
    -TaskName "TradingLabForwardMoexRms" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Forward-only MOEX RMS risk parameters and anticipated cashflows." `
    -Force
