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
    """检查必要的第三方依赖是否已安装，缺失时自动安装。"""
    import subprocess

    required = [
        ('cantools', 'cantools'),
        ('javaproperties', 'javaproperties'),
        ('websockets', 'websockets'),
        ('Jinja2', 'jinja2'),
        ('pypinyin', 'pypinyin'),
        ('watchdog', 'watchdog'),
    ]

    missing = []
    for pkg, import_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)

    if not missing:
        return

    # 尝试自动安装缺失依赖
    print(
        f"\n[INFO] 检测到缺失依赖: {', '.join(missing)}，正在自动安装...",
        file=sys.stderr
    )
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', *missing],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            if result.stderr:
                print(f"[pip stderr]:\n{result.stderr.strip()}", file=sys.stderr)
            raise subprocess.CalledProcessError(result.returncode, result.args)
        # 安装后重新验证
        still_missing = []
        for pkg, import_name in required:
            if pkg not in missing:
                continue
            try:
                __import__(import_name)
            except ImportError:
                still_missing.append(pkg)
        if not still_missing:
            return
        missing = still_missing
    except Exception as e:
        logging.getLogger(__name__).debug("Auto-install failed: %s", e)

    # 自动安装失败，给出明确错误
    _log = logging.getLogger(__name__)
    _log.error(
        "缺少必要依赖: %s\n请运行: pip install -r requirements.txt",
        ', '.join(missing)
    )
    print(
        f"\n[ERROR] 缺少必要依赖: {', '.join(missing)}\n"
        f"自动安装失败，请手动运行: pip install -r requirements.txt\n",
        file=sys.stderr
    )
    sys.exit(1)


_check_dependencies()

from app.services import init_session_manager
from app.models import CanDatabase
from .http_handler import ApiHandler
from .port_utils import check_port_available, handle_port_conflict, find_available_port
from app.auth import init_auth_service

logger = logging.getLogger(__name__)

# ── 会话管理器初始化 ──
SESSION_MGR = init_session_manager()
SESSION_MGR.set_model_factory(CanDatabase)

# ── 认证服务初始化 ──
AUTH_SERVICE = init_auth_service()

# ⚙️ 顺序约束：SESSION_MGR 和 AUTH_SERVICE 必须在 HTTP server 启动前赋值。
import app.server.http_handler as _http_mod
_http_mod.SESSION_MGR = SESSION_MGR
_http_mod.AUTH_SERVICE = AUTH_SERVICE


def _register_all_handlers(ws_router, session_mgr, ws_transport=None):
    """注册所有 WS handler 到 router（消除重复代码）。"""
    from app.ws.handlers import (
        EditSignalHandler, AddSignalHandler, DeleteSignalHandler, BatchAddSignalsHandler,
        EditMessageHandler, AddMessageHandler, DeleteMessageHandler,
        UndoHandler, RedoHandler, SaveHandler, NewFileHandler, ImportFileHandler,
        DownloadFileHandler, CreateFileHandler, LoadFileHandler,
        SaveAsHandler, DeleteFileHandler, GetSessionsHandler, ReleaseLockHandler,
        StealLockHandler, GetSummaryHandler, GetSessionInfoHandler, GetMessageHandler,
        GetDataErrorsHandler, GetStatusHandler, GetMessagesHandler,
        EditDatabaseHandler,
        GetSnapshotDebugHandler,
        AddValueTableHandler, UpdateValueTableHandler, DeleteValueTableHandler,
        RenameValueTableHandler, GetValueTablesHandler,
        BatchEditSignalsHandler, BatchDeleteSignalsHandler,
        BatchEditMessagesHandler, BatchDeleteMessagesHandler,
        GetSaveDiffHandler,
    )

    ws_router.register("edit_signal", EditSignalHandler(session_mgr))
    ws_router.register("add_signal", AddSignalHandler(session_mgr))
    ws_router.register("delete_signal", DeleteSignalHandler(session_mgr))
    ws_router.register("batch_add_signals", BatchAddSignalsHandler(session_mgr))
    ws_router.register("edit_message", EditMessageHandler(session_mgr))
    ws_router.register("add_message", AddMessageHandler(session_mgr))
    ws_router.register("delete_message", DeleteMessageHandler(session_mgr))
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
    ws_router.register("get_data_errors", GetDataErrorsHandler(session_mgr))
    ws_router.register("get_status", GetStatusHandler(session_mgr))
    ws_router.register("get_messages", GetMessagesHandler(session_mgr))
    ws_router.register("edit_database", EditDatabaseHandler(session_mgr))
    ws_router.register("get_snapshot_debug", GetSnapshotDebugHandler(session_mgr))
    ws_router.register("add_value_table", AddValueTableHandler(session_mgr))
    ws_router.register("update_value_table", UpdateValueTableHandler(session_mgr))
    ws_router.register("delete_value_table", DeleteValueTableHandler(session_mgr))
    ws_router.register("rename_value_table", RenameValueTableHandler(session_mgr))
    ws_router.register("get_value_tables", GetValueTablesHandler(session_mgr))
    ws_router.register("batch_edit_signals", BatchEditSignalsHandler(session_mgr))
    ws_router.register("batch_delete_signals", BatchDeleteSignalsHandler(session_mgr))
    ws_router.register("batch_edit_messages", BatchEditMessagesHandler(session_mgr))
    ws_router.register("batch_delete_messages", BatchDeleteMessagesHandler(session_mgr))
    ws_router.register("get_save_diff", GetSaveDiffHandler(session_mgr))


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
    parser.add_argument('--no-browser', action='store_true',
                        help='启动后不自动打开浏览器')
    parser.add_argument('--host', type=str, default='localhost',
                        help='HTTP 绑定地址 (默认: localhost, LAN 部署时传 0.0.0.0)')

    args = parser.parse_args()

    # 根据 --ws-debug 参数提升日志级别到 DEBUG
    if args.ws_debug:
        setup_logging(level=logging.DEBUG)

    port = args.port_opt if args.port_opt is not None else args.port
    auto_clean = args.auto_clean or args.force
    host = args.host

    if auto_clean:
        logger.info("启动模式：自动清理端口冲突")

    # 检查 HTTP + WS 双端口
    if not check_port_available(port) or not check_port_available(port + 1):
        logger.info("端口 %d/%d 不可用，扫描可用端口...", port, port + 1)
        alt = find_available_port(start=port + 2)
        if alt is not None:
            logger.info("自动切换到端口 %d/%d", alt, alt + 1)
            port = alt
        else:
            logger.error("在 %d-%d 范围内未找到可用端口对。", port, port + 21)
            logger.info("提示: 使用 --auto-clean 尝试清理，或手动指定其他端口。")
            sys.exit(1)

    server = ThreadingHTTPServer((host, port), ApiHandler)
    logger.info("CanMatrix Editor API server running at http://%s:%d", host, port)
    logger.info("WS port: %d", port + 1)
    logger.info("Press Ctrl+C to stop.")

    # ── WebSocket 服务启动 ──
    from app.ws.transport import WsTransport, WsDiagnostics
    from app.ws.router import MessageRouter
    from app.ws.server import WsServer

    ws_diag = WsDiagnostics(enabled=args.ws_debug)
    ws_transport = WsTransport(port=port + 1, diagnostics=ws_diag)
    ws_router = MessageRouter(ws_transport, SESSION_MGR, auth_service=AUTH_SERVICE)
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

    # ── 配置热重载 watchdog ──
    AUTH_SERVICE.start_watchdog()

    # ── 自动打开浏览器 ──
    if not args.no_browser:
        import webbrowser
        url = f"http://localhost:{port}" if host == 'localhost' else f"http://{host}:{port}"
        logger.info("服务已就绪，正在打开浏览器: %s", url)
        threading.Timer(0.5, webbrowser.open, args=[url]).start()

    # 不注册自定义 SIGINT 处理器，依赖 Python 默认行为：
    # Ctrl+C → KeyboardInterrupt → 中断 serve_forever()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        AUTH_SERVICE.stop_watchdog()
        # 关闭 WS server（独立线程，安全调用）
        try:
            ws_server.shutdown(timeout=3)
        except Exception as e:
            logger.error("WS shutdown error: %s", e)
        # 关闭 HTTP server（serve_forever 已返回，不会死锁）
        try:
            server.shutdown()
            server.server_close()
        except Exception as e:
            logger.error("HTTP shutdown error: %s", e)


class BackgroundServer:
    """HTTP + WS 服务器的统一生命周期管理。"""

    def __init__(self, http_server, ws_server, ws_transport, port, auth_service=None):
        self._http = http_server
        self._ws = ws_server
        self._ws_transport = ws_transport
        self._port = port
        self._auth_service = auth_service
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

        if self._auth_service:
            self._auth_service.stop_watchdog()

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


def start_server_background(port: int = 8080, host: str = 'localhost') -> BackgroundServer:
    """在后台线程启动 API 服务器，返回 BackgroundServer 对象。"""
    setup_logging()

    # 端口可用性检查（HTTP + WS 双端口）
    if not check_port_available(port) or not check_port_available(port + 1):
        alt = find_available_port(start=port)
        if alt is not None:
            logger.info("start_server_background: 端口 %d 不可用，切换到 %d", port, alt)
            port = alt
        else:
            raise RuntimeError(f"端口 {port}/{port+1} 不可用且无替代端口")

    server = ThreadingHTTPServer((host, port), ApiHandler)
    logger.info("CanMatrix Editor API server running at http://%s:%d", host, port)

    from app.ws.transport import WsTransport
    from app.ws.router import MessageRouter
    from app.ws.server import WsServer

    ws_transport = WsTransport(port=port + 1)
    ws_router = MessageRouter(ws_transport, SESSION_MGR, auth_service=AUTH_SERVICE)
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
        AUTH_SERVICE.start_watchdog()

        def snapshot_on_exit():
            count = SESSION_MGR.snapshot_all_dirty()
            if count > 0:
                logger.info("Exit snapshot: %d dirty session(s) snapshotted", count)
        atexit.register(snapshot_on_exit)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return BackgroundServer(server, ws_server, ws_transport, port, auth_service=AUTH_SERVICE)


if __name__ == '__main__':
    main()
