"""版本号管理 — 启动时加载，全局只读常量。

后端所有需要版本信息的地方统一 import VERSION 字典。
"""
import logging

from app._version import MANUAL_VERSION

logger = logging.getLogger(__name__)

# Level 1: 构建产物（由 compute_version.py --write 生成，已在 .gitignore 中排除）
try:
    from app._auto_version import AUTO_VERSION
except ImportError:
    AUTO_VERSION = "dev"


def _build_version_dict() -> dict:
    auto_ver = AUTO_VERSION
    if auto_ver == "dev":
        # Level 2: 动态计算（新克隆未构建，源码可用）
        try:
            from tools.compute_version import compute_auto_version
            auto_ver = compute_auto_version()
        except Exception as e:
            logger.debug("Dynamic version computation failed: %s", e)
            # Level 3: 保持 "dev"

    hash_part = auto_ver.split("_")[0] if "_" in auto_ver else auto_ver
    return {
        "manual_version": MANUAL_VERSION,
        "auto_version": auto_ver,
        "hash": hash_part,
    }


# 模块级只读常量，多线程读取天然安全，无需加锁
VERSION: dict = _build_version_dict()
