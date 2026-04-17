# Clio API Orchestrator - DEV Environment
# App: ClioDataSync - Core - Dev  (APP_ID: 26651)
#
# Usage:
#   First-time auth:     .\start_dev.ps1 auth
#   Web API (FastAPI):   .\start_dev.ps1 api
#   React GUI (Vite):    .\start_dev.ps1 ui
#   CLI menu / commands: .\start_dev.ps1
#   Direct command:      .\start_dev.ps1 list-matters
#
# Virtual env (recommended): py -3.12 -m venv .venv
#   then: .\.venv\Scripts\pip.exe install -r requirements.txt
#   Scripts use .venv\Scripts\python.exe when that folder exists (works in any terminal).

$RepoRoot = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

$env:CLIO_CLIENT_ID     = "w9ciZKnsTZw8Hx1Y1gjT3J149jtamwaGY429NlQ6"
$env:CLIO_CLIENT_SECRET = "yuwhJD1qyqjwKIwO1i17xZyozePCcfr8in6E1UwM"
$env:CLIO_REDIRECT_URI  = "https://localhost:8787/oauth/callback"
$env:CLIO_SSL_CONTEXT   = "adhoc"
$env:CLIO_APP_DOMAIN    = "quillarrow-cliobatchloadingtemplates-e3aadvg3cra9gmhk.westus2-01.azurewebsites.net"

Set-Location $RepoRoot

if ($args[0] -eq "auth") {
    Write-Host ""
    Write-Host "Starting OAuth server for DEV environment..."
    Write-Host "Visit https://localhost:8787/login to authorize."
    Write-Host ""
    & $PythonExe (Join-Path $RepoRoot "clio_oauth_app.py")
} elseif ($args[0] -eq "api") {
    Write-Host ""
    Write-Host "Starting FastAPI backend on http://localhost:8000 (docs: /docs)"
    Write-Host "Keep this window open. In another terminal run: .\start_dev.ps1 ui"
    Write-Host ""
    & $PythonExe -c "import jose, fastapi" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python web stack not installed. From this folder run:"
        Write-Host ('  {0} -m pip install -r requirements.txt' -f $PythonExe)
        Write-Host ""
        exit 1
    }
    & $PythonExe -m uvicorn backend.main:app --reload --port 8000
} elseif ($args[0] -eq "ui") {
    Write-Host ""
    Write-Host "Starting Vite dev server (React frontend)."
    Write-Host "Browser calls to /api are proxied to http://localhost:8000 - start api first."
    Write-Host ""
    Set-Location (Join-Path $RepoRoot "frontend")
    npm run dev
} else {
    & $PythonExe (Join-Path $RepoRoot "run.py") $args
}
