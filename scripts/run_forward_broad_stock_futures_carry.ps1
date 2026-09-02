$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $repositoryRoot '.venv\Scripts\python.exe'

Set-Location -LiteralPath $repositoryRoot
& $pythonExecutable -m market_lab.futures.moex_forward_broad_stock_futures_carry_source
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
