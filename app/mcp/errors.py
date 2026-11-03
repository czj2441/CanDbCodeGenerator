"""MCP 层错误类型。"""
from __future__ import annotations


class BackendError(Exception):
    """后端调用失败。

    属性：
    - code：错误码。HTTP 层为 f"HTTP_{status}"（如 HTTP_401；连接失败为 HTTP_0）；
      WS 层使用语义码（如 SESSION_NOT_FOUND），由各调用方约定。
    - message：人类可读的错误文案（后端 error 字段或回退文案）。
    - details：后端返回的 details 字段（无则空 dict）。
    """

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else {}
