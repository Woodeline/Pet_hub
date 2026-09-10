@echo off
rem ============================================================
rem  desktop-pet launcher  (double-click this file to start)
rem  This .bat is ASCII-only on purpose, to avoid any encoding
rem  problem caused by non-ASCII characters in the path.
rem ============================================================

cd /d "%~dp0"
set "APPDIR=%~dp0"
set "PYTHONPATH=%APPDIR%src"

rem --- 1) prefer the packaged standalone exe (no Python needed) ---
if exist "%APPDIR%dist\desktop-pet\desktop-pet.exe" (
    start "" "%APPDIR%dist\desktop-pet\desktop-pet.exe"
    exit /b 0
)

rem --- 2) project-local venv ---
if exist "%APPDIR%.venv\Scripts\pythonw.exe" (
    start "" "%APPDIR%.venv\Scripts\pythonw.exe" -m desktop_pet.main
    exit /b 0
)

rem --- 3) fallback: the workspace runtime that already has PySide6 + pynput ---
set "FB=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if exist "%FB%" (
    start "" "%FB%" -m desktop_pet.main
    exit /b 0
)

echo.
echo  [ERROR] No usable Python runtime found.
echo.
echo  Option A: run the packaged exe directly:
echo      dist\desktop-pet\desktop-pet.exe
echo  Option B: install Python 3.13, then follow README.md
echo.
pause
