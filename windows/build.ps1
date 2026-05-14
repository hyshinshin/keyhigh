param(
    [string]$Python = 'python',
    [string]$Name = 'KeyHigh'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .\.venv)) {
    & $Python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller `
  --noconsole `
  --onefile `
  --name $Name `
  --add-data "..\Resources;Resources" `
  keyhigh_windows.py

Write-Host "Built dist\$Name.exe"
