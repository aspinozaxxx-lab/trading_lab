param(
    [string]$DataRoot = "D:\Projects\trading_lab_data"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$resolvedDataRoot = [System.IO.Path]::GetFullPath($DataRoot)

if ($repositoryRoot -eq $resolvedDataRoot) {
    throw "External data root must be outside the repository."
}

New-Item -ItemType Directory -Path $resolvedDataRoot -Force | Out-Null

foreach ($name in @("data", "runs", "models")) {
    $target = Join-Path $resolvedDataRoot $name
    $link = Join-Path $repositoryRoot $name
    New-Item -ItemType Directory -Path $target -Force | Out-Null

    if (Test-Path -LiteralPath $link) {
        $item = Get-Item -LiteralPath $link -Force
        if ($item.LinkType -ne "Junction" -or $item.Target -notcontains $target) {
            throw "Refusing to replace existing path: $link"
        }
        continue
    }

    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
}

$env:MARKET_LAB_STORAGE_ROOT = $resolvedDataRoot
Write-Host "MARKET_LAB_STORAGE_ROOT=$resolvedDataRoot (current PowerShell process)"

Get-Item -LiteralPath (Join-Path $repositoryRoot "data"), (Join-Path $repositoryRoot "runs"), (Join-Path $repositoryRoot "models") |
    Select-Object FullName, LinkType, Target
