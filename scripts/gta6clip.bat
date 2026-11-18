@echo off
setlocal
set "HERE=%~dp0"
if exist "%USERPROFILE%\.viral-clipper\venv\Scripts\python.exe" (
    set "PATH=%USERPROFILE%\.viral-clipper\venv\Scripts;%PATH%"
    "%USERPROFILE%\.viral-clipper\venv\Scripts\python.exe" "%HERE%run.py" %*
    exit /b %ERRORLEVEL%
)
python "%HERE%run.py" %*
