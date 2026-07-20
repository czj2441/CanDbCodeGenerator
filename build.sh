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

echo "[Build] 正在安装 Python 依赖..."
if [ -n "${PIP_MIRROR}" ]; then
    pip3 install -r "${ROOT_DIR}/requirements.txt" -i "${PIP_MIRROR}" || echo "[Warn] pip install 失败，部分功能可能不可用。"
else
    pip3 install -r "${ROOT_DIR}/requirements.txt" || echo "[Warn] pip install 失败，部分功能可能不可用。"
fi
echo "[Build] Python 依赖安装完成。"

echo "[Build] 正在构建前端..."
echo "[Build] 工作目录: ${ROOT_DIR}/frontend"

# 计算自动版本号（写入 app/_auto_version.py，已被 .gitignore 排除）
echo "[Build] 计算版本号..."
python "${ROOT_DIR}/tools/compute_version.py" --write || echo "[Warn] 版本号计算失败，使用默认值"

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
python -m app.server.lifecycle 8080
