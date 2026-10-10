$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskDir = [IO.Path]::GetFullPath((Join-Path $taskRepo 'data/private/wx-channel-v5.7.11'))
$taskExe = Join-Path $taskDir 'wx_channel_v5.7.11.exe'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($taskIdentity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Rollback requires the same user in an administrator terminal.' }
$taskActive = Join-Path $taskDir 'trial-active.xml'
if (-not (Test-Path -LiteralPath $taskActive)) { throw 'No active trial baseline; nothing will be changed.' }
$taskRun = Import-Clixml -LiteralPath $taskActive
if ($taskRun.Exe -ne $taskExe) { throw 'Recovery path does not match this trial.' }
$taskBefore = Import-Clixml -LiteralPath (Join-Path $taskDir 'system-before.xml')
Get-Process | Where-Object { $_.Path -eq $taskExe } | Stop-Process
foreach ($taskSetting in $taskBefore.Proxy) {
    $taskRegistry = Get-Item -LiteralPath $taskSetting.Path
    if ($taskSetting.Present) {
        $taskKind = [Enum]::Parse([Microsoft.Win32.RegistryValueKind], $taskSetting.Kind)
        $taskRegistry.SetValue($taskSetting.Name, $taskSetting.Value, $taskKind)
    } else { $taskRegistry.DeleteValue($taskSetting.Name, $false) }
}
$taskCert = $taskRun.Certificate
if (Test-Path -LiteralPath $taskCert) {
    $taskThumb = [Security.Cryptography.X509Certificates.X509Certificate2]::new($taskCert).Thumbprint
    if ($taskRun.CertificateThumbprint -and $taskRun.CertificateThumbprint -ne $taskThumb) { throw 'Trial certificate changed; preserve roots and inspect manually.' }
    foreach ($taskScope in @('CurrentUser','LocalMachine')) {
        $taskOriginal = if ($taskScope -eq 'CurrentUser') { $taskBefore.CurrentUserRoots } else { $taskBefore.LocalMachineRoots }
        if ($taskOriginal -notcontains $taskThumb) {
            $taskStore = [Security.Cryptography.X509Certificates.X509Store]::new('Root', $taskScope)
            $taskStore.Open('ReadWrite')
            try {
                foreach ($taskFound in $taskStore.Certificates.Find('FindByThumbprint',$taskThumb,$false)) { $taskStore.Remove($taskFound) }
            } finally { $taskStore.Close() }
        }
    }
}
# Only our named temporary rule, never existing firewall rules.
Get-NetFirewallRule -Name 'WeChatSource-wx-channel-v5.7.11-block-inbound' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
# Retire the active marker only after a complete recovery; keep the audit baseline.
Move-Item -LiteralPath $taskActive -Destination (Join-Path $taskDir ('trial-restored-' + (Get-Date -Format 'yyyyMMddHHmmss') + '.xml'))
Write-Output 'Stopped the trial and restored its proxy/certificate changes. Private runtime files are retained.'
