"""app.ws — WebSocket 通信层。

re-export: WsServer, WsTransport, WsDiagnostics,
           MessageRouter, HandlerResult, HandlerError
"""

from .router import MessageRouter, HandlerResult, HandlerError
from .server import WsServer
from .transport import WsTransport, WsDiagnostics

__all__ = [
    'MessageRouter', 'HandlerResult', 'HandlerError',
    'WsServer',
    'WsTransport', 'WsDiagnostics',
]
"""app.ws — WebSocket 通信层。"""
