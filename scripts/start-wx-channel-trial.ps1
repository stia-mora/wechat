param([switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskDir = [IO.Path]::GetFullPath((Join-Path $taskRepo 'data/private/wx-channel-v5.7.11'))
$taskExe = Join-Path $taskDir 'wx_channel_v5.7.11.exe'
$taskSnapshot = Join-Path $taskDir 'system-before.xml'
$taskConfig = Join-Path $taskDir 'config.yaml'
$taskPrivate = Join-Path $taskDir 'local-access.json'
$taskActive = Join-Path $taskDir 'trial-active.xml'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskAdmin = [Security.Principal.WindowsPrincipal]::new($taskIdentity)
if (-not $PrepareOnly -and -not $taskAdmin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Controlled trial requires an administrator terminal.' }
if (Test-Path -LiteralPath $taskActive) { throw 'An active trial has recovery data; stop it before preparing another trial.' }
New-Item -ItemType Directory -Path $taskDir -Force | Out-Null
& icacls.exe $taskDir /inheritance:r /grant:r ($taskIdentity.Name + ':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict the private runtime directory.' }
if (-not (Test-Path -LiteralPath $taskExe)) {
    Invoke-WebRequest -Uri 'https://github.com/nobiyou/wx_channel/releases/download/v5.7.11/wx_channel_v5.7.11.exe' -OutFile $taskExe -TimeoutSec 180
}
if (-not (Test-Path -LiteralPath $taskPrivate)) {
    $taskToken = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    @{ wx_token=$taskToken; credentials_file=(Join-Path $taskDir 'downloads/mp.json') } | ConvertTo-Json | Out-File -LiteralPath $taskPrivate -Encoding utf8
}
$taskAccess = Get-Content -LiteralPath $taskPrivate -Raw | ConvertFrom-Json
(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'wx-channel-config.example.yaml') -Raw).Replace('@LOCAL_TOKEN@',$taskAccess.wx_token).Replace('@CERT_PATH@',(Join-Path $taskDir 'SunnyRoot.cer').Replace('\','/')) | Out-File -LiteralPath $taskConfig -Encoding utf8
$taskHash = (Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash
Write-Output ('Prepared wx_channel v5.7.11; SHA256=' + $taskHash)
if ($PrepareOnly) { return }
if (Get-NetTCPConnection -State Listen -LocalPort 2025,2026 -ErrorAction SilentlyContinue) { throw 'Port 2025 or 2026 is already in use; do not replace an existing instance.' }
# A fresh baseline is captured at each actual launch, never during preparation.
$taskProxy = foreach ($taskPath in @('HKCU:/Software/Microsoft/Windows/CurrentVersion/Internet Settings','HKCU:/Software/Microsoft/Windows/CurrentVersion/Internet Settings/Connections')) {
    $taskRegistry = Get-Item -LiteralPath $taskPath
    $taskNames = if ($taskPath.EndsWith('/Connections')) { $taskRegistry.GetValueNames() } else { @('ProxyEnable','ProxyServer','ProxyOverride','AutoConfigURL','AutoDetect') }
    foreach ($taskName in $taskNames) {
        $taskPresent = $taskRegistry.GetValueNames() -contains $taskName
        [PSCustomObject]@{ Path=$taskPath; Name=$taskName; Present=$taskPresent; Value=$taskRegistry.GetValue($taskName); Kind=$(if ($taskPresent) { $taskRegistry.GetValueKind($taskName).ToString() } else { '' }) }
    }
}
[PSCustomObject]@{
    Proxy=$taskProxy
    CurrentUserRoots=@(Get-ChildItem Cert:/CurrentUser/Root | ForEach-Object Thumbprint)
    LocalMachineRoots=@(Get-ChildItem Cert:/LocalMachine/Root | ForEach-Object Thumbprint)
    CapturedAt=(Get-Date).ToUniversalTime().ToString('o')
} | Export-Clixml -LiteralPath $taskSnapshot
# Block every inbound network profile for this executable; loopback remains local.
$taskRule = 'WeChatSource-wx-channel-v5.7.11-block-inbound'
if (Get-NetFirewallRule -Name $taskRule -ErrorAction SilentlyContinue) { throw 'Trial firewall rule already exists; inspect before starting.' }
if (Get-NetFirewallProfile | Where-Object { -not $_.Enabled }) { throw 'Every firewall profile must be enabled before an all-interface upstream service is started.' }
[PSCustomObject]@{ Exe=$taskExe; Certificate=(Join-Path $taskDir 'SunnyRoot.cer'); FirewallRule=$taskRule; CertificateThumbprint='' } | Export-Clixml -LiteralPath $taskActive
New-NetFirewallRule -Name $taskRule -DisplayName $taskRule -Program $taskExe -Direction Inbound -Action Block -Profile Any | Out-Null
$taskProcess = Start-Process -FilePath $taskExe -ArgumentList @('--config', ('"' + $taskConfig + '"')) -WorkingDirectory $taskDir -WindowStyle Hidden -PassThru
for ($taskAttempt=0; $taskAttempt -lt 20; $taskAttempt++) {
    if (Test-Path -LiteralPath (Join-Path $taskDir 'SunnyRoot.cer')) {
        $taskRun = Import-Clixml -LiteralPath $taskActive
        $taskRun.CertificateThumbprint = [Security.Cryptography.X509Certificates.X509Certificate2]::new($taskRun.Certificate).Thumbprint
        $taskRun | Export-Clixml -LiteralPath $taskActive
        Write-Output ('Trial certificate SHA1 thumbprint=' + $taskRun.CertificateThumbprint)
        break
    }
    if ($taskProcess.HasExited) { throw 'wx_channel exited; run the stop script to restore the baseline.' }
    Start-Sleep -Milliseconds 500
}
if (-not (Import-Clixml -LiteralPath $taskActive).CertificateThumbprint) { throw 'Certificate could not be recorded; run the stop script before proceeding.' }
Write-Output 'Trial started. Only public MP test pages are in scope; no cloud or radar is enabled.'
