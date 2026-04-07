@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "ENV_NAME=any-auto-register"
set "BIND_HOST=0.0.0.0"
set "PORT=8000"
set "SOLVER_PORT=8889"
set "AUTO_OPEN_BROWSER=1"

echo [INFO] Project root: %CD%
echo [INFO] Fixed backend port: %PORT%
echo [INFO] Fixed solver port: %SOLVER_PORT%
echo [INFO] Target URL: http://localhost:%PORT%
echo.

echo [INFO] Clearing occupied ports before launch...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $ports=@(%PORT%,%SOLVER_PORT%); for($i=0; $i -lt 5; $i++){ $conns=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports }; $pids=$conns | Select-Object -ExpandProperty OwningProcess -Unique; if(-not $pids){ Write-Host '[INFO] Target ports are free'; exit 0 }; foreach($pid in $pids){ if($pid){ try{ taskkill /PID $pid /T /F | Out-Null; Write-Host ('[OK] Stopped PID=' + $pid) } catch{} } }; Start-Sleep -Milliseconds 800 }; $remain=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports }; if($remain){ Write-Host '[WARN] Some target ports are still occupied'; exit 1 }; Write-Host '[INFO] Target ports are free'; exit 0"
if errorlevel 1 (
  echo [ERROR] Failed to free port %PORT% or %SOLVER_PORT%.
  echo [ERROR] Close the conflicting process and try again.
  pause
  exit /b 1
)
echo.

set "PYTHON_EXE="
set "LAUNCH_MODE="

where conda >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%i in (`conda run --no-capture-output -n %ENV_NAME% python -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%i"
  if defined PYTHON_EXE if exist "!PYTHON_EXE!" set "LAUNCH_MODE=conda"
)

if not defined LAUNCH_MODE (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Neither conda nor python was found.
    echo [ERROR] Install Miniconda/Anaconda, or add Python to PATH.
    pause
    exit /b 1
  )
  for /f "usebackq delims=" %%i in (`python -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%i"
  if not exist "!PYTHON_EXE!" (
    echo [ERROR] Failed to resolve current python path.
    pause
    exit /b 1
  )
  set "LAUNCH_MODE=python"
)

set "HOST=%BIND_HOST%"
set "PORT=%PORT%"

if /i "%LAUNCH_MODE%"=="conda" (
  echo [INFO] Launch mode: conda
  echo [INFO] Conda env: %ENV_NAME%
) else (
  echo [WARN] Conda env '%ENV_NAME%' not found. Falling back to current python.
  echo [WARN] Some features like Solver may fail if dependencies are missing.
  echo [INFO] Launch mode: python
)

echo [INFO] Python: !PYTHON_EXE!
echo [INFO] Starting backend...

if "%AUTO_OPEN_BROWSER%"=="1" (
  start "" cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:%PORT%"
)

"!PYTHON_EXE!" main.py

echo.
echo [INFO] Backend exited.
pause
