"""版本号管理 — 启动时加载，全局只读常量。

后端所有需要版本信息的地方统一 import VERSION 字典。
"""
from _version import MANUAL_VERSION, AUTO_VERSION

def _build_version_dict() -> dict:
    auto_ver = AUTO_VERSION
    if auto_ver == "dev":
        # 开发模式：动态计算（运行时源码文件存在）
        try:
            from compute_version import compute_auto_version
            auto_ver = compute_auto_version()
        except Exception:
            auto_ver = "dev"

    hash_part = auto_ver.split("_")[0] if "_" in auto_ver else auto_ver
    return {
        "manual_version": MANUAL_VERSION,
        "auto_version": auto_ver,
        "hash": hash_part,
    }


# 模块级只读常量，多线程读取天然安全，无需加锁
VERSION: dict = _build_version_dict()
