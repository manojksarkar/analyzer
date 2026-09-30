@echo off
rem start-app - start the ArtiFex API and web app from this folder, cleanly.
rem   start-app               check, stop old servers, start both (Ctrl+C stops them)
rem   start-app --status      what runs now      start-app --stop     stop them
rem   start-app --help        every option (the script is tools\start_app.py)
rem A .cmd, not a .ps1: office machines often block PowerShell scripts.
setlocal
set "HERE=%~dp0"
set "PYEXE="
set "PYARG="
if exist "%HERE%.venv\Scripts\python.exe" set "PYEXE=%HERE%.venv\Scripts\python.exe"
if not defined PYEXE if exist "%HERE%venv\Scripts\python.exe" set "PYEXE=%HERE%venv\Scripts\python.exe"
if defined PYEXE goto :run
rem "python" can be the Microsoft Store stub, which runs nothing: prove it works first
python -c "import sys" >nul 2>nul && set "PYEXE=python"
if not defined PYEXE py -3 -c "import sys" >nul 2>nul && set "PYEXE=py" && set "PYARG=-3"
if not defined PYEXE goto :nopython
:run
"%PYEXE%" %PYARG% "%HERE%tools\start_app.py" %*
exit /b %errorlevel%
:nopython
echo Python was not found. Install Python 3.12 or newer, then run:
echo     pip install -r requirements.txt
exit /b 1
