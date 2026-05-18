# Clio API Orchestrator - LOCAL DEV launcher (talks to Clio Dev)
# App registration: "Clio API Orchestrator - Dev"
#
# Usage:
#   Web API (FastAPI):   .\start_dev.ps1 api
#   React GUI (Vite):    .\start_dev.ps1 ui
#   First-time auth:     visit  http://localhost:8000/api/oauth/login?session=<jwt>
#                        after logging in via POST /api/auth/login.
#                        (Legacy flow:  .\start_dev.ps1 auth  -- uses clio_oauth_app.py)
#   CLI menu / commands: .\start_dev.ps1
#   Direct command:      .\start_dev.ps1 list-matters
#
# Virtual env: py -3.12 -m venv .venv  then  .\.venv\Scripts\pip.exe install -r requirements.txt
# Scripts use .venv\Scripts\python.exe when that folder exists.

$RepoRoot = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

# ── Clio DEV credentials ─────────────────────────────────────────────────────
# These point your LOCAL FastAPI app at Clio Dev. The deployed Azure dev Web
# App has its own copy of these in App Settings -- this script only matters
# when you're iterating on code locally before deploying.
$env:CLIO_CLIENT_ID     = "Eth67c5v4MnKUVQ9o2xnvatr0uEp9p1PvHgRwpdm"
$env:CLIO_CLIENT_SECRET = "IYd7n3BtpUGZ1MSaV6shxJctO1yE7OmTHo8dHlAB"

# Redirect URI matches the new FastAPI OAuth route on uvicorn (port 8000, HTTP).
# This URI must also be registered as an allowed redirect on the Clio Dev app.
$env:CLIO_REDIRECT_URI  = "http://localhost:8000/api/oauth/callback"

# Mark this process as the dev environment so DbTokenStore (if you happen to
# point DATABASE_URL at Azure SQL locally) writes to the env='dev' row.
$env:CLIO_ENV           = "dev"

Set-Location $RepoRoot

if ($args[0] -eq "auth") {
    Write-Host ""
    Write-Host "LEGACY OAuth helper (clio_oauth_app.py on https://localhost:8787)."
    Write-Host "Prefer the new flow:  start the API + visit"
    Write-Host "  http://localhost:8000/api/oauth/login?session=<jwt>"
    Write-Host ""
    # The legacy helper expects its own SSL context for https://localhost:8787.
    $env:CLIO_SSL_CONTEXT = "adhoc"
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
