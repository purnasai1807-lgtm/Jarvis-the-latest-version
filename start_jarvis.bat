@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "LOG_DIR=%PROJECT_DIR%data\logs"
set "LOG_FILE=%LOG_DIR%startup.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo [%date% %time%] Starting Jarvis after Windows sign-in.>>"%LOG_FILE%"

:: Give audio devices, network, and GPU drivers time to finish initializing.
timeout /t 15 /nobreak >nul

if exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
	set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
	set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
	set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
) else (
	set "PYTHON_EXE="
)

cd /d "%PROJECT_DIR%"
if defined PYTHON_EXE (
	"%PYTHON_EXE%" main.py >>"%LOG_FILE%" 2>&1
) else (
	py.exe -3 main.py >>"%LOG_FILE%" 2>&1
)
echo [%date% %time%] Jarvis exited with code %errorlevel%.>>"%LOG_FILE%"
endlocal
