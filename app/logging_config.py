"""
logging_config.py — 统一日志配置模块。

提供 setup_logging() 供应用启动时调用，统一所有模块的日志格式和级别。
服务器模式下自动启用文件日志（SessionRotatingHandler），桌面模式仅 stdout。
"""

import logging
import os
import sys
import time
import threading
from datetime import datetime
from logging.handlers import BaseRotatingHandler


class SessionRotatingHandler(BaseRotatingHandler):
    """基于会话的文件日志 handler。

    每次启动创建独立会话目录（启动时间戳命名），日志文件按日期+序号命名。
    支持按大小拆分（10MB）和过期目录自动清理。
    """

    MAX_BYTES = 10 * 1024 * 1024   # 10 MB
    RETENTION_DAYS = 30
    CLEANUP_INTERVAL = 86400        # 24 hours

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        now = datetime.now()

        # 创建会话目录：logs/YYYYMMDD_HHMMSS/
        session_name = now.strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(base_dir, session_name)
        os.makedirs(self.session_dir, exist_ok=True)

        # 初始化父类（打开第一个日志文件）
        self._current_date = now.strftime("%Y-%m-%d")
        self._index = 1
        first_path = self._build_path(self._current_date, self._index)
        BaseRotatingHandler.__init__(self, first_path, 'a', encoding='utf-8')
        self.max_bytes = self.MAX_BYTES

        # 过期清理：首次执行 + 每 24 小时定时执行
        self._cleanup()
        self._cleanup_timer = None
        self._schedule_cleanup()

    def _build_path(self, date_str: str, index: int) -> str:
        return os.path.join(self.session_dir, f"{date_str}_{index:03d}.log")

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        """文件大小超限或日期变更时触发轮转。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            return True
        if self.stream is None:
            self.stream = self._open()
        msg = self.format(record) + self.terminator
        self.stream.seek(0, 2)
        return self.stream.tell() + len(msg.encode("utf-8")) >= self.max_bytes

    def doRollover(self):
        """关闭当前文件，打开新日志文件。"""
        if self.stream:
            self.stream.close()
            self.stream = None

        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            # 跨日：重置序号
            self._current_date = today
            self._index = 1
        else:
            self._index += 1

        self.baseFilename = os.path.abspath(
            self._build_path(self._current_date, self._index)
        )
        self.stream = self._open()

    # ── 过期清理 ──

    def _cleanup(self):
        """删除 mtime 超过 RETENTION_DAYS 天的会话目录。"""
        if not os.path.isdir(self.base_dir):
            return
        cutoff = time.time() - self.RETENTION_DAYS * 86400
        for name in os.listdir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if not os.path.isdir(path):
                continue
            try:
                if os.path.getmtime(path) < cutoff:
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass

    def _schedule_cleanup(self):
        """注册 24 小时后的下一次清理。"""
        self._cleanup_timer = threading.Timer(
            self.CLEANUP_INTERVAL, self._run_cleanup
        )
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _run_cleanup(self):
        self._cleanup()
        self._schedule_cleanup()

    def close(self):
        """取消定时器并关闭文件。"""
        if self._cleanup_timer is not None:
            self._cleanup_timer.cancel()
            self._cleanup_timer = None
        super().close()


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

        # 文件日志：PyInstaller 桌面模式跳过
        if not getattr(sys, 'frozen', False):
            project_root = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            try:
                log_base = os.path.join(project_root, "logs")
                fh = SessionRotatingHandler(log_base)
                fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
                root.addHandler(fh)
            except Exception as e:
                root.warning("File logging disabled: %s", e)

    root.setLevel(level)
    return root
