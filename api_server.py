#!/usr/bin/env python3
"""
CanMatrix Editor - API Server (WebSocket 模式)
前端通过 WebSocket 进行所有数据交互，HTTP 仅保留静态文件服务 + 健康检查 + 诊断。

会话模型：
  - 每个浏览器标签页对应一个独立 session
  - 每个 session 绑定一个数据文件，所有变更自动落盘
  - 浏览器意外关闭后可通过 localStorage 中的 session_id 恢复
"""

import json
import os
import signal
import atexit
import sys
import threading
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from version import VERSION
from typing import Any

try:
    from http.server import ThreadingHTTPServer
    THREADING_AVAILABLE = True
except ImportError:
    from socketserver import ThreadingMixIn
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        pass
    THREADING_AVAILABLE = True

# ── 会话管理器 ──────────────────────────────────────────────────────────────────
from session_manager import init_session_manager

SESSION_MGR = init_session_manager()

# ── 数据模型（统一从 models.py 导入）────────────────────────────────────
from models import CanDatabase


# ── 注入模型工厂 ──
SESSION_MGR.set_model_factory(CanDatabase)


def _resp(success: bool, data: Any = None, error: str = "", details: dict | None = None) -> dict:
    """统一JSON响应格式。"""
    result = {"success": success, "data": data, "error": error}
    if details is not None:
        result["details"] = details
    return result


# ── API 请求处理器 ────────────────────────────────────────────────────────────

class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    _last_status: int = 200  # tracked for compact log

    def log_message(self, fmt: str, *args: Any) -> None:
        """Suppress default access log — we emit a single compact line per request."""
        pass

    # ── CORS ──

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Id")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    # ── 工具方法 ──

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()
        self._last_status = status

    def _path_parts(self) -> list[str]:
        """返回路径部分（不含query string），以'/'分割并过滤空字符串。"""
        parsed = urllib.parse.urlparse(self.path)
        return [p for p in parsed.path.split("/") if p]

    # ── 静态文件服务 ──

    def _serve_static(self) -> None:
        """Serve static files. New Vue frontend in dist/, legacy HTML in root."""
        import mimetypes

        parsed = urllib.parse.urlparse(self.path)
        filepath = parsed.path.lstrip("/")
        if not filepath:
            filepath = "index.html"

        safe_path = os.path.normpath(filepath)
        if safe_path.startswith(".."):
            self._send_json(403, _resp(False, error="Forbidden"))
            return

        # PyInstaller 打包后 __file__ 指向 _MEIPASS 临时目录，前端资源在那里
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        # Legacy HTML always served from root
        if safe_path == "canmatrix_web_editor.html":
            full_path = os.path.join(base_dir, safe_path)
        else:
            # New Vue frontend assets live in dist/
            full_path = os.path.join(base_dir, "dist", safe_path)
            if not os.path.isfile(full_path):
                full_path = os.path.join(base_dir, safe_path)

        if not os.path.isfile(full_path):
            self._send_json(404, _resp(False, error="Not found"))
            return

        mime_type, _ = mimetypes.guess_type(full_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self._last_status = 200
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(content)
            self.wfile.flush()
        except Exception as e:
            self._send_json(500, _resp(False, error=str(e)))

    # ── 路由（GET /api/status + GET /api/diag + GET /api/export + POST /api/release + 静态文件）──

    def do_GET(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if parts == ["api", "status"]:
                self._get_status()
            elif parts == ["api", "diag"]:
                self._get_diag()
            elif parts == ["api", "export"]:
                self._get_export()
            elif parts == ["api", "version"]:
                self._get_version()
            else:
                self._serve_static()
        except Exception as e:
            print(f"[ERROR] do_GET: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] {self._last_status} GET {self.path} +{elapsed:.1f}ms")

    def do_POST(self) -> None:
        """POST /api/release 用于 navigator.sendBeacon（页面关闭时释放文件锁）。
        其他 POST 端点已迁移至 WebSocket。
        """
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if parts == ["api", "release"]:
                self._post_release()
            else:
                self._last_status = 404
                self._send_json(404, _resp(False, error="Not found. All CRUD operations moved to WebSocket."))
        except Exception as e:
            print(f"[ERROR] do_POST: {e}", flush=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] {self._last_status} POST {self.path} +{elapsed:.1f}ms")

    def do_PUT(self) -> None:
        """所有 PUT 端点已迁移至 WebSocket，返回 404。"""
        self._last_status = 404
        try:
            self._send_json(404, _resp(False, error="Not found. All CRUD operations moved to WebSocket."))
        except:
            pass
        print(f"[API] 404 PUT {self.path} (moved to WS)")

    def do_DELETE(self) -> None:
        """所有 DELETE 端点已迁移至 WebSocket，返回 404。"""
        self._last_status = 404
        try:
            self._send_json(404, _resp(False, error="Not found. All CRUD operations moved to WebSocket."))
        except:
            pass
        print(f"[API] 404 DELETE {self.path} (moved to WS)")

    # ── 端点实现 ──

    def _get_status(self) -> None:
        """GET /api/status - 轻量健康检查（所有数据操作已迁移至 WS）。"""
        self._send_json(200, _resp(True, {"status": "ok"}))

    def _get_version(self) -> None:
        """GET /api/version - 返回应用版本号。"""
        self._send_json(200, _resp(True, VERSION))

    def _post_release(self) -> None:
        """POST /api/release - 释放文件锁（navigator.sendBeacon 专用）。

        页面关闭/刷新时通过 sendBeacon 释放锁，支持 URL 查询参数 ?sid=xxx。
        sendBeacon 不支持自定义请求头，因此从 URL 参数读取 session ID。
        """
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        sid = params.get("sid", [""])[0]
        abort = params.get("abort", [""])[0] in ("1", "true", "yes")
        if sid:
            SESSION_MGR.release_session(sid, abort=abort)
        self._send_json(200, _resp(True))

    def _get_export(self) -> None:
        """GET /api/export?sid=xxx&fmt=properties|dbc - WS 断开时的 HTTP 导出降级端点。

        直接读取内存中的会话数据进行序列化，不依赖 WebSocket 连接。
        用于保存失败后用户点击「导出备份」的场景。
        """
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        sid = params.get("sid", [""])[0]
        fmt = params.get("fmt", ["properties"])[0]

        if not sid:
            self._send_json(400, _resp(False, error="sid is required"))
            return

        session = SESSION_MGR.get(sid)
        if not session:
            self._send_json(404, _resp(False, error="Session not found"))
            return

        try:
            if fmt == "dbc":
                content = session.db.to_dbc_str()
                ext = ".dbc"
                mime = "application/octet-stream"
            elif fmt == "properties":
                content = session.db.to_properties_str()
                ext = ".properties"
                mime = "text/plain"
            elif fmt == "c_header":
                content = session.db.to_c_header_str()
                ext = "_signals.h"
                mime = "text/plain"
            elif fmt == "c_source":
                content = session.db.to_c_source_str()
                ext = "_signals.c"
                mime = "text/plain"
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(500, _resp(False, error=f"Export failed: {e}"))
            return

        file_name = session.db.name or "export"
        if not file_name.endswith(ext):
            file_name = file_name.rsplit(".", 1)[0] + ext

        payload = content.encode("utf-8")
        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'attachment; filename="{file_name}"')
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()

    def _get_diag(self) -> None:
        """GET /api/diag - 诊断快照（仅 --ws-debug 模式下可用）"""
        # 延迟导入，避免循环依赖
        try:
            from ws_transport import WsTransport
        except ImportError:
            self._send_json(404, _resp(False, error="WS module not available"))
            return
        # 通过全局变量获取 transport（main() 中设置）
        transport = getattr(self.__class__, '_ws_transport', None)
        if not transport or not transport.diag.enabled:
            self._send_json(404, _resp(False, error="Diagnostics not enabled"))
            return
        self._send_json(200, _resp(True, transport.diag.snapshot()))


# ── 启动服务器 ────────────────────────────────────────────────────────────────

def check_port_available(port: int) -> bool:
    """检查端口是否可用。"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('localhost', port))
            return True
        except OSError:
            return False


def find_processes_on_port(port: int) -> list:
    """查找占用指定端口的进程。
    
    Windows: 使用 netstat -ano
    Linux/Mac: 使用 lsof 或 ss
    """
    import subprocess
    import platform
    
    system = platform.system()
    
    try:
        if system == 'Windows':
            # Windows: 使用 netstat -ano
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            pids = []
            for line in result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    # 提取 PID（最后一列）
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit():
                            pids.append(int(pid))
            
            return pids
        
        elif system in ('Linux', 'Darwin'):  # Darwin = macOS
            # Linux: 使用 ss 或 lsof
            # 优先使用 ss（更快）
            try:
                result = subprocess.run(
                    ['ss', '-tlnp', f'sport = :{port}'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                pids = []
                for line in result.stdout.split('\n'):
                    # ss 输出示例: LISTEN  0  128  0.0.0.0:8080  0.0.0.0:*  users:(("python",pid=12345,fd=3))
                    if 'pid=' in line:
                        import re
                        pid_match = re.search(r'pid=(\d+)', line)
                        if pid_match:
                            pids.append(int(pid_match.group(1)))
                
                if pids:
                    return pids
            except FileNotFoundError:
                # ss 不可用，尝试 lsof
                pass
            
            # 使用 lsof
            result = subprocess.run(
                ['lsof', '-i', f':{port}', '-t'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                pids = []
                for line in result.stdout.strip().split('\n'):
                    if line.strip().isdigit():
                        pids.append(int(line.strip()))
                return pids
        
        return []
    except Exception:
        return []


def kill_process(pid: int) -> bool:
    """终止指定进程。
    
    Windows: 使用 taskkill
    Linux/Mac: 使用 kill
    """
    import subprocess
    import platform
    
    try:
        system = platform.system()
        
        if system == 'Windows':
            subprocess.run(
                ['taskkill', '/F', '/PID', str(pid)],
                capture_output=True,
                timeout=5
            )
        elif system in ('Linux', 'Darwin'):
            subprocess.run(
                ['kill', '-9', str(pid)],
                capture_output=True,
                timeout=5
            )
        else:
            return False
        
        return True
    except Exception:
        return False


def handle_port_conflict(port: int, auto_clean: bool = False) -> bool:
    """处理端口冲突，返回是否成功解决。
    
    Args:
        port: 端口号
        auto_clean: 是否自动清理（无需用户确认）
    """
    import platform
    
    print(f"\n[ERROR] 错误：端口 {port} 已被占用")
    print("=" * 60)
    
    system = platform.system()
    
    # 查找占用端口的进程
    pids = find_processes_on_port(port)
    
    if not pids:
        print(f"端口 {port} 被占用，但无法检测到占用进程。")
        print("可能的原因：")
        print("  1. 其他程序正在使用该端口")
        print("  2. 端口处于 TIME_WAIT 状态（等待关闭）")
        print("\n建议操作：")
        print(f"  - 使用其他端口启动：python api_server.py <端口号>")
        print(f"  - 等待几秒后重试（如果是 TIME_WAIT 状态）")
        return False
    
    # 检查是否是 api_server.py 进程（仅 Windows 支持详细检查）
    api_server_pids = []
    
    if system == 'Windows':
        import subprocess
        try:
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            for line in result.stdout.split('\n'):
                if 'python.exe' in line.lower():
                    for pid in pids:
                        if str(pid) in line:
                            api_server_pids.append(pid)
        except Exception:
            pass
    else:
        # Linux/Mac: 简化处理，假设所有占用端口的进程都是目标进程
        # 可以通过 /proc/<pid>/cmdline 或 ps 命令进一步检查
        api_server_pids = pids[:10]  # 限制最多处理 10 个进程
    
    if api_server_pids:
        print(f"检测到 {len(api_server_pids)} 个占用端口的进程：")
        for pid in api_server_pids:
            print(f"  - PID: {pid}")
        print()
        
        # 根据 auto_clean 参数决定是否跳过确认
        if auto_clean:
            print("[Auto-cleaning] 正在终止旧进程...")
        else:
            # 询问是否自动清理
            try:
                response = input("是否自动终止旧进程并重启？(Y/n): ").strip().lower()
                if response not in ['', 'y', 'yes']:
                    print("\n已取消自动清理。")
                    print("\n手动操作建议：")
                    if system == 'Windows':
                        print("  Windows: taskkill /F /PID <进程ID>")
                        print("  或使用任务管理器终止 python.exe 进程")
                    elif system == 'Linux':
                        print("  Linux: kill -9 <进程ID>")
                        print("  或使用 pkill -f api_server.py")
                    elif system == 'Darwin':
                        print("  macOS: kill -9 <进程ID>")
                        print("  或使用活动监视器终止进程")
                    else:
                        print(f"  {system}: kill <进程ID>")
                    return False
            except (KeyboardInterrupt, EOFError):
                print("\n\n已取消操作。")
                return False
            
            print("\n正在终止旧进程...")
        
        # 执行清理操作
        for pid in api_server_pids:
            if kill_process(pid):
                print(f"  [OK] 已终止进程 {pid}")
            else:
                print(f"  [ERROR] 无法终止进程 {pid}")
        
        # 等待端口释放
        print("等待端口释放...")
        import time
        for i in range(10):
            if check_port_available(port):
                print("[OK] 端口已释放")
                return True
            time.sleep(0.5)
        
        print("[WARN] 端口仍未释放，请手动检查")
        return False
    else:
        print(f"端口 {port} 被其他程序占用（PID: {', '.join(map(str, pids))}）")
        print("\n建议操作：")
        print(f"  1. 终止占用端口的程序")
        print(f"  2. 使用其他端口启动：python api_server.py <端口号>")
        return False


def main() -> None:
    """主函数，支持命令行参数。"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='CanMatrix Editor API Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python api_server.py                  # 默认端口 8080
  python api_server.py 9090             # 指定端口 9090
  python api_server.py --auto-clean     # 自动清理端口冲突
  python api_server.py -p 9090 --auto-clean  # 组合使用
"""
    )
    
    parser.add_argument(
        'port',
        nargs='?',
        type=int,
        default=8080,
        help='服务器端口号 (默认: 8080)'
    )
    
    parser.add_argument(
        '-p', '--port-opt',
        type=int,
        default=None,
        help='服务器端口号 (覆盖位置参数)'
    )
    
    parser.add_argument(
        '--auto-clean',
        action='store_true',
        help='自动清理端口冲突（无需用户确认）'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='强制模式（同 --auto-clean）'
    )
    
    parser.add_argument(
        '--ws-debug',
        action='store_true',
        help='启用 WebSocket 诊断日志（JSON lines 输出到 stdout）'
    )
    
    args = parser.parse_args()
    
    # 确定端口号（--port-opt 优先于位置参数）
    port = args.port_opt if args.port_opt is not None else args.port
    auto_clean = args.auto_clean or args.force
    
    if auto_clean:
        print(f"\n[Auto-cleaning] 启动模式：自动清理端口冲突")
    
    # 检查端口是否可用
    if not check_port_available(port):
        print(f"\n[WARN] 检测到端口 {port} 已被占用")
        
        # 尝试处理端口冲突
        if not handle_port_conflict(port, auto_clean=auto_clean):
            print("\n[ERROR] 无法启动服务器，请解决端口冲突后重试。")
            sys.exit(1)
        
        # 再次检查端口
        if not check_port_available(port):
            print(f"\n[ERROR] 端口 {port} 仍然被占用，无法启动。")
            sys.exit(1)
    
    # 1. ThreadingHTTPServer（WS 多线程并发安全）
    # 2. 启动 WS 服务（port + 1）
    server = ThreadingHTTPServer(("localhost", port), ApiHandler)
    print(f"\nCanMatrix Editor API server running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    
    # ── WebSocket 服务启动 ──
    from ws_transport import WsTransport, WsDiagnostics
    from ws_router import MessageRouter
    from ws_server import WsServer
    from handlers import (
        EditSignalHandler, AddSignalHandler, DeleteSignalHandler, BatchAddSignalsHandler,
        EditMessageHandler, AddMessageHandler, DeleteMessageHandler, DuplicateMessageHandler,
        UndoHandler, RedoHandler, SaveHandler, NewFileHandler, ImportFileHandler,
        DownloadFileHandler, CreateFileHandler, LoadFileHandler,
        RenameSessionHandler, DeleteFileHandler, GetSessionsHandler, ReleaseLockHandler,
        StealLockHandler, GetSummaryHandler, GetSessionInfoHandler, GetMessageHandler,
        GetSignalErrorsHandler, GetStatusHandler, GetMessagesHandler,
    )
    
    ws_diag = WsDiagnostics(enabled=args.ws_debug)
    ws_transport = WsTransport(port=port + 1, diagnostics=ws_diag)
    ws_router = MessageRouter(ws_transport, SESSION_MGR)
    
    # ─ 注册所有 handler ──
    ws_router.register("edit_signal", EditSignalHandler(SESSION_MGR))
    ws_router.register("add_signal", AddSignalHandler(SESSION_MGR))
    ws_router.register("delete_signal", DeleteSignalHandler(SESSION_MGR))
    ws_router.register("batch_add_signals", BatchAddSignalsHandler(SESSION_MGR))
    ws_router.register("edit_message", EditMessageHandler(SESSION_MGR))
    ws_router.register("add_message", AddMessageHandler(SESSION_MGR))
    ws_router.register("delete_message", DeleteMessageHandler(SESSION_MGR))
    ws_router.register("duplicate_message", DuplicateMessageHandler(SESSION_MGR))
    ws_router.register("undo", UndoHandler(SESSION_MGR))
    ws_router.register("redo", RedoHandler(SESSION_MGR))
    ws_router.register("save", SaveHandler(SESSION_MGR))
    ws_router.register("new_file", NewFileHandler(SESSION_MGR))
    ws_router.register("import_file", ImportFileHandler(SESSION_MGR))
    ws_router.register("download_file", DownloadFileHandler(SESSION_MGR))
    ws_router.register("create_file", CreateFileHandler(SESSION_MGR))
    ws_router.register("load_file", LoadFileHandler(SESSION_MGR))
    ws_router.register("rename_session", RenameSessionHandler(SESSION_MGR))
    ws_router.register("delete_file", DeleteFileHandler(SESSION_MGR))
    ws_router.register("get_sessions", GetSessionsHandler(SESSION_MGR))
    ws_router.register("release_lock", ReleaseLockHandler(SESSION_MGR))
    ws_router.register("steal_lock", StealLockHandler(SESSION_MGR, ws_transport))
    ws_router.register("get_summary", GetSummaryHandler(SESSION_MGR))
    ws_router.register("get_session_info", GetSessionInfoHandler(SESSION_MGR))
    ws_router.register("get_message", GetMessageHandler(SESSION_MGR))
    ws_router.register("get_signal_errors", GetSignalErrorsHandler(SESSION_MGR))
    ws_router.register("get_status", GetStatusHandler(SESSION_MGR))
    ws_router.register("get_messages", GetMessagesHandler(SESSION_MGR))
    
    ws_server = WsServer(ws_transport, ws_router)
    ws_thread = ws_server.start_in_thread()
    
    # ── 注册锁释放回调（WS 广播 lock_stolen 到所有客户端） ──
    SESSION_MGR.set_lock_released_callback(
        lambda sid: ws_transport.broadcast_all({
            "type": "lock_stolen",
            "data": {"victim_session_id": sid}
        })
    )
    
    # 让 ApiHandler 能访问 ws_transport（供 _get_diag 使用）
    ApiHandler._ws_transport = ws_transport
    
    if args.ws_debug:
        print(f"[WS-DIAG] WebSocket diagnostics enabled")
    
    # ── 优雅关闭机制（Graceful Shutdown） ──
    
    def save_all_sessions():
        """保存所有活跃会话（优雅关闭）。"""
        print("\n[INFO] Saving all active sessions...")
        count = SESSION_MGR.save_all_dirty()
        if count > 0:
            print(f"[INFO] Save complete: {count} session(s) saved")
        else:
            print(f"[INFO] No modified sessions to save.")
    
    # 注册退出处理器（进程正常退出时触发）
    atexit.register(save_all_sessions)

    # 注册信号处理器（捕获 Ctrl+C 和 kill 信号）
    def graceful_shutdown(signum, frame):
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        print(f"\n[INFO] Received {signal_name} signal, initiating graceful shutdown...")
        sys.exit(0)  # 触发 atexit
    
    # 跨平台信号注册（Windows 支持 SIGINT，Unix 支持 SIGTERM）
    signal.signal(signal.SIGINT, graceful_shutdown)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, graceful_shutdown)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


class BackgroundServer:
    """HTTP + WS 服务器的统一生命周期管理。

    - 幂等 shutdown（可安全多次调用）
    - 有序关闭：先 WS 后 HTTP
    - 异常隔离：任一组件关闭失败不影响其他组件
    """

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
        """有序关闭 HTTP + WS 服务器。幂等，线程安全。"""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True

        try:
            self._ws.shutdown(timeout=5)
        except Exception as e:
            print(f"[BackgroundServer] WS shutdown error: {e}")

        try:
            self._http.shutdown()
        except Exception as e:
            print(f"[BackgroundServer] HTTP shutdown error: {e}")

    def server_close(self):
        """关闭 HTTP server socket（释放端口）。"""
        try:
            self._http.server_close()
        except Exception as e:
            print(f"[BackgroundServer] HTTP server_close error: {e}")


def start_server_background(port: int = 8080) -> "BackgroundServer":
    """在后台线程启动 API 服务器，返回 BackgroundServer 对象供外部控制关闭。
    用于桌面应用（pywebview）集成。
    """
    server = ThreadingHTTPServer(("localhost", port), ApiHandler)
    print(f"\nCanMatrix Editor API server running at http://localhost:{port}")

    # ── WebSocket 服务启动（桌面版） ──
    from ws_transport import WsTransport, WsDiagnostics
    from ws_router import MessageRouter
    from ws_server import WsServer
    from handlers import (
        EditSignalHandler, AddSignalHandler, DeleteSignalHandler, BatchAddSignalsHandler,
        EditMessageHandler, AddMessageHandler, DeleteMessageHandler, DuplicateMessageHandler,
        UndoHandler, RedoHandler, SaveHandler, NewFileHandler, ImportFileHandler,
        DownloadFileHandler, CreateFileHandler, LoadFileHandler,
        RenameSessionHandler, DeleteFileHandler, GetSessionsHandler, ReleaseLockHandler,
        StealLockHandler, GetSummaryHandler, GetSessionInfoHandler, GetMessageHandler,
        GetSignalErrorsHandler, GetStatusHandler, GetMessagesHandler,
    )
    
    ws_transport = WsTransport(port=port + 1)
    ws_router = MessageRouter(ws_transport, SESSION_MGR)
    ws_router.register("edit_signal", EditSignalHandler(SESSION_MGR))
    ws_router.register("add_signal", AddSignalHandler(SESSION_MGR))
    ws_router.register("delete_signal", DeleteSignalHandler(SESSION_MGR))
    ws_router.register("batch_add_signals", BatchAddSignalsHandler(SESSION_MGR))
    ws_router.register("edit_message", EditMessageHandler(SESSION_MGR))
    ws_router.register("add_message", AddMessageHandler(SESSION_MGR))
    ws_router.register("delete_message", DeleteMessageHandler(SESSION_MGR))
    ws_router.register("duplicate_message", DuplicateMessageHandler(SESSION_MGR))
    ws_router.register("undo", UndoHandler(SESSION_MGR))
    ws_router.register("redo", RedoHandler(SESSION_MGR))
    ws_router.register("save", SaveHandler(SESSION_MGR))
    ws_router.register("new_file", NewFileHandler(SESSION_MGR))
    ws_router.register("import_file", ImportFileHandler(SESSION_MGR))
    ws_router.register("download_file", DownloadFileHandler(SESSION_MGR))
    ws_router.register("create_file", CreateFileHandler(SESSION_MGR))
    ws_router.register("load_file", LoadFileHandler(SESSION_MGR))
    ws_router.register("rename_session", RenameSessionHandler(SESSION_MGR))
    ws_router.register("delete_file", DeleteFileHandler(SESSION_MGR))
    ws_router.register("get_sessions", GetSessionsHandler(SESSION_MGR))
    ws_router.register("release_lock", ReleaseLockHandler(SESSION_MGR))
    ws_router.register("steal_lock", StealLockHandler(SESSION_MGR, ws_transport))
    ws_router.register("get_summary", GetSummaryHandler(SESSION_MGR))
    ws_router.register("get_session_info", GetSessionInfoHandler(SESSION_MGR))
    ws_router.register("get_message", GetMessageHandler(SESSION_MGR))
    ws_router.register("get_signal_errors", GetSignalErrorsHandler(SESSION_MGR))
    ws_router.register("get_status", GetStatusHandler(SESSION_MGR))
    ws_router.register("get_messages", GetMessagesHandler(SESSION_MGR))
    ws_server = WsServer(ws_transport, ws_router)
    ws_server.start_in_thread()
    
    SESSION_MGR.set_lock_released_callback(
        lambda sid: ws_transport.broadcast_all({
            "type": "lock_stolen",
            "data": {"victim_session_id": sid}
        })
    )
    
    # 让 ApiHandler 能访问 ws_transport（供 _get_diag 使用）
    ApiHandler._ws_transport = ws_transport

    # 防止重启时 atexit 重复注册
    if not hasattr(start_server_background, '_initialized'):
        start_server_background._initialized = True

        # 注册 atexit 保存
        def save_all_sessions():
            print("\n[INFO] Saving all active sessions...")
            count = SESSION_MGR.save_all_dirty()
            if count > 0:
                print(f"[INFO] Save complete: {count} session(s) saved")
        atexit.register(save_all_sessions)

    # 在守护线程中运行 serve_forever
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return BackgroundServer(server, ws_server, ws_transport, port)


if __name__ == "__main__":
    main()
