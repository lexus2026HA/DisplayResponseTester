$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .venv\Scripts\python.exe)) { throw 'Run setup.ps1 first.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed `
    --name DisplayResponseTester-v1.2 --distpath build --workpath build\work --specpath build `
    --add-data "$PSScriptRoot\assets;assets" --add-data "$PSScriptRoot\config\panels.json;config" main.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force build\Images | Out-Null
Get-ChildItem Images -File | Where-Object { $_.Extension -in '.jpg', '.jpeg', '.png' } |
    ForEach-Object {
        $target = Join-Path (Join-Path $PSScriptRoot 'build\Images') $_.Name
        if (!(Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath $_.FullName -Destination $target }
    }
Get-Item build\DisplayResponseTester-v1.2.exe