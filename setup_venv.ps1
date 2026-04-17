# Recreate .venv with Python 3.12 and install requirements.txt
# Run from repo root:  .\setup_venv.ps1
# Requires: py launcher with 3.12 (py -3.12 --version)

$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

Write-Host "Using:" (py -3.12 -c "import sys; print(sys.executable)")

if (Test-Path ".venv") {
    Write-Host "Removing existing .venv ..."
    Remove-Item -Recurse -Force ".venv"
}

Write-Host "Creating .venv with Python 3.12 ..."
py -3.12 -m venv .venv
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Error "Failed to create .venv. Install Python 3.12 and ensure 'py -3.12' works."
    exit 1
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt

Write-Host ""
Write-Host "Done. This venv is used automatically by start_dev.ps1 / start_prod.ps1."
Write-Host "Next:  .\start_dev.ps1 api   (one terminal)"
Write-Host "       .\start_dev.ps1 ui    (another terminal)"
