$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$releaseDirectory = Join-Path $projectRoot "dist\BLACKOUT_Portable"
$archivePath = Join-Path $projectRoot "dist\BLACKOUT_Portable_Windows_x64.zip"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python 3.13 virtual environment not found at $pythonPath"
}

Set-Location -LiteralPath $projectRoot

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name BLACKOUT_Simulator `
    --add-data "configs;configs" `
    blackout_gui.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$executablePath = Join-Path $projectRoot "dist\BLACKOUT_Simulator.exe"
$smokeTest = Start-Process `
    -FilePath $executablePath `
    -ArgumentList "--smoke-test" `
    -Wait `
    -PassThru
if ($smokeTest.ExitCode -ne 0) {
    throw "Bundled executable smoke test failed with exit code $($smokeTest.ExitCode)"
}

New-Item -ItemType Directory -Force -Path $releaseDirectory | Out-Null
Copy-Item -Force `
    -LiteralPath $executablePath `
    -Destination $releaseDirectory
Copy-Item -Force `
    -LiteralPath (Join-Path $projectRoot "FRIEND_README.txt") `
    -Destination $releaseDirectory

Compress-Archive -Force -Path "$releaseDirectory\*" -DestinationPath $archivePath

Write-Host "Portable package created: $archivePath"
Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
