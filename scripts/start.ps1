param([switch]$Dev, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
if (!(Test-Path '.venv/Scripts/python.exe')) { throw 'Create .venv and install backend/requirements.txt first. See README.md.' }
if (!$Dev -and !(Test-Path 'frontend/dist/index.html')) { throw 'Build the frontend first: pnpm --dir frontend install; pnpm --dir frontend build' }
& '.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
