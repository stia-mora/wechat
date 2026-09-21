param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$upstreamRoot = Join-Path $projectRoot 'ref\wechat-download-api'
$sourceData = Join-Path $upstreamRoot 'data'
$sourceEnv = Join-Path $upstreamRoot '.env'

foreach ($requiredPath in @(
    (Join-Path $projectRoot '.env'),
    (Join-Path $projectRoot 'data'),
    $sourceData,
    $sourceEnv
)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required migration input is missing: $requiredPath"
    }
}

$dbContainer = (docker compose -f (Join-Path $projectRoot 'compose.yaml') ps -q db).Trim()
if (-not $dbContainer) {
    throw 'The local PostgreSQL container must be running before migration.'
}

$absoluteOutput = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $absoluteOutput
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    throw "Output directory does not exist: $outputDirectory"
}
if (Test-Path -LiteralPath $absoluteOutput) {
    throw "Refusing to overwrite an existing migration archive: $absoluteOutput"
}

$stagingDirectory = Join-Path $env:TEMP ("wechat-migration-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stagingDirectory | Out-Null

try {
    $dumpInContainer = '/tmp/wechat-source.dump'
    docker exec $dbContainer pg_dump -U wechat -d wechat_source --format=custom --file=$dumpInContainer
    if ($LASTEXITCODE -ne 0) {
        throw 'PostgreSQL dump failed.'
    }

    $migrationDirectory = Join-Path $stagingDirectory 'migration'
    New-Item -ItemType Directory -Path $migrationDirectory | Out-Null
    docker cp "${dbContainer}:$dumpInContainer" (Join-Path $migrationDirectory 'postgres.dump')
    if ($LASTEXITCODE -ne 0) {
        throw 'Copying the PostgreSQL dump from Docker failed.'
    }

    Copy-Item -LiteralPath (Join-Path $projectRoot '.env') -Destination (Join-Path $stagingDirectory '.env')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'data') -Destination (Join-Path $stagingDirectory 'data') -Recurse -Force
    $sourceTarget = Join-Path $stagingDirectory 'data\source-bridge'
    New-Item -ItemType Directory -Path $sourceTarget -Force | Out-Null
    Copy-Item -LiteralPath $sourceData -Destination (Join-Path $sourceTarget 'upstream-data') -Recurse -Force
    Copy-Item -LiteralPath $sourceEnv -Destination (Join-Path $sourceTarget 'upstream.env')

    & tar.exe -czf $absoluteOutput -C $stagingDirectory .
    if ($LASTEXITCODE -ne 0) {
        throw 'Creating the migration archive failed.'
    }
}
finally {
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
    if ($dbContainer) {
        docker exec $dbContainer rm -f /tmp/wechat-source.dump *> $null
    }
}

Write-Host "Migration archive created: $absoluteOutput"
