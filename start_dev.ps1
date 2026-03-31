# ── Clio API Orchestrator — DEV Environment ──────────────────────────────────
# App: ClioDataSync - Core - Dev  (APP_ID: 26651)
#
# Usage:
#   First-time auth:  .\start_dev.ps1 auth
#   Run operations:   .\start_dev.ps1
#   Direct command:   .\start_dev.ps1 list-matters
# ─────────────────────────────────────────────────────────────────────────────

$env:CLIO_CLIENT_ID     = "w9ciZKnsTZw8Hx1Y1gjT3J149jtamwaGY429NlQ6"
$env:CLIO_CLIENT_SECRET = "yuwhJD1qyqjwKIwO1i17xZyozePCcfr8in6E1UwM"
$env:CLIO_REDIRECT_URI  = "https://quillarrow-cliobatchloadingtemplates-e3aadvg3cra9gmhk.westus2-01.azurewebsites.net/oauth/callback"
$env:CLIO_APP_DOMAIN    = "quillarrow-cliobatchloadingtemplates-e3aadvg3cra9gmhk.westus2-01.azurewebsites.net"

if ($args[0] -eq "auth") {
    Write-Host ""
    Write-Host "Starting OAuth server for DEV environment..."
    Write-Host "Visit https://$($env:CLIO_APP_DOMAIN)/login to authorize."
    Write-Host ""
    python "C:\Users\Tim\OneDrive - quillarrowlaw.com\Documents\ClioData_MassUpdate_Cleanup_MappingSchema\QuillArrow-ClioAPIOrchestrator\clio_oauth_app.py"
} else {
    python "C:\Users\Tim\OneDrive - quillarrowlaw.com\Documents\ClioData_MassUpdate_Cleanup_MappingSchema\QuillArrow-ClioAPIOrchestrator\run.py" $args
}
