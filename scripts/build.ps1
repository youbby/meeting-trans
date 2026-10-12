$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm MeetingTranscriber.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
$packageRoot = Join-Path $projectRoot 'dist\MeetingTranscriber'
$modelRoot = Join-Path $packageRoot 'models'
New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null
$manifest = Get-Content -LiteralPath 'models/manifest.json' -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files.PSObject.Properties) {
    $target = Join-Path $modelRoot $entry.Name
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path 'models' $entry.Name) -Destination $target -Force
}
Copy-Item -LiteralPath 'models/manifest.json' -Destination $modelRoot -Force
Copy-Item -LiteralPath 'readme.md' -Destination $packageRoot -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination $packageRoot -Force
Copy-Item -LiteralPath 'scripts/enable_firewall.ps1' -Destination $packageRoot -Force
Copy-Item -LiteralPath 'scripts/check_package.ps1' -Destination $packageRoot -Force
if (Test-Path -LiteralPath 'docs') { Copy-Item -LiteralPath 'docs' -Destination $packageRoot -Recurse -Force }
& '.\.venv\Scripts\python.exe' 'scripts/collect_notices.py' --package $packageRoot
if ($LASTEXITCODE -ne 0) { throw 'Notice collection failed.' }
& '.\.venv\Scripts\python.exe' 'scripts/package_portable.py' --package $packageRoot
if ($LASTEXITCODE -ne 0) { throw 'Portable packaging failed.' }
Write-Host "Built: $packageRoot"
