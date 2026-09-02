param(
    [string]$RepositoryRoot = "D:\Projects\trading_lab",
    [string]$OutputRoot = "D:\Projects\trading_lab_data\data\forward\moex-rms-risk-cashflow-v2"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Trading Lab Python is missing: $python"
}

$probeUrl = "https://iss.moex.com/iss/rms/engines/futures/objects/staticparams.json?iss.meta=off&start=0"
$probe = Invoke-RestMethod -Uri $probeUrl -Method Get -TimeoutSec 30 -Headers @{
    "User-Agent" = "market-lab-forward-rms-scheduler/2.0"
}
$columns = @($probe.staticparams.columns)
$tradeDateIndex = [Array]::IndexOf($columns, "tradedate")
if ($tradeDateIndex -lt 0) {
    throw "MOEX RMS probe lacks tradedate"
}
$sourceDates = @(
    $probe.staticparams.data |
        ForEach-Object { $_[$tradeDateIndex] } |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        Sort-Object -Unique
)
if ($sourceDates.Count -ne 1) {
    throw "MOEX RMS probe must expose exactly one risk source date"
}
$sourceDate = [string]$sourceDates[0]
if ([datetime]$sourceDate -lt [datetime]"2026-09-02") {
    throw "MOEX RMS risk source date escaped V2 seal: $sourceDate"
}

if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
    $manifests = Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter "snapshot_*" |
        ForEach-Object { Join-Path $_.FullName "manifest.json" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    foreach ($manifestPath in $manifests) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if ([string]$manifest.risk_source_date -eq $sourceDate) {
            $snapshotPath = Split-Path -Parent $manifestPath
            $auditOutput = & $python -m `
                market_lab.futures.moex_forward_rms_source_v2 `
                --audit-directory $snapshotPath
            if ($LASTEXITCODE -eq 0) {
                $audit = $auditOutput | Out-String | ConvertFrom-Json
                if ($audit.all_true -eq $true) {
                    Write-Output "SKIP risk_source_date=$sourceDate at $manifestPath"
                    exit 0
                }
            }
            Write-Warning "Existing MOEX RMS snapshot failed audit; collecting replacement"
        }
    }
}

Push-Location -LiteralPath $RepositoryRoot
try {
    & $python -m market_lab.futures.moex_forward_rms_source_v2 `
        --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) {
        throw "MOEX RMS collector failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
