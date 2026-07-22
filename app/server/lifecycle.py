"""
lifecycle.py — 服务器启动、关闭、handler 注册。

包含 main()、start_server_background()、BackgroundServer。
消除原 api_server.py 中 handler 注册代码的重复。
"""

import atexit
import logging
import signal
import sys
import threading

from http.server import HTTPServer

try:
    from http.server import ThreadingHTTPServer
except ImportError:
    from socketserver import ThreadingMixIn
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        pass

from app.logging_config import setup_logging


def _check_dependencies():
    """检查必要的第三方依赖是否已安装。"""
    missing = []
    for pkg, import_name in [
        ('cantools', 'cantools'),
        ('javaproperties', 'javaproperties'),
        ('websockets', 'websockets'),
        ('Jinja2', 'jinja2'),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        import logging as _log
        _log.getLogger(__name__).error(
            "缺少必要依赖: %s\n请运行: pip install -r requirements.txt",
            ', '.join(missing)
        )
        print(
            f"\n[ERROR] 缺少必要依赖: {', '.join(missing)}\n"
            f"请运行: pip install -r requirements.txt\n",
            file=sys.stderr
        )
        sys.exit(1)


_check_dependencies()

from app.services import init_session_manager
from app.models import CanDatabase
from .http_handler import ApiHandler
from .port_utils import check_port_available, handle_port_conflict

logger = logging.getLogger(__name__)

# ── 会话管理器初始化 ──
SESSION_MGR = init_session_manager()
SESSION_MGR.set_model_factory(CanDatabase)

# 同步到 http_handler 模块
import app.server.http_handler as _http_mod
_http_mod.SESSION_MGR = SESSION_MGR


def _register_all_handlers(ws_router, session_mgr, ws_transport=None):
    """注册所有 WS handler 到 router（消除重复代码）。"""
    from app.ws.handlers import (
        EditSignalHandler, AddSignalHandler, DeleteSignalHandler, BatchAddSignalsHandler,
        EditMessageHandler, AddMessageHandler, DeleteMessageHandler, DuplicateMessageHandler,
        UndoHandler, RedoHandler, SaveHandler, NewFileHandler, ImportFileHandler,
        DownloadFileHandler, CreateFileHandler, LoadFileHandler,
        SaveAsHandler, DeleteFileHandler, GetSessionsHandler, ReleaseLockHandler,
        StealLockHandler, GetSummaryHandler, GetSessionInfoHandler, GetMessageHandler,
        GetSignalErrorsHandler, GetStatusHandler, GetMessagesHandler,
        EditDatabaseHandler,
        GetSnapshotDebugHandler,
    )

    ws_router.register("edit_signal", EditSignalHandler(session_mgr))
    ws_router.register("add_signal", AddSignalHandler(session_mgr))
    ws_router.register("delete_signal", DeleteSignalHandler(session_mgr))
    ws_router.register("batch_add_signals", BatchAddSignalsHandler(session_mgr))
    ws_router.register("edit_message", EditMessageHandler(session_mgr))
    ws_router.register("add_message", AddMessageHandler(session_mgr))
    ws_router.register("delete_message", DeleteMessageHandler(session_mgr))
    ws_router.register("duplicate_message", DuplicateMessageHandler(session_mgr))
    ws_router.register("undo", UndoHandler(session_mgr))
    ws_router.register("redo", RedoHandler(session_mgr))
    ws_router.register("save", SaveHandler(session_mgr))
    ws_router.register("new_file", NewFileHandler(session_mgr))
    ws_router.register("import_file", ImportFileHandler(session_mgr))
    ws_router.register("download_file", DownloadFileHandler(session_mgr))
    ws_router.register("create_file", CreateFileHandler(session_mgr))
    ws_router.register("load_file", LoadFileHandler(session_mgr))
    ws_router.register("save_as", SaveAsHandler(session_mgr))
    ws_router.register("delete_file", DeleteFileHandler(session_mgr))
    ws_router.register("get_sessions", GetSessionsHandler(session_mgr))
    ws_router.register("release_lock", ReleaseLockHandler(session_mgr))
    ws_router.register("steal_lock", StealLockHandler(session_mgr, ws_transport))
    ws_router.register("get_summary", GetSummaryHandler(session_mgr))
    ws_router.register("get_session_info", GetSessionInfoHandler(session_mgr))
    ws_router.register("get_message", GetMessageHandler(session_mgr))
    ws_router.register("get_signal_errors", GetSignalErrorsHandler(session_mgr))
    ws_router.register("get_status", GetStatusHandler(session_mgr))
    ws_router.register("get_messages", GetMessagesHandler(session_mgr))
    ws_router.register("edit_database", EditDatabaseHandler(session_mgr))
    ws_router.register("get_snapshot_debug", GetSnapshotDebugHandler(session_mgr))


def main() -> None:
    """主函数，支持命令行参数。"""
    import argparse
    from app.version import VERSION

    # 初始化日志（默认 INFO 级别，--ws-debug 时提升到 DEBUG）
    setup_logging()

    parser = argparse.ArgumentParser(
        description='CanMatrix Editor API Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python -m app.server.lifecycle                  # 默认端口 8080
  python -m app.server.lifecycle 9090             # 指定端口 9090
  python -m app.server.lifecycle --auto-clean     # 自动清理端口冲突
  python -m app.server.lifecycle -p 9090 --auto-clean  # 组合使用
"""
    )

    parser.add_argument('port', nargs='?', type=int, default=8080,
                        help='服务器端口号 (默认: 8080)')
    parser.add_argument('-p', '--port-opt', type=int, default=None,
                        help='服务器端口号 (覆盖位置参数)')
    parser.add_argument('--auto-clean', action='store_true',
                        help='自动清理端口冲突（无需用户确认）')
    parser.add_argument('--force', action='store_true',
                        help='强制模式（同 --auto-clean）')
    parser.add_argument('--ws-debug', action='store_true',
                        help='启用 WebSocket 诊断日志（JSON lines 输出到 stdout）')

    args = parser.parse_args()

    # 根据 --ws-debug 参数提升日志级别到 DEBUG
    if args.ws_debug:
        setup_logging(level=logging.DEBUG)

    port = args.port_opt if args.port_opt is not None else args.port
    auto_clean = args.auto_clean or args.force

    if auto_clean:
        logger.info("启动模式：自动清理端口冲突")

    if not check_port_available(port):
        logger.warning("检测到端口 %d 已被占用", port)
        if not handle_port_conflict(port, auto_clean=auto_clean):
            logger.error("无法启动服务器，请解决端口冲突后重试。")
            sys.exit(1)
        if not check_port_available(port):
            logger.error("端口 %d 仍然被占用，无法启动。", port)
            sys.exit(1)

    server = ThreadingHTTPServer(("localhost", port), ApiHandler)
    logger.info("CanMatrix Editor API server running at http://localhost:%d", port)
    logger.info("Press Ctrl+C to stop.")

    # ── WebSocket 服务启动 ──
    from app.ws.transport import WsTransport, WsDiagnostics
    from app.ws.router import MessageRouter
    from app.ws.server import WsServer

    ws_diag = WsDiagnostics(enabled=args.ws_debug)
    ws_transport = WsTransport(port=port + 1, diagnostics=ws_diag)
    ws_router = MessageRouter(ws_transport, SESSION_MGR)
    _register_all_handlers(ws_router, SESSION_MGR, ws_transport)

    # ── 注册锁释放回调（在 WS 服务启动前，避免心跳定时器竞态） ──
    SESSION_MGR.set_lock_released_callback(
        lambda sid: ws_transport.broadcast_all({
            "type": "lock_stolen",
            "data": {"victim_session_id": sid}
        })
    )

    # ── 注册锁获取回调（通知 FileBrowser 文件被锁定） ──
    import os
    SESSION_MGR._file_lock.set_lock_acquired_callback(
        lambda sid, fpath: ws_transport.broadcast_all({
            "type": "file_locked",
            "data": {"session_id": sid, "file_name": os.path.basename(fpath)}
        })
    )

    ws_server = WsServer(ws_transport, ws_router)
    ws_thread = ws_server.start_in_thread()

    ApiHandler._ws_transport = ws_transport

    if args.ws_debug:
        logger.info("WebSocket diagnostics enabled")

    # ── 快照系统初始化 ──
    from app.services.snapshot import cleanup_stale_snapshots
    cleanup_stale_snapshots()  # 启动时清理过期快照
    SESSION_MGR.start_snapshot_scheduler(interval=60)  # 60s 定时器作为 kill -9 崩溃兆底

    def snapshot_on_exit():
        count = SESSION_MGR.snapshot_all_dirty()
        if count > 0:
            logger.info("Exit snapshot: %d dirty session(s) snapshotted", count)

    atexit.register(snapshot_on_exit)

    def graceful_shutdown(signum, frame):
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.info("Received %s signal, initiating graceful shutdown...", signal_name)
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")


class BackgroundServer:
    """HTTP + WS 服务器的统一生命周期管理。"""

    def __init__(self, http_server, ws_server, ws_transport, port):
        self._http = http_server
        self._ws = ws_server
        self._ws_transport = ws_transport
        self._port = port
        self._stopped = False
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        return self._port

    @property
    def ws_port(self) -> int:
        return self._port + 1

    def shutdown(self):
        with self._lock:
            if self._stopped:
                return
            self._stopped = True

        try:
            self._ws.shutdown(timeout=5)
        except Exception as e:
            logger.error("WS shutdown error: %s", e)

        try:
            self._http.shutdown()
        except Exception as e:
            logger.error("HTTP shutdown error: %s", e)

    def server_close(self):
        try:
            self._http.server_close()
        except Exception as e:
            logger.error("HTTP server_close error: %s", e)


def start_server_background(port: int = 8080) -> BackgroundServer:
    """在后台线程启动 API 服务器，返回 BackgroundServer 对象。"""
    setup_logging()
    server = ThreadingHTTPServer(("localhost", port), ApiHandler)
    logger.info("CanMatrix Editor API server running at http://localhost:%d", port)

    from app.ws.transport import WsTransport
    from app.ws.router import MessageRouter
    from app.ws.server import WsServer

    ws_transport = WsTransport(port=port + 1)
    ws_router = MessageRouter(ws_transport, SESSION_MGR)
    _register_all_handlers(ws_router, SESSION_MGR, ws_transport)

    # ── 注册锁释放回调（在 WS 服务启动前，避免心跳定时器竞态） ──
    SESSION_MGR.set_lock_released_callback(
        lambda sid: ws_transport.broadcast_all({
            "type": "lock_stolen",
            "data": {"victim_session_id": sid}
        })
    )

    # ── 注册锁获取回调（通知 FileBrowser 文件被锁定） ──
    import os
    SESSION_MGR._file_lock.set_lock_acquired_callback(
        lambda sid, fpath: ws_transport.broadcast_all({
            "type": "file_locked",
            "data": {"session_id": sid, "file_name": os.path.basename(fpath)}
        })
    )

    ws_server = WsServer(ws_transport, ws_router)
    ws_server.start_in_thread()

    ApiHandler._ws_transport = ws_transport

    if not hasattr(start_server_background, '_initialized'):
        start_server_background._initialized = True

        from app.services.snapshot import cleanup_stale_snapshots
        cleanup_stale_snapshots()
        SESSION_MGR.start_snapshot_scheduler(interval=60)

        def snapshot_on_exit():
            count = SESSION_MGR.snapshot_all_dirty()
            if count > 0:
                logger.info("Exit snapshot: %d dirty session(s) snapshotted", count)
        atexit.register(snapshot_on_exit)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return BackgroundServer(server, ws_server, ws_transport, port)


if __name__ == '__main__':
    main()
