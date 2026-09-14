# Run once from an administrator PowerShell to allow LAN website access.
$ErrorActionPreference = 'Stop'
$ruleName = 'WeChatSource-LAN-3500'
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -Name $ruleName
}
New-NetFirewallRule -Name $ruleName -DisplayName 'WeChat Source LAN website' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3500 -RemoteAddress LocalSubnet -Profile Any | Out-Null
