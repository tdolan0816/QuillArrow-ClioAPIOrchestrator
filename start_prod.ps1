# Clio API Orchestrator - LOCAL PROD launcher (talks to Clio PRODUCTION)
# App registration: "Clio API Orchestrator - Prod"
#
# *** READ THIS BEFORE RUNNING ***
# Production is hosted on Azure -- a separate Web App keeps it running 24/7
# without this script. You almost never need to run prod from your laptop.
#
# Legitimate reasons to use this script:
#   - One-off CLI scripts (.\start_prod.ps1 list-matters) that need prod data.
#   - Last-resort debugging when the Azure Prod Web App is misbehaving.
#
# Do NOT use this for routine local development -- use start_dev.ps1.
# A wrong click here can mutate real Clio Production matters.
#
# To proceed, pass -Force as the second argument, e.g.:
#   .\start_prod.ps1 api -Force
#   .\start_prod.ps1 list-matters -Force

param(
    [Parameter(Position = 0)] [string] $Mode,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)] [string[]] $Rest
)

$RepoRoot = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

# ── Safety gate ──────────────────────────────────────────────────────────────
$forceFlag = ($Rest -contains "-Force") -or ($Rest -contains "--force")
if (-not $forceFlag) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host " start_prod.ps1 wires your LOCAL machine to Clio PRODUCTION " -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Production normally runs in Azure -- you do not need this script"
    Write-Host "to keep the prod Web App alive. For day-to-day coding, use"
    Write-Host "  .\start_dev.ps1 api   and   .\start_dev.ps1 ui"
    Write-Host ""
    Write-Host "If you really need to run locally against Clio Prod, append -Force:"
    Write-Host "  .\start_prod.ps1 $Mode -Force"
    Write-Host ""
    exit 1
}

# ── Clio PROD credentials (only loaded after -Force) ─────────────────────────
$env:CLIO_CLIENT_ID     = "hUN65hCoCcJVMcCdpjVShJBPqWhwAjGpRCA75vzi"
$env:CLIO_CLIENT_SECRET = "payho6jN1Ed4VDhKFXRh3RB2kNmqTSQL4zK6QvIi"

# Redirect URI for the new FastAPI OAuth route. Note: registering a localhost
# URI on the Clio PROD app is generally discouraged. Only do so temporarily if
# you need to re-authorize Clio Prod from a local FastAPI instance.
$env:CLIO_REDIRECT_URI  = "http://localhost:8000/api/oauth/callback"

$env:CLIO_ENV           = "prod"

Set-Location $RepoRoot

if ($Mode -eq "auth") {
    Write-Host ""
    Write-Host "[PROD] LEGACY OAuth helper (clio_oauth_app.py on https://localhost:8787)."
    Write-Host "Prefer the new flow:  start the API + visit"
    Write-Host "  http://localhost:8000/api/oauth/login?session=<jwt>"
    Write-Host ""
    $env:CLIO_SSL_CONTEXT = "adhoc"
    & $PythonExe (Join-Path $RepoRoot "clio_oauth_app.py")
} elseif ($Mode -eq "api") {
    Write-Host ""
    Write-Host "[PROD] FastAPI backend on http://localhost:8000 -- talking to Clio PRODUCTION."
    Write-Host ""
    & $PythonExe -c "import jose, fastapi" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python web stack not installed. From this folder run:"
        Write-Host ('  {0} -m pip install -r requirements.txt' -f $PythonExe)
        Write-Host ""
        exit 1
    }
    & $PythonExe -m uvicorn backend.main:app --reload --port 8000
} elseif ($Mode -eq "ui") {
    Write-Host ""
    Write-Host "[PROD] Vite dev server. Start  .\start_prod.ps1 api -Force  in another terminal first."
    Write-Host ""
    Set-Location (Join-Path $RepoRoot "frontend")
    npm run dev
} else {
    # Filter -Force out of the remaining args before forwarding to run.py.
    $cliArgs = @($Mode) + ($Rest | Where-Object { $_ -ne "-Force" -and $_ -ne "--force" })
    & $PythonExe (Join-Path $RepoRoot "run.py") $cliArgs
}
