param(
    [ValidateSet("decision_eod", "execution_observation")]
    [string]$SnapshotKind,
    [string]$RepositoryRoot = "D:\Projects\trading_lab",
    [string]$OutputRoot = "D:\Projects\trading_lab_data\data\forward\v27-validation-v1"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Trading Lab Python is missing: $python"
}

$probeUrl = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json?assets=Si&iss.meta=off&iss.only=marketdata"
$probe = Invoke-RestMethod -Uri $probeUrl -Method Get -TimeoutSec 30 -Headers @{
    "User-Agent" = "market-lab-v27-forward-scheduler/1.0"
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

if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
    $manifests = Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter "snapshot_*" |
        ForEach-Object { Join-Path $_.FullName "manifest.json" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    foreach ($manifestPath in $manifests) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if (
            [string]$manifest.snapshot_kind -eq $SnapshotKind -and
            @($manifest.counts.source_dates) -contains $sourceDate
        ) {
            $snapshotPath = Split-Path -Parent $manifestPath
            $auditOutput = & $python -m `
                market_lab.futures.moex_v27_forward_validation_source `
                --audit-directory $snapshotPath
            if ($LASTEXITCODE -eq 0) {
                $audit = $auditOutput | Out-String | ConvertFrom-Json
                if ($audit.all_true -eq $true) {
                    Write-Output "SKIP kind=$SnapshotKind source_date=$sourceDate at $manifestPath"
                    exit 0
                }
            }
            Write-Warning "Existing V27 snapshot failed audit; collecting replacement"
        }
    }
}

Push-Location -LiteralPath $RepositoryRoot
try {
    & $python -m market_lab.futures.moex_v27_forward_validation_source `
        --snapshot-kind $SnapshotKind `
        --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) {
        throw "V27 forward collector failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
