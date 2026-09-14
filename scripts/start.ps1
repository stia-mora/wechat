param([switch]$Install)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$PythonExe = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
$LogDirectory = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

if (!(Test-Path -LiteralPath '.env')) {
    $config = Get-Content -Raw '.env.example'
    $adminToken = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllText((Join-Path $ProjectRoot '.env'), $config.Replace('replace-with-a-long-random-token', $adminToken))
}
if ($Install) {
    if (!(Test-Path -LiteralPath $PythonExe)) { python -m venv .venv }
    & $PythonExe -X utf8 -m pip install -r backend/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed' }
    if (Test-Path -LiteralPath 'ref/wechat-download-api/requirements.txt') {
        & $PythonExe -X utf8 -m pip install -r ref/wechat-download-api/requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Source dependency installation failed' }
    }
    Push-Location web
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}
if (!(Test-Path -LiteralPath $PythonExe)) { throw 'Run ./scripts/start.ps1 -Install first' }
docker compose up -d db
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL failed to start' }

function Start-OwnedService($Name, $Executable, $Arguments, $Directory, $Port) {
    $pidFile = Join-Path $LogDirectory "$Name.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $saved = Get-Content -Raw $pidFile | ConvertFrom-Json
        $existing = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
        $savedTicks = if ($saved.started_ticks) { [long]$saved.started_ticks } else { ([datetime]$saved.started).ToUniversalTime().Ticks }
        if ($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq $savedTicks) {
            Write-Host "$Name already running"; return
        }
    }
    if ($Port) {
        $connection = New-Object Net.Sockets.TcpClient
        try { $connection.Connect('127.0.0.1', $Port); throw "Port $Port is already in use; leave its process intact and stop it manually if it belongs to this project." }
        catch [Net.Sockets.SocketException] {} finally { $connection.Dispose() }
    }
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LogDirectory "$Name.log") -RedirectStandardError (Join-Path $LogDirectory "$Name-error.log")
    @{id=$process.Id;started_ticks=$process.StartTime.ToUniversalTime().Ticks} | ConvertTo-Json | Set-Content -LiteralPath $pidFile
}

if (Test-Path -LiteralPath 'ref/wechat-download-api/app.py') {
    $env:SITE_URL = 'http://localhost:5500'
    $env:SKIP_BACKGROUND_TASKS = 'true'
    Start-OwnedService 'source' $PythonExe '-X utf8 -m uvicorn service:app --app-dir ../../source_bridge --host 127.0.0.1 --port 5500' (Join-Path $ProjectRoot 'ref/wechat-download-api') 5500
}
Start-OwnedService 'api' $PythonExe '-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8500' (Join-Path $ProjectRoot 'backend') 8500
Start-OwnedService 'worker' $PythonExe '-X utf8 -m app.worker' (Join-Path $ProjectRoot 'backend') 0
Start-OwnedService 'ai-worker' $PythonExe '-X utf8 -m app.worker --mode ai' (Join-Path $ProjectRoot 'backend') 0
$NodeExe = (Get-Command node.exe).Source
Start-OwnedService 'web' $NodeExe 'node_modules/next/dist/bin/next start --hostname 0.0.0.0 --port 3500' (Join-Path $ProjectRoot 'web') 3500
Write-Host 'Website: http://localhost:3500'
Write-Host 'Source login: http://localhost:5500/login.html'
Write-Host 'Admin token is stored in .env; logs are in logs/.'
