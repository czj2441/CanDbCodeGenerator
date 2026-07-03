"""
ws_server.py — WebSocket 服务端

连接生命周期管理 + full_sync 构建 + 服务启动。
"""

import asyncio
import json
import threading

import websockets

from models import CanDatabase
from session_manager import get_session_manager
from ws_transport import WsTransport, WsDiagnostics
from ws_router import MessageRouter


class WsServer:
    """WebSocket 服务端 — 管理连接生命周期 + 消息路由。"""

    def __init__(self, transport: WsTransport, router: MessageRouter):
        self._transport = transport
        self._router = router

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

            # ── 首次连接（无 session_id）→ 创建新 session ──
            if not session_id:
                session_id = sm.create(file_name="", db=CanDatabase())
                await ws.send(json.dumps({
                    "type": "session_created",
                    "data": {"session_id": session_id}
                }, ensure_ascii=False))
                # 继续注册 + full_sync（不 return）

            # ── 验证 session ──
            session = sm.get(session_id)
            if not session:
                # 旧 session 已丢失（后端重启/超时清理），创建恢复 session
                session_id = sm.create(file_name="", db=CanDatabase())
                await ws.send(json.dumps({
                    "type": "session_recovered",
                    "data": {"session_id": session_id, "reason": "session_not_found"}
                }, ensure_ascii=False))

            # ── 注册 + full_sync ──
            self._transport.register(session_id, ws)
            sm.update_heartbeat(session_id)

            await self._send_full_sync(ws, session_id)

            # ── 消息循环 ──
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "ping":
                    # 心跳 + 锁续期
                    try:
                        await ws.send(json.dumps({"type": "pong"}))
                        sm.update_heartbeat(session_id)
                    except Exception as e:
                        print(f"[WS] ping handler error: {e}")

                elif "requestId" in msg:
                    # 请求-响应类型：路由到 handler
                    result = await self._router.dispatch(ws, msg)

                    # session 切换同步（new_file/import_file/load_session 可能改变 session_id）
                    if result and result.new_session_id:
                        self._transport.unregister(session_id, ws)
                        session_id = result.new_session_id
                        self._transport.register(session_id, ws)
                        sm.update_heartbeat(session_id)
                        # session 切换后自动发送 full_sync
                        await self._send_full_sync(ws, session_id)

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"[WS] handler error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if session_id:
                self._transport.unregister(session_id, ws)
                sm.mark_stale(session_id)

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
                "lock_status": "held" if lock_held else "lost",
                "selected_message": None,
                "selected_errors": None
            }
        }

        if self._transport.diag.enabled:
            with self._transport.diag._counter_lock:
                pass
            self._transport.diag.info("full_sync_built",
                                       messages=len(messages_data))

        await ws.send(json.dumps(msg, ensure_ascii=False))

    # ── 服务启动 ──

    async def _serve(self):
        """启动 websockets.serve 并永久运行。"""
        async with websockets.serve(
            self._handler,
            self._transport.host,
            self._transport.port,
            ping_interval=None,     # 禁用库内置 ping（由应用层心跳管理）
            close_timeout=5,
            max_size=10 * 1024 * 1024  # 10MB
        ):
            await asyncio.Future()  # 永久运行

    def start_in_thread(self):
        """在独立守护线程中启动 WS 服务。返回线程对象。"""
        ready = threading.Event()

        def _run():
            self._transport.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._transport.loop)
            ready.set()
            self._transport.loop.run_until_complete(self._serve())

        t = threading.Thread(target=_run, daemon=True, name="ws-server")
        t.start()
        ready.wait(timeout=3)
        print(f"[WS] WebSocket server started on ws://{self._transport.host}:{self._transport.port}/ws")
        return t
