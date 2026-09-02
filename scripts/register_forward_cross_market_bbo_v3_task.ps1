param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab"
)

$ErrorActionPreference = "Stop"
$taskName = "TradingLabForwardCrossMarketBBO10mV3"
$wrapperPath = Join-Path $RepositoryRoot "scripts\run_forward_cross_market_bbo_v3.ps1"
if (-not (Test-Path -LiteralPath $wrapperPath -PathType Leaf)) {
    throw "Cross-market V3 wrapper is missing: $wrapperPath"
}

$taskService = New-Object -ComObject "Schedule.Service"
$taskService.Connect()
$taskFolder = $taskService.GetFolder("\")
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$definition = $taskService.NewTask(0)
$definition.RegistrationInfo.Description = (
    "Trading Lab delayed public ISS cross-market V3 CNY-perpetual source-only collector."
)
$definition.Principal.UserId = $currentUser
$definition.Principal.LogonType = 3
$definition.Principal.RunLevel = 0
$definition.Settings.DisallowStartIfOnBatteries = $true
$definition.Settings.StopIfGoingOnBatteries = $true
$definition.Settings.StartWhenAvailable = $true
$definition.Settings.ExecutionTimeLimit = "PT5M"
$definition.Settings.MultipleInstances = 2
$definition.Settings.UseUnifiedSchedulingEngine = $true

$trigger = $definition.Triggers.Create(3)
$trigger.StartBoundary = [datetime]::Today.AddHours(10).AddMinutes(9).ToString(
    "yyyy-MM-dd'T'HH:mm:ssK"
)
$trigger.WeeksInterval = 1
$trigger.DaysOfWeek = 62
$trigger.Repetition.Interval = "PT10M"
$trigger.Repetition.Duration = "PT8H31M"
$trigger.Repetition.StopAtDurationEnd = $true

$action = $definition.Actions.Create(0)
$action.Path = "powershell.exe"
$action.Arguments = (
    "-NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File `"{0}`"" -f $wrapperPath
)
$action.WorkingDirectory = $RepositoryRoot

$taskFolder.RegisterTaskDefinition(
    $taskName,
    $definition,
    6,
    $null,
    $null,
    3,
    $null
) | Out-Null

$oldTask = $taskFolder.GetTask("TradingLabForwardCrossMarketBBO10mV2")
$oldTask.Enabled = $false
