"""app.ws.handlers — WS Handler 业务逻辑（按业务域拆分）。"""

# Signal handlers
from .signal_handlers import (
    EditSignalHandler, AddSignalHandler, DeleteSignalHandler,
    BatchAddSignalsHandler, GetDataErrorsHandler,
    BatchEditSignalsHandler, BatchDeleteSignalsHandler,
)

# Message handlers
from .message_handlers import (
    EditMessageHandler, AddMessageHandler, DeleteMessageHandler,
    DuplicateMessageHandler, GetMessageHandler, GetMessagesHandler,
    BatchEditMessagesHandler, BatchDeleteMessagesHandler,
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

# Value table handlers
from .value_table_handlers import (
    AddValueTableHandler, UpdateValueTableHandler, DeleteValueTableHandler,
    RenameValueTableHandler, GetValueTablesHandler,
)

__all__ = [
    # Signal
    'EditSignalHandler', 'AddSignalHandler', 'DeleteSignalHandler',
    'BatchAddSignalsHandler', 'GetDataErrorsHandler',
    'BatchEditSignalsHandler', 'BatchDeleteSignalsHandler',
    # Message
    'EditMessageHandler', 'AddMessageHandler', 'DeleteMessageHandler',
    'DuplicateMessageHandler', 'GetMessageHandler', 'GetMessagesHandler',
    'BatchEditMessagesHandler', 'BatchDeleteMessagesHandler',
    # File
    'SaveHandler', 'NewFileHandler', 'ImportFileHandler', 'DownloadFileHandler',
    'CreateFileHandler', 'LoadFileHandler', 'SaveAsHandler',
    'DeleteFileHandler', 'GetSessionsHandler',
    # System
    'UndoHandler', 'RedoHandler', 'ReleaseLockHandler', 'StealLockHandler',
    'GetSummaryHandler', 'GetSessionInfoHandler', 'GetStatusHandler',
    'EditDatabaseHandler',
    'GetSnapshotDebugHandler',
    # Value table
    'AddValueTableHandler', 'UpdateValueTableHandler', 'DeleteValueTableHandler',
    'RenameValueTableHandler', 'GetValueTablesHandler',
]
