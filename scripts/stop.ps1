$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
foreach ($Name in @('web','worker','ai-worker','api','source')) {
    $pidFile = Join-Path $ProjectRoot "logs/$Name.pid"
    if (!(Test-Path -LiteralPath $pidFile)) { continue }
    $saved = Get-Content -Raw $pidFile | ConvertFrom-Json
    $process = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
    $savedTicks = if ($saved.started_ticks) { [long]$saved.started_ticks } else { ([datetime]$saved.started).ToUniversalTime().Ticks }
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq $savedTicks) {
        # Python's Windows venv launcher may own a child interpreter; stop the owned tree.
        taskkill.exe /PID $process.Id /T /F | Out-Null
        Write-Host "Stopped $Name"
    }
}
Write-Host 'PostgreSQL data is retained. Use docker compose stop db if needed.'
