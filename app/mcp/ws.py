"""WS 会话层 — WsConnection（hello 握手 + 请求响应匹配 + 心跳）与 SessionPool。

编辑操作走 WS：请求 {"type", "requestId", "data"} → 响应
{"type": "ok", "requestId", "data", "new_version"} 或
{"type": "error", "requestId", "code", "message", "details"}（见 app/ws/router.py）。

后台任务周期发 {"type": "ping"}（保活 + 后端锁续期），并按空闲 TTL 回收池内连接。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

import websockets

from app.mcp.errors import BackendError

logger = logging.getLogger(__name__)

# ── 超时数值（测试可注入覆盖） ──
PING_INTERVAL = 30.0   # 后台心跳间隔（秒）：保活 + 后端锁续期
IDLE_TTL = 1800.0      # 会话池空闲 TTL（秒）：30 分钟无活动 → 关连接出池
HELLO_TIMEOUT = 5.0    # hello 握手探测超时（秒）

# 创建类消息：响应 data.session_id 即新会话 ID（open_session 据此登记入池）
SESSION_OPEN_TYPES = frozenset({"load_file", "import_file", "create_file", "new_file"})


@dataclass
class CallResult:
    """WS 请求的 ok 响应。

    - data：响应 data 字段（多数消息为 dict；get_sessions 等为条目列表）。
    - new_version：响应 new_version（数据版本号）。
    - new_session_id：创建类消息产生的新会话 ID（其余消息为 None）。
    """
    data: dict
    new_version: int | None = None
    new_session_id: str | None = None


class WsConnection:
    """单条 WS 连接：hello 握手、请求响应匹配、后台心跳。

    由 connect() 建立；call() 发请求并按 requestId 匹配响应；close() 幂等关闭。
    """

    def __init__(self, ws, *, ping_interval: float = PING_INTERVAL):
        self._ws = ws
        self._ping_interval = ping_interval
        self._pending: dict[str, asyncio.Future] = {}
        self._last_activity = time.monotonic()
        self._closed = False
        self._pool = None                     # bind_pool_entry() 注册
        self._on_closed: Callable[[], None] | None = None  # 出池回调
        self._wake = asyncio.Event()          # 绑池时唤醒后台任务重算检查节奏
        self._reader_task = asyncio.create_task(self._reader())
        self._loop_task = asyncio.create_task(self._loop())

    # ── 建立连接 ──

    @classmethod
    async def connect(cls, ws_url: str, pat: str, *, ping_interval: float = PING_INTERVAL) -> "WsConnection":
        """建立 WS 连接并完成 hello 握手（hello 用空 session_id 起连接）。

        握手探测：hello 后发一次 ping 等 pong——未认证连接会被服务端 close(4010)，
        此时抛 BackendError("AUTH_REQUIRED", ...)。
        """
        ws = await websockets.connect(
            ws_url,
            ping_interval=None,             # 禁用库内置 ping（由应用层心跳管理）
            max_size=10 * 1024 * 1024,      # 与服务端一致
            open_timeout=HELLO_TIMEOUT,
        )
        try:
            await ws.send(json.dumps({"type": "hello", "session_id": "", "token": pat}))
            await ws.send(json.dumps({"type": "ping"}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=HELLO_TIMEOUT)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "pong":
                    break
        except websockets.exceptions.ConnectionClosed as exc:
            code = getattr(getattr(exc, "rcvd", None), "code", None)
            if code == 4010:
                raise BackendError("AUTH_REQUIRED", "认证失败：PAT 无效或已过期") from exc
            raise BackendError("WS_HANDSHAKE_FAILED", f"握手失败：连接被服务端关闭 code={code}") from exc
        except asyncio.TimeoutError as exc:
            raise BackendError("WS_HANDSHAKE_FAILED", "握手超时：服务端未响应 ping/pong") from exc
        except BaseException:
            with contextlib.suppress(Exception):
                await ws.close()
            raise
        return cls(ws, ping_interval=ping_interval)

    # ── 属性 ──

    @property
    def closed(self) -> bool:
        """连接是否已关闭。"""
        return self._closed

    def bind_pool_entry(self, pool, on_closed: Callable[[], None]) -> None:
        """登记到会话池（由 SessionPool 调用）：注入空闲 TTL 回收与出池回调。"""
        self._pool = pool
        self._on_closed = on_closed
        self._wake.set()  # 唤醒后台任务：按池的空闲 TTL 重算检查节奏

    def idle_expired(self, idle_ttl: float) -> bool:
        """是否空闲超时（活动 = 调用 + 心跳）。"""
        return time.monotonic() - self._last_activity > idle_ttl

    # ── 请求响应 ──

    async def call(self, msg_type: str, data: dict) -> CallResult:
        """发送请求并等待同 requestId 的响应。

        ok → CallResult；error → BackendError（code/message/details 透传）。
        创建类消息从响应 data.session_id 提取 new_session_id
        （router.py 的 ok 响应不带顶层 new_session_id，见 HandlerResult）。
        """
        if self._closed:
            raise BackendError("WS_CLOSED", "连接已关闭")
        req_id = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            await self._ws.send(json.dumps({"type": msg_type, "requestId": req_id, "data": data}))
            self._last_activity = time.monotonic()  # 调用活动：刷新空闲计时
            msg = await fut
        finally:
            self._pending.pop(req_id, None)
        self._last_activity = time.monotonic()
        if msg.get("type") == "error":
            raise BackendError(
                code=msg.get("code") or "WS_ERROR",
                message=msg.get("message") or "",
                details=msg.get("details") or {},
            )
        resp_data = msg.get("data")
        new_sid = msg.get("new_session_id")
        if new_sid is None and msg_type in SESSION_OPEN_TYPES and isinstance(resp_data, dict):
            new_sid = resp_data.get("session_id") or None
        return CallResult(data=resp_data, new_version=msg.get("new_version"), new_session_id=new_sid)

    # ── 后台任务 ──

    async def _reader(self):
        """接收循环：按 requestId 匹配响应，其余消息（广播/pong 等）丢弃。"""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                req_id = msg.get("requestId")
                fut = self._pending.get(req_id) if req_id is not None else None
                if fut is not None and not fut.done():
                    fut.set_result(msg)
        except Exception:
            pass
        finally:
            if not self._closed:
                await self.close()

    async def _loop(self):
        """后台任务：空闲 TTL 回收 + 周期 ping（保活 + 后端锁续期）。"""
        next_ping = time.monotonic() + self._ping_interval
        try:
            while True:
                tick = self._ping_interval
                if self._pool is not None:
                    tick = min(tick, max(self._pool.idle_ttl / 3.0, 0.05))
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=tick)
                    self._wake.clear()
                except asyncio.TimeoutError:
                    pass
                # 空闲 TTL：无活动超过 TTL → 自动关连接出池
                if self._pool is not None and self.idle_expired(self._pool.idle_ttl):
                    logger.info("WS 连接空闲超过 %.0fs，自动关闭出池", self._pool.idle_ttl)
                    await self.close()
                    return
                if time.monotonic() >= next_ping:
                    next_ping = time.monotonic() + self._ping_interval
                    await self._ws.send(json.dumps({"type": "ping"}))
                    self._last_activity = time.monotonic()  # 心跳保活：刷新空闲计时
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close()

    # ── 关闭 ──

    async def close(self) -> None:
        """关闭连接（幂等）：停后台任务、关 WS、失败挂起请求并出池。"""
        if self._closed:
            return
        self._closed = True
        task = self._loop_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        try:
            await self._ws.close()
        except Exception:
            pass
        err = BackendError("WS_CLOSED", "连接已关闭")
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()
        on_closed, self._on_closed = self._on_closed, None
        if on_closed is not None:
            on_closed()


class SessionPool:
    """WS 会话池 — 按 (username, session_id) 隔离，空闲 TTL 自动关连接出池。

    - key 含 username：A 用户的连接绝不暴露给 B 用户（越权调用只能由后端权限拦截）。
    - 空闲计时按连接活动（调用 + 心跳）刷新；超过 idle_ttl 无活动 → 关连接出池。
    - 控制连接（无 session）按 username 共享一条（供 get_sessions 等）。
    """

    def __init__(self, idle_ttl: float = IDLE_TTL, ping_interval: float = PING_INTERVAL):
        self.idle_ttl = idle_ttl
        self.ping_interval = ping_interval
        self._entries: dict[tuple[str, str], WsConnection] = {}
        self._controls: dict[str, WsConnection] = {}
        self._lock = threading.Lock()

    async def connect(self, ws_url: str, token: str) -> WsConnection:
        """按池的心跳间隔建立一条新连接。"""
        return await WsConnection.connect(ws_url, token, ping_interval=self.ping_interval)

    def put(self, username: str, session_id: str, conn: WsConnection) -> None:
        """登记会话连接（连接关闭时自动出池）。"""
        with self._lock:
            self._entries[(username, session_id)] = conn
        conn.bind_pool_entry(self, lambda: self._discard(username, session_id, conn))

    def _discard(self, username: str, session_id: str, conn: WsConnection) -> None:
        with self._lock:
            if self._entries.get((username, session_id)) is conn:
                del self._entries[(username, session_id)]

    def pop(self, username: str, session_id: str) -> WsConnection | None:
        """取出并移除池内连接（close_session 用）。"""
        with self._lock:
            return self._entries.pop((username, session_id), None)

    async def get(self, username: str, session_id: str) -> WsConnection:
        """查池返回该用户绑定该会话的连接；未命中/已过期抛 SESSION_NOT_FOUND。"""
        with self._lock:
            conn = self._entries.get((username, session_id))
        if conn is not None and conn.closed:
            self._discard(username, session_id, conn)
            conn = None
        if conn is not None and conn.idle_expired(self.idle_ttl):
            # 空闲超时（后台回收之外的兜底）：关连接出池
            await conn.close()
            conn = None
        if conn is None:
            raise BackendError("SESSION_NOT_FOUND", "会话不存在或已过期，请重新 canmatrix_open_file")
        return conn

    async def get_control(self, ws_url: str, username: str, token: str) -> WsConnection:
        """每用户共享一条无 session 控制连接。"""
        with self._lock:
            conn = self._controls.get(username)
        if conn is not None and not conn.closed:
            return conn
        conn = await self.connect(ws_url, token)
        with self._lock:
            old = self._controls.get(username)
            self._controls[username] = conn
        if old is not None and old is not conn and not old.closed:
            await old.close()
        return conn

    async def aclose_all(self) -> None:
        """关闭池内全部连接（会话 + 控制），测试/退出清理用。"""
        with self._lock:
            conns = list(self._entries.values()) + list(self._controls.values())
            self._entries.clear()
            self._controls.clear()
        for conn in conns:
            await conn.close()


# ── 全局会话池（单例，与 auth/session 管理器同模式） ──
_pool: SessionPool | None = None


def get_session_pool() -> SessionPool:
    """取全局会话池（不存在则按默认数值创建）。"""
    global _pool
    if _pool is None:
        _pool = SessionPool()
    return _pool


def init_session_pool(idle_ttl: float = IDLE_TTL, ping_interval: float = PING_INTERVAL) -> SessionPool:
    """重建全局会话池（测试注入空闲 TTL/心跳间隔用）。"""
    global _pool
    _pool = SessionPool(idle_ttl=idle_ttl, ping_interval=ping_interval)
    return _pool
