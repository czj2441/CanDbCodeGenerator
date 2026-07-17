#!/usr/bin/env bash
# ============================================
#  CAN Matrix Editor - 前端快速构建脚本
#  用法：chmod +x build.sh && ./build.sh
# ============================================

set -e

# 获取脚本所在目录（兼容软链接）
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[Build] 正在安装 Python 依赖..."
pip3 install -r "${ROOT_DIR}/requirements.txt" || echo "[Warn] pip install 失败，部分功能可能不可用。"
echo "[Build] Python 依赖安装完成。"

echo "[Build] 正在构建前端..."
echo "[Build] 工作目录: ${ROOT_DIR}/frontend"

# 计算自动版本号
echo "[Build] 计算版本号..."
python3 "${ROOT_DIR}/tools/compute_version.py" --write || echo "[Warn] 版本号计算失败，使用默认值"

cd "${ROOT_DIR}/frontend"

# 检查 node_modules 是否存在，若不存在则先安装依赖
if [ ! -d "node_modules" ]; then
    echo "[Build] 未检测到 node_modules，正在安装依赖..."
    npm install
    echo "[Build] 依赖安装完成。"
fi

# 执行构建
npm run build

echo ""
echo "============================================"
echo " [OK] 前端构建成功！"
echo " 产物已输出到: ${ROOT_DIR}/dist/"
echo "============================================"
echo ""

# 询问是否启动后端服务
read -p "是否启动后端服务 (python -m app.server.lifecycle 8080)? [Y/n]: " LAUNCH
if [[ "${LAUNCH,,}" == "n" ]]; then
    exit 0
fi

echo "[Build] 正在启动后端服务..."
cd "${ROOT_DIR}"
python -m app.server.lifecycle 8080
