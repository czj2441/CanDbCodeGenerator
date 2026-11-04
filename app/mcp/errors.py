"""MCP 层错误类型与工具错误统一映射。"""
from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

# 文件被占时附上的提示（占用者信息在消息上文）。
FILE_LOCKED_HINT = "文件被他人占用，占用者信息见上文"
# 只读会话写入被拒时附上的可执行提示。
READONLY_WRITE_HINT = "文件所有者可写，联系其授权或由其编辑"


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

    @property
    def status(self) -> int | None:
        """HTTP 状态码（解析自 code 的 f"HTTP_{status}" 形式）；非 HTTP 错误码时 None。"""
        if not self.code.startswith("HTTP_"):
            return None
        try:
            return int(self.code[len("HTTP_"):])
        except ValueError:
            return None


def tool_error(e: BackendError) -> ToolError:
    """BackendError → ToolError 统一映射（工具层共用，Task 8/9/11 复用）。

    基础形如 f"{message}（{code}）"（保留后端中文原文）；按语义附可执行提示：
    - FILE_LOCKED：附「文件被他人占用，占用者信息见上文」；
    - 只读会话写入被拒（read_only/permission_denied）：附「文件所有者可写，联系其授权或由其编辑」。
    """
    message = f"{e.message}（{e.code}）"
    if e.code == "FILE_LOCKED":
        message = f"{message}；{FILE_LOCKED_HINT}"
    elif e.code in ("read_only", "permission_denied"):
        message = f"{message}；{READONLY_WRITE_HINT}"
    return ToolError(message)
