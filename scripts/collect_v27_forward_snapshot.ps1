param(
    [ValidateSet("decision_eod", "execution_observation")]
    [string]$SnapshotKind,
    [string]$RepositoryRoot = "D:\Projects\trading_lab",
    [string]$OutputRoot = "D:\Projects\trading_lab_data\data\forward\v27-validation-v3-components"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Trading Lab Python is missing: $python"
}

$probeUrl = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json?assets=Si&iss.meta=off&iss.only=marketdata"
$probe = Invoke-RestMethod -Uri $probeUrl -Method Get -TimeoutSec 30 -Headers @{
    "User-Agent" = "market-lab-v27-forward-scheduler/2.0"
}
$columns = @($probe.marketdata.columns)
$tradeDateIndex = [Array]::IndexOf($columns, "TRADEDATE")
if ($tradeDateIndex -lt 0) {
    throw "MOEX V27 probe lacks TRADEDATE"
}
$sourceDates = @(
    $probe.marketdata.data |
        ForEach-Object { $_[$tradeDateIndex] } |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        Sort-Object -Unique
)
if ($sourceDates.Count -ne 1) {
    throw "MOEX V27 probe must expose exactly one source date"
}
$sourceDate = [string]$sourceDates[0]
if ([datetime]$sourceDate -lt [datetime]"2026-09-02") {
    throw "V27 source date escaped the forward seal: $sourceDate"
}

$marketComponent = if ($SnapshotKind -eq "decision_eod") {
    "market_decision"
}
else {
    "market_execution"
}

function Test-ExistingComponent {
    param(
        [string]$Component,
        [bool]$MatchSourceDate
    )
    if (-not (Test-Path -LiteralPath $OutputRoot -PathType Container)) {
        return $false
    }
    $manifests = Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter "snapshot_*" |
        ForEach-Object { Join-Path $_.FullName "manifest.json" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    foreach ($manifestPath in $manifests) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if ([string]$manifest.component -ne $Component) {
            continue
        }
        $identityMatches = if ($MatchSourceDate) {
            @($manifest.source_dates) -contains $sourceDate
        }
        else {
            ([datetimeoffset]$manifest.retrieved_at_utc).UtcDateTime.Date -eq
                ([datetime]$sourceDate).Date
        }
        if (-not $identityMatches) {
            continue
        }
        $snapshotPath = Split-Path -Parent $manifestPath
        $auditOutput = & $python -m `
            market_lab.futures.moex_v27_forward_component_source `
            --audit-directory $snapshotPath
        if ($LASTEXITCODE -eq 0) {
            $audit = $auditOutput | Out-String | ConvertFrom-Json
            if ($audit.all_true -eq $true) {
                Write-Output "SKIP component=$Component source_date=$sourceDate at $manifestPath"
                return $true
            }
        }
        Write-Warning "Existing V27 component failed audit: $manifestPath"
    }
    return $false
}

function Invoke-Component {
    param(
        [string]$Component,
        [bool]$MatchSourceDate,
        [bool]$Required
    )
    if (Test-ExistingComponent -Component $Component -MatchSourceDate $MatchSourceDate) {
        return
    }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $componentOutput = @(
            & $python -m market_lab.futures.moex_v27_forward_component_source `
                --component $Component `
                --output-root $OutputRoot 2>&1
        )
        $componentExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($componentExitCode -ne 0) {
        if ($Required) {
            $detail = $componentOutput | Select-Object -Last 1
            throw "Required V27 component $Component failed ($componentExitCode): $detail"
        }
        $detail = $componentOutput | Select-Object -Last 1
        Write-Warning "Optional V27 component $Component is unavailable: $detail"
        return
    }
    $componentOutput | Write-Output
}

Push-Location -LiteralPath $RepositoryRoot
try {
    Invoke-Component -Component $marketComponent -MatchSourceDate $true -Required $true
    Invoke-Component -Component "macro_cbr" -MatchSourceDate $false -Required $false
    Invoke-Component -Component "macro_fred" -MatchSourceDate $false -Required $false
    & $python -m market_lab.futures.v27_forward_component_readiness `
        --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) {
        throw "V27 component readiness failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
