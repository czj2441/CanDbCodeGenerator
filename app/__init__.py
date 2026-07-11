"""app — CanMatrix Editor 后端 Python 包。

Lazy re-export（避免 import app 触发服务器初始化）:
    from app import main, start_server_background, BackgroundServer, VERSION
"""

from .version import VERSION

_LAZY_EXPORTS = {
    'main': '.server',
    'start_server_background': '.server',
    'BackgroundServer': '.server',
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        import importlib
        module = importlib.import_module(_LAZY_EXPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module 'app' has no attribute {name!r}")


__all__ = ['main', 'start_server_background', 'BackgroundServer', 'VERSION']
"""app — CanMatrix Editor 后端 Python 包。"""
