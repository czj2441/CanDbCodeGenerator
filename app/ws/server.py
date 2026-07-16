"""
ws_server.py — WebSocket 服务端

连接生命周期管理 + full_sync 构建 + 服务启动。
"""

import asyncio
import json
import logging
import threading

import websockets

from app.services import get_session_manager
from .transport import WsTransport
from .router import MessageRouter
from app.version import VERSION

logger = logging.getLogger(__name__)


class WsServer:
    """WebSocket 服务端 — 管理连接生命周期 + 消息路由。"""

    def __init__(self, transport: WsTransport, router: MessageRouter):
        self._transport = transport
        self._router = router
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    # ── 连接生命周期协程 ──

    async def _handler(self, ws):
        """单个 WS 连接的完整生命周期：
        hello 握手 → register → full_sync → 消息循环 → cleanup
        """
        session_id = None
        try:
            # ── 等待 hello ──
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                if self._transport.diag.enabled:
                    with self._transport.diag._counter_lock:
                        self._transport.diag.hello_timeouts += 1
                await ws.close(4001, "hello timeout")
                return

            msg = json.loads(raw)
            if msg.get("type") != "hello":
                await ws.close(4002, "expected hello")
                return

            session_id = msg.get("session_id", "")

            sm = get_session_manager()

            # ── 验证 session ──
            if session_id:
                session = sm.get(session_id)
                if not session:
                    # 旧 session 已丢失（后端重启/超时清理）
                    # 关闭连接让前端清理状态后重连，不自动创建幻影会话
                    logger.info("WS connection rejected: session_id=%s not found", session_id[:8])
                    await ws.close(4003, "session_not_found")
                    return

            # ── 注册 + full_sync（仅有有效 session 时） ──
            if session_id:
                self._transport.register(session_id, ws)
                sm.update_heartbeat(session_id)
                logger.info("WS connected: session=%s", session_id[:8])
                # 发送服务端版本号（前端用于校验）
                await ws.send(json.dumps({"type": "server_version", "data": VERSION}))
                await self._send_full_sync(ws, session_id)

            # ── 消息循环 ──
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("WS received malformed JSON, dropping message")
                    continue

                if msg.get("type") == "ping":
                    # 心跳 + 锁续期 + 版本号推送
                    try:
                        await ws.send(json.dumps({"type": "pong", "data": VERSION}))
                        sm.update_heartbeat(session_id)
                    except Exception as e:
                        logger.error("WS ping handler error: %s", e)

                elif "requestId" in msg:
                    # 请求-响应类型：路由到 handler
                    result = await self._router.dispatch(ws, msg)

                    # session 切换同步（new_file/import_file/load_session/save_as 可能改变 session_id）
                    if result and result.new_session_id:
                        self._transport.unregister(session_id, ws)
                        sm.release_session(session_id, abort=True)  # 立即释放旧 session 文件锁
                        logger.info("WS session switch: %s -> %s", session_id[:8], result.new_session_id[:8])
                        session_id = result.new_session_id
                        self._transport.register(session_id, ws)
                        sm.update_heartbeat(session_id)
                        # session 切换后自动发送 full_sync
                        await self._send_full_sync(ws, session_id)

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error("WS handler error: %s: %s", type(e).__name__, e, exc_info=True)
        finally:
            if session_id:
                self._transport.unregister(session_id, ws)
                sm.mark_stale(session_id)
                logger.info("WS disconnected: session=%s", session_id[:8])

    # ── 全量快照 ──

    async def _send_full_sync(self, ws, session_id: str):
        """构建并发送全量快照。在 db.with_lock() 内完成数据遍历。"""
        sm = get_session_manager()
        session = sm.get(session_id)
        if not session:
            return

        db = session.db
        with db.with_lock():
            messages_data = [
                {"id": mid, "id_hex": f"0x{mid:X}", "name": m.name,
                 "dlc": m.dlc, "cycle_time": m.cycle_time,
                 "signal_count": len(m.signals)}
                for mid, m in sorted(db.messages.items())
            ]
            status = {
                "modified": db.modified,
                "undo_count": len(session.undo_stack),
                "redo_count": len(session.redo_stack),
                "save_error": session.save_error
            }
            version = db.data_version

        lock_held = sm.has_lock(session_id)

        msg = {
            "type": "full_sync",
            "data_version": version,
            "data": {
                "messages": messages_data,
                "status": status,
                "lock_status": "held" if lock_held else "lost"
            }
        }

        if self._transport.diag.enabled:
            with self._transport.diag._counter_lock:
                pass
            self._transport.diag.info("full_sync_built",
                                       messages=len(messages_data))

        await ws.send(json.dumps(msg, ensure_ascii=False))
        logger.info("full_sync sent: session=%s messages=%d version=%d",
                    session_id[:8], len(messages_data), version)

    # ── 服务启动 ──

    async def _serve(self):
        """启动 websockets.serve 并运行直到 stop_event 被设置。"""
        stop_event = asyncio.Event()

        # 跨线程桥接：从外部线程触发 asyncio.Event.set()
        self._stop_event_bridge = lambda: self._transport.loop.call_soon_threadsafe(stop_event.set)

        async with websockets.serve(
            self._handler,
            self._transport.host,
            self._transport.port,
            ping_interval=None,     # 禁用库内置 ping（由应用层心跳管理）
            close_timeout=5,
            max_size=10 * 1024 * 1024  # 10MB
        ) as ws_server:
            self._ws_server = ws_server
            self._running = True
            await stop_event.wait()

        self._running = False

    def start_in_thread(self):
        """在独立守护线程中启动 WS 服务。返回线程对象。"""
        ready = threading.Event()
        self._ws_server = None
        self._stop_event_bridge = None

        def _run():
            self._transport.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._transport.loop)
            ready.set()
            try:
                self._transport.loop.run_until_complete(self._serve())
            except Exception as e:
                logger.error("WS event loop error: %s: %s", type(e).__name__, e, exc_info=True)
            finally:
                self._running = False
                try:
                    self._transport.loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=_run, daemon=True, name="ws-server")
        self._thread.start()
        ready.wait(timeout=5)
        logger.info("WS server started on ws://%s:%d/ws", self._transport.host, self._transport.port)
        return self._thread

    def shutdown(self, timeout: float = 5.0):
        """从任意线程安全停止 WS 服务器。幂等，多次调用安全。"""
        with self._lock:
            if not self._running and self._thread is None:
                return
            was_running = self._running
            self._running = False

        if was_running:
            logger.info("WS initiating shutdown...")

        # 1. 桥接触发 asyncio.Event → _serve() 退出 async with
        bridge = getattr(self, '_stop_event_bridge', None)
        if bridge:
            try:
                bridge()
            except Exception as e:
                logger.error("WS stop bridge error: %s", e)

        # 2. 等待线程退出
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("WS thread did not exit within %.1fs", timeout)

        # 3. 确保 transport 资源清理
        self._transport.close()
        logger.info("WS shutdown complete")
