"""app.server — HTTP 服务层。"""

from .http_handler import ApiHandler
from .port_utils import check_port_available, handle_port_conflict, find_available_port

_LAZY_EXPORTS = {
    'main': '.lifecycle',
    'start_server_background': '.lifecycle',
    'BackgroundServer': '.lifecycle',
    'SESSION_MGR': '.lifecycle',
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        import importlib
        module = importlib.import_module(_LAZY_EXPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module 'app.server' has no attribute {name!r}")


__all__ = [
    'ApiHandler', 'check_port_available', 'handle_port_conflict', 'find_available_port',
    'main', 'start_server_background', 'BackgroundServer', 'SESSION_MGR',
]
