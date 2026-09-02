param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab",
    [string]$OutputRoot = "D:\Projects\trading_lab_data\data\forward\moex-cny-relative-value-v1"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Trading Lab Python is missing: $python"
}

$probeUrl = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json?assets=CNYRUBTOM&iss.meta=off&iss.only=marketdata"
$probe = Invoke-RestMethod -Uri $probeUrl -Method Get -TimeoutSec 30 -Headers @{
    "User-Agent" = "market-lab-forward-cny-relative-value-scheduler/1.0"
}
$columns = @($probe.marketdata.columns)
$secidIndex = [Array]::IndexOf($columns, "SECID")
$tradeDateIndex = [Array]::IndexOf($columns, "TRADEDATE")
if ($secidIndex -lt 0 -or $tradeDateIndex -lt 0) {
    throw "MOEX forward CNY probe lacks SECID or TRADEDATE"
}
$sourceDates = @(
    $probe.marketdata.data |
        Where-Object { [string]$_[$secidIndex] -eq "CNYRUBF" } |
        ForEach-Object { $_[$tradeDateIndex] } |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        Sort-Object -Unique
)
if ($sourceDates.Count -ne 1) {
    throw "MOEX forward CNY probe must expose exactly one CNYRUBF quote date"
}
$sourceDate = [string]$sourceDates[0]
if ([datetime]$sourceDate -lt [datetime]"2026-09-02") {
    throw "Forward CNY source date escaped the seal: $sourceDate"
}

if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
    $manifests = Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter "snapshot_*" |
        ForEach-Object { Join-Path $_.FullName "manifest.json" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    foreach ($manifestPath in $manifests) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if (@($manifest.counts.quote_dates) -contains $sourceDate) {
            $snapshotPath = Split-Path -Parent $manifestPath
            $auditOutput = & $python -m `
                market_lab.futures.moex_forward_cny_relative_value_source `
                --audit-directory $snapshotPath
            if ($LASTEXITCODE -eq 0) {
                $audit = $auditOutput | Out-String | ConvertFrom-Json
                if ($audit.all_true -eq $true) {
                    Write-Output "SKIP quote_date=$sourceDate already captured at $manifestPath"
                    exit 0
                }
            }
            Write-Warning "Existing quote_date=$sourceDate failed audit; collecting replacement"
        }
    }
}

Push-Location -LiteralPath $RepositoryRoot
try {
    & $python -m market_lab.futures.moex_forward_cny_relative_value_source `
        --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Forward CNY collector failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$snapshots = Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter "snapshot_*" |
    Sort-Object LastWriteTimeUtc
$latest = $snapshots | Select-Object -Last 1
if ($null -eq $latest) {
    throw "Forward CNY collector created no snapshot"
}
$latestManifest = Get-Content -LiteralPath (Join-Path $latest.FullName "manifest.json") `
    -Raw -Encoding UTF8 | ConvertFrom-Json
$quoteDates = @($latestManifest.counts.quote_dates)
if ($quoteDates.Count -ne 1 -or [datetime]$quoteDates[0] -lt [datetime]"2026-09-02") {
    throw "Persisted forward CNY quote date is outside the sealed interval"
}

$sameDate = @()
foreach ($snapshot in $snapshots) {
    $manifestPath = Join-Path $snapshot.FullName "manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        continue
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($manifest.counts.quote_dates) -contains [string]$quoteDates[0]) {
        $sameDate += $snapshot
    }
}
if ($sameDate.Count -gt 1) {
    throw "Duplicate forward CNY quote date captured: $($quoteDates[0])"
}
Write-Output "CAPTURED quote_date=$($quoteDates[0]) snapshot=$($latest.FullName)"
