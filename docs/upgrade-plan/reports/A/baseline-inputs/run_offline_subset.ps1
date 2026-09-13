# Thin wrapper. Run from repo root. Does not modify skillforge/ or product tests.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..\..")
Set-Location $root
$nodeids = Get-Content (Join-Path $PSScriptRoot "offline-nodeids.txt") | Where-Object { $_.Trim() -ne "" }
python -m pytest -v --tb=short --no-header @nodeids
