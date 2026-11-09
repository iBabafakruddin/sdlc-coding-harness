@echo off
REM Windows CMD Installer for Lean Parallel SDLC Harness
set TARGET_DIR=%~1
if "%TARGET_DIR%"=="" set TARGET_DIR=.

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python "%~dp0install.py" "%TARGET_DIR%"
    goto :eof
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "%~dp0install.py" "%TARGET_DIR%"
    goto :eof
)

echo [ERROR] Python 3 not found in PATH. Please install Python 3.
exit /b 1
