param(
    [string]$EnvName = "any-auto-register",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$RestartExisting = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    Write-Error "conda command not found. Install Miniconda/Anaconda first and make sure conda is available in the terminal."
    exit 1
}

Write-Host "[INFO] Project root: $root"
Write-Host "[INFO] Conda env: $EnvName"
if ($BindHost -eq "0.0.0.0") {
    $displayHost = "localhost"
} else {
    $displayHost = $BindHost
}
Write-Host "[INFO] Backend URL: http://$displayHost`:$Port"
Write-Host "[INFO] Press Ctrl+C to stop"

if ($RestartExisting) {
    Write-Host "[INFO] Stopping old backend / solver processes first"
    & "$root\stop_backend.ps1" -BackendPort $Port -SolverPort 8889 -FullStop 0
}

$pythonExe = (conda run --no-capture-output -n $EnvName python -c "import sys; print(sys.executable)").Trim()
if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
    Write-Error "Failed to resolve python executable for conda env '$EnvName'."
    exit 1
}

$env:HOST = $BindHost
$env:PORT = [string]$Port

Write-Host "[INFO] Python: $pythonExe"
& $pythonExe main.py
