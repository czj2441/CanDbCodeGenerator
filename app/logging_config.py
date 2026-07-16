"""
logging_config.py — 统一日志配置模块。

提供 setup_logging() 供应用启动时调用，统一所有模块的日志格式和级别。
"""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """配置 app 根 logger，统一格式输出到 stdout。

    Args:
        level: 日志级别，默认 INFO。可通过 CLI 参数调整为 DEBUG。

    Returns:
        app 根 logger 实例。
    """
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger("app")
    # 避免重复添加 handler（多次调用 setup_logging 时）
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level)
    return root
