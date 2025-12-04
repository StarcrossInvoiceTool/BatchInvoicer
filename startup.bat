@echo off
REM Azure App Service startup script for Windows (if needed)
REM Azure typically uses Linux containers, but this is for Windows App Service

REM Azure provides the PORT environment variable
if "%PORT%"=="" set PORT=8000

REM Start the application using uvicorn
uvicorn app:app --host 0.0.0.0 --port %PORT% --workers 2

