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

# ── 系统依赖检测与自动安装（仅 Debian/Ubuntu）──
ensure_system_deps() {
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "[Build] 非 Debian/Ubuntu 系统，跳过自动安装。"
        echo "        请确保已安装: python3-venv, nodejs, npm"
        return 0
    fi

    local MISSING=()

    # 检测 python3-venv（提供 venv 模块 + ensurepip）
    if ! dpkg -s python3-venv >/dev/null 2>&1; then
        MISSING+=(python3-venv)
    fi

    # 检测 nodejs + npm
    if ! command -v node >/dev/null 2>&1; then
        MISSING+=(nodejs)
    fi
    if ! command -v npm >/dev/null 2>&1; then
        MISSING+=(npm)
    fi

    if [ ${#MISSING[@]} -eq 0 ]; then
        echo "[Build] 系统依赖已就绪。"
        return 0
    fi

    echo "[Build] 检测到缺失系统包: ${MISSING[*]}"
    echo "[Build] 正在通过 apt 安装（需要 sudo 权限）..."
    sudo apt-get update -qq || { echo "[ERROR] apt-get update 失败，请检查网络。" >&2; exit 1; }
    sudo apt-get install -y "${MISSING[@]}" || { echo "[ERROR] 依赖安装失败，请手动执行: sudo apt install ${MISSING[*]}" >&2; exit 1; }
    echo "[Build] 系统依赖安装完成。"
}

ensure_system_deps

# ── Python 虚拟环境管理 ──
VENV_DIR="${ROOT_DIR}/venv"

if [ ! -d "${VENV_DIR}" ]; then
    echo "[Build] 创建 Python 虚拟环境: ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}" || { echo "[ERROR] venv 创建失败！请确认 python3-venv 已安装。" >&2; exit 1; }
fi

# 激活 venv
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
PYTHON_CMD="python"
PIP_CMD="python -m pip"
echo "[Build] venv 已激活: $(which python)"

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
