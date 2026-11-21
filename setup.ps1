$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .venv\Scripts\python.exe)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { & py -3 -m venv .venv }
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& .\.venv\Scripts\python.exe -c 'import sys; assert sys.version_info >= (3, 11)'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
exit $LASTEXITCODE