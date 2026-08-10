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

REM ── 自动探测可用的 Python + pip 组合 ──
REM 优先使用 python -m pip（保证同一解释器），失败时回退到裸 pip。
set "PYTHON_CMD=python"
set "PIP_CMD=python -m pip"

python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [Build] python -m pip not available, falling back to pip...
    pip --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Neither python -m pip nor pip is available!
        echo         Please install Python from https://www.python.org/
        exit /b 1
    )
    REM pip 可用但当前 python 无 pip 模块，尝试用 py launcher 定位 pip 所属 python
    py -3 -m pip --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
        set "PIP_CMD=py -3 -m pip"
        echo [Build] Using py launcher for Python 3.
    ) else (
        echo [Warn] pip found but cannot locate matching python. Using bare pip.
        set "PIP_CMD=pip"
    )
)

echo [Build] Installing Python dependencies...
if defined PIP_MIRROR (
    %PIP_CMD% install -r "%ROOT_DIR%requirements.txt" -i %PIP_MIRROR%
) else (
    %PIP_CMD% install -r "%ROOT_DIR%requirements.txt"
)
if errorlevel 1 (
    echo [ERROR] pip install failed! Please check your network or Python environment.
    exit /b 1
)
echo [Build] Python dependencies installed.

echo [Build] Building frontend...
echo [Build] Working directory: %ROOT_DIR%frontend

REM 计算自动版本号（写入 app/_auto_version.py，已被 .gitignore 排除）
%PYTHON_CMD% "%ROOT_DIR%tools\compute_version.py" --write
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
%PYTHON_CMD% -m app.server.lifecycle
