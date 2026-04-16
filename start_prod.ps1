# ── Clio API Orchestrator — PROD Environment ─────────────────────────────────
# App: ClioDataSync - Core - Prod  (APP_ID: 28169)
#
# Usage:
#   First-time auth:     .\start_prod.ps1 auth
#   Web API (FastAPI):   .\start_prod.ps1 api
#   React GUI (Vite):    .\start_prod.ps1 ui
#   CLI menu / commands: .\start_prod.ps1
#   Direct command:      .\start_prod.ps1 list-matters
# ─────────────────────────────────────────────────────────────────────────────

$RepoRoot = $PSScriptRoot

$env:CLIO_CLIENT_ID     = "dZEXLoJcal4sU4bY15ibg5mRIMMa1lm30YMnBktA"
$env:CLIO_CLIENT_SECRET = "S38RW2j7SJ6on24TBhiJp4ZBlnFdglxFyX9g07C6"
$env:CLIO_REDIRECT_URI  = "https://localhost:8787/oauth/callback"
$env:CLIO_SSL_CONTEXT   = "adhoc"
$env:CLIO_APP_DOMAIN    = "quillarrow-cliobatchloadingtemplates-e3aadvg3cra9gmhk.westus2-01.azurewebsites.net"

Set-Location $RepoRoot

if ($args[0] -eq "auth") {
    Write-Host ""
    Write-Host "Starting OAuth server for PROD environment..."
    Write-Host "Visit https://localhost:8787/login to authorize."
    Write-Host ""
    python (Join-Path $RepoRoot "clio_oauth_app.py")
} elseif ($args[0] -eq "api") {
    Write-Host ""
    Write-Host "Starting FastAPI backend on http://localhost:8000 (docs: /docs)"
    Write-Host ""
    python -m uvicorn backend.main:app --reload --port 8000
} elseif ($args[0] -eq "ui") {
    Write-Host ""
    Write-Host "Starting Vite dev server (React). Start .\start_prod.ps1 api in another terminal first."
    Write-Host ""
    Set-Location (Join-Path $RepoRoot "frontend")
    npm run dev
} else {
    python (Join-Path $RepoRoot "run.py") $args
}
