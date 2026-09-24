@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo D&D Companion is not installed yet. Run setup.bat first.
  pause
  exit /b 1
)
start "" /b .venv\Scripts\pythonw.exe -m app.main
endlocal
