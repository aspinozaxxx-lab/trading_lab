param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("decision", "fill")]
    [string]$Stage,
    [string]$RepositoryRoot = "D:\Projects\trading_lab",
    [string]$OutputRoot = "D:\Projects\trading_lab_data\data\forward\moex-lqdt-idle-cash-v1"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Trading Lab Python is missing: $python"
}

$moscowZone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Russian Standard Time")
$moscowNow = [System.TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $moscowZone)
$sourceDate = $moscowNow.ToString("yyyyMMdd")
$snapshot = Join-Path $OutputRoot "snapshot_${sourceDate}_${Stage}"
if (Test-Path -LiteralPath $snapshot -PathType Container) {
    Push-Location -LiteralPath $RepositoryRoot
    try {
        $auditOutput = & $python -m `
            market_lab.futures.moex_forward_lqdt_idle_cash_source `
            --audit-directory $snapshot
        if ($LASTEXITCODE -ne 0) {
            throw "Existing forward LQDT snapshot audit process failed"
        }
        $audit = $auditOutput | Out-String | ConvertFrom-Json
        if ($audit.all_true -ne $true) {
            throw "Existing immutable forward LQDT snapshot failed audit: $snapshot"
        }
        Write-Output "SKIP source_date=$sourceDate stage=$Stage snapshot=$snapshot"
        exit 0
    }
    finally {
        Pop-Location
    }
}

Push-Location -LiteralPath $RepositoryRoot
try {
    & $python -m market_lab.futures.moex_forward_lqdt_idle_cash_source `
        --stage $Stage `
        --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Forward LQDT collector failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $snapshot -PathType Container)) {
    throw "Forward LQDT collector created no expected snapshot: $snapshot"
}
Write-Output "CAPTURED source_date=$sourceDate stage=$Stage snapshot=$snapshot"
