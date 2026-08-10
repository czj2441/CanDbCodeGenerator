#!/usr/bin/env bash
# ============================================
#  CAN Matrix Editor - 前端快速构建脚本
#  用法：chmod +x build.sh && ./build.sh
# ============================================

set -e

# 获取脚本所在目录（兼容软链接）
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# PyPI 镜像源（留空则使用官方源，国内推荐清华源）
PIP_MIRROR=""

# ── 自动探测可用的 Python + pip 组合 ──
# 优先使用 python3 -m pip（保证同一解释器），失败时回退到裸 pip3/pip。
PYTHON_CMD=python3
PIP_CMD="python3 -m pip"

if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "[Build] python3 -m pip not available, falling back..."
    if pip3 --version >/dev/null 2>&1; then
        PIP_CMD="pip3"
        PYTHON_CMD="python3"
        echo "[Warn] Using bare pip3. Python and pip may point to different interpreters."
    elif pip --version >/dev/null 2>&1; then
        PIP_CMD="pip"
        PYTHON_CMD="python"
        echo "[Warn] Using bare pip. Python and pip may point to different interpreters."
    else
        echo "[ERROR] Neither python3 -m pip nor pip3/pip is available!" >&2
        echo "        Please install Python 3 from https://www.python.org/" >&2
        exit 1
    fi
fi

echo "[Build] 正在安装 Python 依赖..."
if [ -n "${PIP_MIRROR}" ]; then
    $PIP_CMD install -r "${ROOT_DIR}/requirements.txt" -i "${PIP_MIRROR}" || { echo "[ERROR] pip install 失败，请检查网络或 Python 环境。" >&2; exit 1; }
else
    $PIP_CMD install -r "${ROOT_DIR}/requirements.txt" || { echo "[ERROR] pip install 失败，请检查网络或 Python 环境。" >&2; exit 1; }
fi
echo "[Build] Python 依赖安装完成。"

echo "[Build] 正在构建前端..."
echo "[Build] 工作目录: ${ROOT_DIR}/frontend"

# 计算自动版本号（写入 app/_auto_version.py，已被 .gitignore 排除）
echo "[Build] 计算版本号..."
${PYTHON_CMD} "${ROOT_DIR}/tools/compute_version.py" --write || echo "[Warn] 版本号计算失败，使用默认值"

cd "${ROOT_DIR}/frontend"

# 始终执行 npm install 以确保依赖完整（依赖已全时极快）
echo "[Build] 检查依赖..."
npm install
echo "[Build] 依赖检查完成。"

# 执行构建
npm run build

echo ""
echo "============================================"
echo " [OK] 前端构建成功！"
echo " 产物已输出到: ${ROOT_DIR}/dist/"
echo "============================================"
echo ""

echo "[Build] 正在启动后端服务..."
cd "${ROOT_DIR}"
${PYTHON_CMD} -m app.server.lifecycle
