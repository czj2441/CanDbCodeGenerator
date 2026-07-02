@echo off
REM ============================================
REM  CAN Matrix Editor - Frontend Build Script
REM  Usage: double-click or run build.bat
REM ============================================

setlocal

REM Store script directory
set "ROOT_DIR=%~dp0"

echo [Build] Building frontend...
echo [Build] Working directory: %ROOT_DIR%frontend

cd /d "%ROOT_DIR%frontend"

REM Install dependencies if node_modules is missing
if not exist "node_modules\" (
    echo [Build] node_modules not found, installing dependencies...
    call npm install
    if errorlevel 1 (
        echo [Error] npm install failed!
        cd /d "%ROOT_DIR%"
        exit /b 1
    )
    echo [Build] Dependencies installed.
)

REM Run build
call npm run build
if errorlevel 1 (
    echo [Error] Build failed!
    cd /d "%ROOT_DIR%"
    exit /b 1
)

echo.
echo ============================================
echo  [OK] Frontend build succeeded!
echo  Output: %ROOT_DIR%dist\
echo ============================================
echo.

REM Ask whether to start backend server
set /p LAUNCH="Start backend server (python api_server.py 8080)? [Y/n]: "
if /i "%LAUNCH%"=="n" goto :done

echo [Build] Starting backend server...
cd /d "%ROOT_DIR%"
python api_server.py 8080
goto :eof

:done
cd /d "%ROOT_DIR%"
endlocal
