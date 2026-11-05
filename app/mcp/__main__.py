"""python -m app.mcp — 以 uvicorn 独立启动 MCP 服务器（Streamable HTTP）。

⚠️ 生产环境不再使用本入口：MCP 已内嵌进后端（见 app/mcp/runner.py），
随 `python -m app.server.lifecycle` 自动拉起（端口 = HTTP + 2）。本入口仅用于
脱离后端单独调试 MCP 时使用。

环境变量：
- CANMATRIX_BACKEND_URL：后端 API 地址（默认 http://127.0.0.1:8080）
- CANMATRIX_MCP_HOST：监听地址（默认 127.0.0.1）
- CANMATRIX_MCP_PORT：监听端口（默认 8082）
"""
from __future__ import annotations

import os

import uvicorn

from app.mcp.server import build_app

DEFAULT_HOST = "127.0.0.1"
# 不能用 8081：后端 WS 端口 = 后端 HTTP 端口 +1（默认 8081），会与本服务监听端口冲突。
DEFAULT_PORT = 8082


def main() -> None:
    """读取环境变量并以 uvicorn 运行 build_app()。"""
    host = os.environ.get("CANMATRIX_MCP_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CANMATRIX_MCP_PORT", str(DEFAULT_PORT)))
    uvicorn.run(build_app(), host=host, port=port)


if __name__ == "__main__":
    main()
