"""app.ws.handlers — WS Handler 业务逻辑（按业务域拆分）。"""

# Signal handlers
from .signal_handlers import (
    EditSignalHandler, AddSignalHandler, DeleteSignalHandler,
    BatchAddSignalsHandler, GetSignalErrorsHandler,
)

# Message handlers
from .message_handlers import (
    EditMessageHandler, AddMessageHandler, DeleteMessageHandler,
    DuplicateMessageHandler, GetMessageHandler, GetMessagesHandler,
)

# File handlers
from .file_handlers import (
    SaveHandler, NewFileHandler, ImportFileHandler, DownloadFileHandler,
    CreateFileHandler, LoadFileHandler, SaveAsHandler,
    DeleteFileHandler, GetSessionsHandler,
)

# System handlers
from .system_handlers import (
    UndoHandler, RedoHandler, ReleaseLockHandler, StealLockHandler,
    GetSummaryHandler, GetSessionInfoHandler, GetStatusHandler,
    EditDatabaseHandler,
    GetSnapshotDebugHandler,
)

__all__ = [
    # Signal
    'EditSignalHandler', 'AddSignalHandler', 'DeleteSignalHandler',
    'BatchAddSignalsHandler', 'GetSignalErrorsHandler',
    # Message
    'EditMessageHandler', 'AddMessageHandler', 'DeleteMessageHandler',
    'DuplicateMessageHandler', 'GetMessageHandler', 'GetMessagesHandler',
    # File
    'SaveHandler', 'NewFileHandler', 'ImportFileHandler', 'DownloadFileHandler',
    'CreateFileHandler', 'LoadFileHandler', 'SaveAsHandler',
    'DeleteFileHandler', 'GetSessionsHandler',
    # System
    'UndoHandler', 'RedoHandler', 'ReleaseLockHandler', 'StealLockHandler',
    'GetSummaryHandler', 'GetSessionInfoHandler', 'GetStatusHandler',
    'EditDatabaseHandler',
    'GetSnapshotDebugHandler',
]
