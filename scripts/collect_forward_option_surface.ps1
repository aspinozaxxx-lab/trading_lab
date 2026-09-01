param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab",
    [string]$OutputRoot = "D:\Projects\trading_lab_data\data\forward\moex-options-surface-v1"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Trading Lab Python is missing: $python"
}

$probeUrl = "https://iss.moex.com/iss/engines/futures/markets/options/securities.json?assets=Si&iss.meta=off&iss.only=marketdata"
$probe = Invoke-RestMethod -Uri $probeUrl -Method Get -TimeoutSec 30 -Headers @{
    "User-Agent" = "market-lab-forward-option-surface-scheduler/1.0"
}
$columns = @($probe.marketdata.columns)
$sourceDateIndex = [Array]::IndexOf($columns, "TRADE_SESSION_DATE")
if ($sourceDateIndex -lt 0) {
    throw "MOEX option probe lacks TRADE_SESSION_DATE"
}
$sourceDates = @(
    $probe.marketdata.data |
        ForEach-Object { $_[$sourceDateIndex] } |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        Sort-Object -Unique
)
if ($sourceDates.Count -ne 1) {
    throw "MOEX option probe must expose exactly one source date"
}
$sourceDate = [string]$sourceDates[0]
if ([datetime]$sourceDate -lt [datetime]"2026-01-01") {
    throw "Forward option source date escaped the forward boundary: $sourceDate"
}

if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
    $manifests = Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter "snapshot_*" |
        ForEach-Object { Join-Path $_.FullName "manifest.json" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    foreach ($manifestPath in $manifests) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if (@($manifest.counts.source_dates) -contains $sourceDate) {
            $snapshotPath = Split-Path -Parent $manifestPath
            $auditOutput = & $python -m market_lab.futures.moex_forward_option_surface_source `
                --audit-directory $snapshotPath
            $auditExitCode = $LASTEXITCODE
            if ($auditExitCode -eq 0) {
                $audit = $auditOutput | Out-String | ConvertFrom-Json
                if ($audit.all_true -eq $true) {
                    Write-Output "SKIP source_date=$sourceDate already captured and audited at $manifestPath"
                    exit 0
                }
            }
            Write-Warning "Existing source_date=$sourceDate failed replay audit; collecting an immutable replacement"
        }
    }
}

Push-Location -LiteralPath $RepositoryRoot
try {
    & $python -m market_lab.futures.moex_forward_option_surface_source `
        --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Forward option collector failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$latest = Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter "snapshot_*" |
    Sort-Object LastWriteTimeUtc |
    Select-Object -Last 1
if ($null -eq $latest) {
    throw "Forward option collector created no snapshot"
}
$latestManifest = Get-Content -LiteralPath (Join-Path $latest.FullName "manifest.json") `
    -Raw -Encoding UTF8 | ConvertFrom-Json
if (@($latestManifest.counts.source_dates) -notcontains $sourceDate) {
    throw "Persisted option snapshot source date does not match the probe"
}
Write-Output "CAPTURED source_date=$sourceDate snapshot=$($latest.FullName)"
