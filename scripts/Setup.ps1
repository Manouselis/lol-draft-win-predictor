param([string]$Python = 'py', [string]$Pnpm = 'pnpm')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path '.venv\Scripts\python.exe')) {
    if ($Python -eq 'py') { & $Python -3.12 -m venv .venv }
    else { & $Python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
& '.\.venv\Scripts\python.exe' -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed' }
& $Pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
& $Pnpm --filter league-draft-lab-ui build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
if (!(Test-Path '.env')) { Copy-Item '.env.example' '.env' }
Write-Host 'Setup complete. Run Start.cmd or .venv\Scripts\python.exe -m loldraft.cli serve'
