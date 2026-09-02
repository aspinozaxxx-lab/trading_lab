param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab"
)

$ErrorActionPreference = "Stop"
$taskService = New-Object -ComObject "Schedule.Service"
$taskService.Connect()
$taskFolder = $taskService.GetFolder("\")
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Register-DelayedBboTask {
    param(
        [string]$TaskName,
        [string]$Wrapper,
        [string]$Description
    )

    $wrapperPath = Join-Path $RepositoryRoot $Wrapper
    if (-not (Test-Path -LiteralPath $wrapperPath -PathType Leaf)) {
        throw "Delayed-BBO wrapper is missing: $wrapperPath"
    }

    $definition = $taskService.NewTask(0)
    $definition.RegistrationInfo.Description = $Description
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
        "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"{0}`"" -f $wrapperPath
    )
    $action.WorkingDirectory = $RepositoryRoot

    $taskFolder.RegisterTaskDefinition(
        $TaskName,
        $definition,
        6,
        $null,
        $null,
        3,
        $null
    ) | Out-Null
}

Register-DelayedBboTask `
    -TaskName "TradingLabForwardCrossMarketBBO10mV2" `
    -Wrapper "scripts\run_forward_cross_market_bbo_v2.ps1" `
    -Description "Trading Lab delayed public ISS cross-market V2 source-only collector."
Register-DelayedBboTask `
    -TaskName "TradingLabForwardBroadStockFuturesCarry10mV2" `
    -Wrapper "scripts\run_forward_broad_stock_futures_carry_v2.ps1" `
    -Description "Trading Lab delayed public ISS broad carry V2 source-only collector."
