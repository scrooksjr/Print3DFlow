param([int]$Port = 8766)
$ErrorActionPreference = 'Stop'
$demoRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $demoRoot
if (!(Test-Path 'frontend/dist/index.html')) { throw 'Build the frontend before starting a demo.' }
$demoDirectory = & '.venv/Scripts/python.exe' -m scripts.prepare_demo
if ($LASTEXITCODE -ne 0) { throw 'Demo preparation failed. Keep the main app on port 8765 running with shop rates configured.' }
$previousDataDir = $env:DATA_DIR
$previousDatabase = $env:DATABASE_URL
try {
    $env:DATA_DIR = $demoDirectory.Trim()
    $env:DATABASE_URL = 'sqlite:///' + (Join-Path $env:DATA_DIR 'shop.db').Replace('\','/')
    Write-Host "Fresh rehearsal: http://127.0.0.1:$Port"
    Write-Host "Paste this prompt from: $(Join-Path $env:DATA_DIR 'intake-prompt.txt')"
    Write-Host 'Ctrl+C stops this rehearsal. Run the script again for a fresh session.'
    & '.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
}
finally {
    $env:DATA_DIR = $previousDataDir
    $env:DATABASE_URL = $previousDatabase
}
