# Rules-first versus model-only comparison on the dev split (Windows PowerShell).
#
# Runs the dev documents twice against a fresh database each time:
#   1. hybrid    - rules first, model when needed (normal operation)
#   2. llm-only  - the model reads every PDF and image
# then puts the normal setting back. Results: evaluation\runs\hybrid-dev and evaluation\runs\llm-only-dev.
#
# Usage, from the project folder:   powershell -ExecutionPolicy Bypass -File evaluation\run_comparison.ps1
# It deletes this project's database and stored files at the start of each run.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$key = (Select-String '^DOCINTEL_API_KEY=' .env).Line.Split('=')[1]

function Set-Mode($mode) {
    $lines = Get-Content .env | Where-Object { $_ -notmatch '^DOCINTEL_EXTRACTION_MODE=' }
    $lines + "DOCINTEL_EXTRACTION_MODE=$mode" | Set-Content .env
}

function Reset-Stack {
    docker compose down -v
    docker compose up -d
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $h = Invoke-RestMethod http://localhost:8000/health -TimeoutSec 5
            if ($h.status -eq "ok") { return }
        } catch { }
        Start-Sleep -Seconds 5
    }
    throw "The API did not become healthy"
}

foreach ($run in @(@{mode = "hybrid"; label = "hybrid-dev"}, @{mode = "llm_only"; label = "llm-only-dev"})) {
    Write-Host "`n=== $($run.label): extraction mode $($run.mode) ===`n"
    Set-Mode $run.mode
    Reset-Stack
    python evaluation\run_eval.py --api http://localhost:8000 --key $key --split dev --label $run.label
}

Set-Mode "hybrid"
docker compose up -d
Write-Host "`nDone. Results are in evaluation\runs\hybrid-dev and evaluation\runs\llm-only-dev."
