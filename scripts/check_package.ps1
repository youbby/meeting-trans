param([switch]$CheckRuntime)
$ErrorActionPreference = 'Stop'
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'PACKAGE_FILES.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($record in $manifest.files) {
    if ([IO.Path]::IsPathRooted($record.file) -or $record.file -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Invalid package file path.' }
    $target = [IO.Path]::GetFullPath((Join-Path $packageRoot $record.file))
    if (-not $target.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid package file path.' }
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Missing package file: $($record.file)" }
    $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    if ($actual -ne $record.sha256) { throw "Package file changed: $($record.file)" }
}
Write-Host "Package files verified: $($manifest.files.Count)"
if ($CheckRuntime) {
    $checkFolder = Join-Path $env:LOCALAPPDATA 'StandaloneMeetingTranscriber\checks'
    New-Item -ItemType Directory -Path $checkFolder -Force | Out-Null
    $reportPath = Join-Path $checkFolder ("package_check_{0}_{1}.json" -f (Get-Date -Format 'yyyyMMdd_HHmmss'), [guid]::NewGuid().ToString('N'))
    $process = Start-Process -FilePath (Join-Path $packageRoot 'MeetingTranscriber.exe') -ArgumentList @('--self-check', '--check-ui', '--report', ('"{0}"' -f $reportPath)) -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw 'Runtime check failed. Check the operational log.' }
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $report.models_loaded -or -not $report.aec_loaded -or -not $report.ui.pdf_bytes) { throw 'Runtime check did not complete.' }
    Write-Host 'Local models, AEC, UI and PDF verified. No microphone recording was performed.'
    Write-Host "Report: $reportPath"
}
