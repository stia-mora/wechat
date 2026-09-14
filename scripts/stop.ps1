$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
foreach ($Name in @('web','worker','api','source')) {
    $pidFile = Join-Path $ProjectRoot "logs/$Name.pid"
    if (!(Test-Path -LiteralPath $pidFile)) { continue }
    $saved = Get-Content -Raw $pidFile | ConvertFrom-Json
    $process = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $saved.started) {
        Stop-Process -Id $process.Id
        Write-Host "Stopped $Name"
    }
}
Write-Host 'PostgreSQL data is retained. Use docker compose stop db if needed.'
