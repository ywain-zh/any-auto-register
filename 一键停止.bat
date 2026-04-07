@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo [INFO] Stopping backend and solver...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $ports=@(8000,8889); for($i=0; $i -lt 5; $i++){ $conns=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports }; $pids=$conns | Select-Object -ExpandProperty OwningProcess -Unique; if(-not $pids){ Write-Host '[INFO] No matching process found'; exit 0 }; foreach($pid in $pids){ if($pid){ try{ taskkill /PID $pid /T /F | Out-Null; Write-Host ('[OK] Stopped PID=' + $pid) } catch{} } }; Start-Sleep -Milliseconds 800 }; $remain=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports }; if($remain){ Write-Host '[WARN] Some target ports are still occupied'; exit 1 }; Write-Host '[INFO] Stop completed'; exit 0"
if errorlevel 1 (
  echo [WARN] Some target ports are still occupied.
)
echo.
pause
