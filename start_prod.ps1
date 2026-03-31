# ── Clio API Orchestrator — PROD Environment ─────────────────────────────────
# App: ClioDataSync - Core - Prod  (APP_ID: 28169)
#
# Usage:
#   First-time auth:  .\start_prod.ps1 auth
#   Run operations:   .\start_prod.ps1
#   Direct command:   .\start_prod.ps1 list-matters
# ─────────────────────────────────────────────────────────────────────────────

$env:CLIO_CLIENT_ID     = "dZEXLoJcal4sU4bY15ibg5mRIMMa1lm30YMnBktA"
$env:CLIO_CLIENT_SECRET = "S38RW2j7SJ6on24TBhiJp4ZBlnFdglxFyX9g07C6"
$env:CLIO_REDIRECT_URI  = "https://localhost:8787/oauth/callback"
$env:CLIO_SSL_CONTEXT   = "adhoc"
$env:CLIO_APP_DOMAIN    = "quillarrow-cliobatchloadingtemplates-e3aadvg3cra9gmhk.westus2-01.azurewebsites.net"

if ($args[0] -eq "auth") {
    Write-Host ""
    Write-Host "Starting OAuth server for PROD environment..."
    Write-Host "Visit https://localhost:8787/login to authorize."
    Write-Host ""
    python clio_oauth_app.py
} else {
    python run.py $args
}
