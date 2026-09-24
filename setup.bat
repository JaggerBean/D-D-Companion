@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.12 or newer from python.org, then rerun this file.
  pause
  exit /b 1
)
py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv
if errorlevel 1 (
  echo Could not create virtual environment.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e .
if errorlevel 1 (
  echo Dependency installation failed. See README troubleshooting.
  pause
  exit /b 1
)
if not exist config\discord.env copy config\discord.env.example config\discord.env >nul
python -c "import ctranslate2; print('CTranslate2 CUDA device count:', ctranslate2.get_cuda_device_count())"
echo Setup complete. Starting D&D Companion; first Whisper model download occurs when Discord bot receives speech.
python -m app.main
endlocal
