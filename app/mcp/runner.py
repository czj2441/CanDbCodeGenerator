"""内嵌 MCP 服务器 — 在后台线程内运行 uvicorn，供后端 lifecycle 绑定启动。

端口同源派生，构成三元组绑定（偏移常量见 app/server/port_utils.py）：
    HTTP = P（后端）、WS = P + WS_PORT_OFFSET、MCP = P + MCP_PORT_OFFSET
一个后端进程 = 一个三元组，MCP 永远指向本进程后端。
"""
from __future__ import annotations

import logging
import threading

from uvicorn.config import Config
from uvicorn.server import Server

from app.mcp.backend import set_backend_url
from app.mcp.server import build_app
from app.server.port_utils import MCP_PORT_OFFSET

logger = logging.getLogger(__name__)


class EmbeddedMcpServer:
    """在守护线程内运行 MCP（uvicorn），随调用方进程生命周期起停。"""

    def __init__(self, host: str, http_port: int):
        self._http_port = http_port
        self._mcp_port = http_port + MCP_PORT_OFFSET
        self._thread: threading.Thread | None = None
        config = Config(
            app=build_app(),
            host=host,
            port=self._mcp_port,
            # 不重配根 logger（避免覆盖后端的 setup_logging）；uvicorn 内部告警仍会传播。
            log_config=None,
            log_level="warning",
            access_log=False,
        )
        self._server = Server(config)

    @property
    def mcp_port(self) -> int:
        return self._mcp_port

    def start(self) -> None:
        """指向本进程后端并启动 uvicorn 线程。"""
        # 同进程 loopback；WS 地址由 backend 层按 HTTP + WS_PORT_OFFSET 自动推导。
        set_backend_url(f"http://127.0.0.1:{self._http_port}")
        self._thread = threading.Thread(
            target=self._server.run, name="mcp-server", daemon=True
        )
        self._thread.start()
        logger.info(
            "MCP server started on port %d (backend http %d)", self._mcp_port, self._http_port
        )

    def stop(self, timeout: float = 3.0) -> None:
        """优雅停止 uvicorn 线程。"""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
