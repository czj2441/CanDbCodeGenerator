"""HTTP 后端客户端 — MCP 服务器以 PAT 身份调用 CanMatrix 后端 API。"""
from __future__ import annotations

import os

import httpx

from app.mcp.errors import BackendError

# 后端 API 默认地址（可用环境变量 CANMATRIX_BACKEND_URL 覆盖）。
DEFAULT_BACKEND_URL = "http://127.0.0.1:8080"


class BackendClient:
    """后端 HTTP API 客户端 — 所有请求带 Authorization: Bearer <PAT>。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._transport = transport

    async def request(
        self, method: str, path: str, body: dict | None = None, timeout: float = 30.0
    ) -> dict:
        """发起后端请求，成功时返回完整响应体（{"success": true, "data": ...}，调用方取 data）。

        HTTP 非 2xx 或 {"success": false} → BackendError(code=f"HTTP_{status}",
        message=error 文案, details=details)；连接失败/超时 → BackendError(code="HTTP_0")。
        """
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, transport=self._transport, timeout=timeout
            ) as client:
                resp = await client.request(
                    method,
                    path,
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=body,
                )
        except httpx.RequestError as exc:
            raise BackendError(code="HTTP_0", message=f"无法连接后端：{exc}", details={}) from exc

        try:
            resp_body = resp.json()
        except ValueError:
            resp_body = None
        if not isinstance(resp_body, dict):
            resp_body = {}
        if 200 <= resp.status_code < 300 and resp_body.get("success"):
            return resp_body
        raise BackendError(
            code=f"HTTP_{resp.status_code}",
            message=resp_body.get("error") or f"后端返回 HTTP {resp.status_code}",
            details=resp_body.get("details") or {},
        )


def get_backend() -> BackendClient:
    """构造当前请求对应的后端客户端（当前 PAT + 环境变量 CANMATRIX_BACKEND_URL）。"""
    # 延迟导入：auth_context 顶层导入本模块的 get_backend，避免循环依赖。
    from app.mcp.auth_context import get_current_pat

    return BackendClient(
        base_url=os.environ.get("CANMATRIX_BACKEND_URL", DEFAULT_BACKEND_URL),
        token=get_current_pat() or "",
    )
