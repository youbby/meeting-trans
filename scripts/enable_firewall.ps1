# Optional OS-level outbound blocking for the packaged app. Run manually as administrator.
#Requires -RunAsAdministrator
param([string]$Program = '')
$ErrorActionPreference = 'Stop'
if (-not $Program) {
    $Program = Join-Path $PSScriptRoot 'MeetingTranscriber.exe'
    if (-not (Test-Path -LiteralPath $Program)) {
        $Program = Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\MeetingTranscriber\MeetingTranscriber.exe'
    }
}
$programPath = (Resolve-Path -LiteralPath $Program).Path
if ([System.IO.Path]::GetFileName($programPath) -ne 'MeetingTranscriber.exe') {
    throw 'Select the packaged MeetingTranscriber.exe.'
}
$existing = Get-NetFirewallRule -DisplayName 'Standalone Meeting Transcriber - Outbound Block' -ErrorAction SilentlyContinue
if ($existing) { $existing | Remove-NetFirewallRule }
New-NetFirewallRule -DisplayName 'Standalone Meeting Transcriber - Outbound Block' -Direction Outbound -Program $programPath -Action Block -Profile Any | Out-Null
Write-Host 'Outbound connections blocked for this EXE path. Meeting applications are unaffected.'
