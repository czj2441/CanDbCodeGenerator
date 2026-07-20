@echo off
REM ============================================
REM  CAN Matrix Editor - Frontend Build Script
REM  Usage: double-click or run build.bat
REM ============================================

setlocal

REM Store script directory
set "ROOT_DIR=%~dp0"

REM PyPI 镜像源（留空则使用官方源，国内推荐清华源）
set "PIP_MIRROR="

echo [Build] Installing Python dependencies...
if defined PIP_MIRROR (
    pip install -r "%ROOT_DIR%requirements.txt" -i %PIP_MIRROR%
) else (
    pip install -r "%ROOT_DIR%requirements.txt"
)
if errorlevel 1 (
    echo [Warn] pip install failed, some features may not work.
)
echo [Build] Python dependencies installed.

echo [Build] Building frontend...
echo [Build] Working directory: %ROOT_DIR%frontend

REM 计算自动版本号（写入 app/_auto_version.py，已被 .gitignore 排除）
python "%ROOT_DIR%tools\compute_version.py" --write
if errorlevel 1 (
    echo [Warn] Version computation failed, using defaults.
)

cd /d "%ROOT_DIR%frontend"

REM 始终执行 npm install 以确保依赖完整（依赖已全时极快）
echo [Build] Checking dependencies...
call npm install
if errorlevel 1 (
    echo [Error] npm install failed!
    cd /d "%ROOT_DIR%"
    exit /b 1
)
echo [Build] Dependencies ready.

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

echo [Build] Starting backend server...
cd /d "%ROOT_DIR%"
python -m app.server.lifecycle 8080
