"""python -m app.mcp — 以 uvicorn 启动 MCP 服务器（Streamable HTTP）。

环境变量：
- CANMATRIX_BACKEND_URL：后端 API 地址（默认 http://127.0.0.1:8080）
- CANMATRIX_MCP_HOST：监听地址（默认 127.0.0.1）
- CANMATRIX_MCP_PORT：监听端口（默认 8081）
"""
from __future__ import annotations

import os

import uvicorn

from app.mcp.server import build_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8081


def main() -> None:
    """读取环境变量并以 uvicorn 运行 build_app()。"""
    host = os.environ.get("CANMATRIX_MCP_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CANMATRIX_MCP_PORT", str(DEFAULT_PORT)))
    uvicorn.run(build_app(), host=host, port=port)


if __name__ == "__main__":
    main()
