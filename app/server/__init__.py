"""app.server — HTTP 服务层。"""

from .http_handler import ApiHandler
from .port_utils import check_port_available, handle_port_conflict, find_available_port
from .lifecycle import main, start_server_background, BackgroundServer, SESSION_MGR

__all__ = [
    'ApiHandler', 'check_port_available', 'handle_port_conflict', 'find_available_port',
    'main', 'start_server_background', 'BackgroundServer', 'SESSION_MGR',
]
