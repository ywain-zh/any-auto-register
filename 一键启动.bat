@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "BIND_HOST=0.0.0.0"
set "PORT=8000"
set "SOLVER_PORT=8889"
set "AUTO_OPEN_BROWSER=1"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=%~dp0.venv\bin\python"
)

echo [INFO] Project root: %CD%
echo [INFO] Fixed backend port: %PORT%
echo [INFO] Fixed solver port: %SOLVER_PORT%
echo [INFO] Target URL: http://localhost:%PORT%
echo.

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Local virtualenv python not found.
  echo [ERROR] Expected: %~dp0.venv\Scripts\python.exe
  echo [ERROR] Please create the local .venv first.
  pause
  exit /b 1
)

echo [INFO] Using local virtualenv: %PYTHON_EXE%
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

set "HOST=%BIND_HOST%"
set "PORT=%PORT%"

echo [INFO] Starting backend...

if "%AUTO_OPEN_BROWSER%"=="1" (
  start "" cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:%PORT%"
)

"%PYTHON_EXE%" main.py

echo.
echo [INFO] Backend exited.
pause
