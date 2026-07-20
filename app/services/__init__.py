"""app.services — 业务服务层。"""

from .session import Session
from .file_lock import FileLockManager
from .undo_engine import UndoEngine
from .session_manager import (
    SessionManager, FileLockedError, FileNameExistsError,
    get_session_manager, init_session_manager,
)
from .file_persistence import (
    DATA_DIR, SNAPSHOT_DIR, HEARTBEAT_TIMEOUT, HEARTBEAT_CHECK_INTERVAL, MAX_ORPHAN_STACKS,
    write_session_file, load_session_file,
)

__all__ = [
    'Session', 'SessionManager', 'FileLockedError', 'FileNameExistsError',
    'FileLockManager', 'UndoEngine',
    'get_session_manager', 'init_session_manager',
    'DATA_DIR', 'SNAPSHOT_DIR', 'HEARTBEAT_TIMEOUT', 'HEARTBEAT_CHECK_INTERVAL', 'MAX_ORPHAN_STACKS',
    'write_session_file', 'load_session_file',
]
