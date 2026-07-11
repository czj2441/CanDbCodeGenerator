"""
ws_transport.py — WebSocket 传输层 + 诊断系统

所有 WebSocket 网络 I/O 的唯一出口。上层模块不接触 ws/asyncio 对象。
"""

import asyncio
import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager

import websockets


class WsDiagnostics:
    """WebSocket 稳定性/性能诊断。

    开关：构造函数 `enabled` 参数，由 `--ws-debug` CLI 控制。
    输出：JSON lines，每行一条事件，可直接 `| jq` 解析。
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._start = time.time()
        self._counter_lock = threading.Lock()

        # 连接事件计数
        self.connects = 0
        self.disconnects = 0
        self.hello_timeouts = 0
        self.lock_stolen_sent = 0

        # 广播事件计数
        self.broadcasts = 0
        self.broadcast_fails = 0
        self.broadcast_by_type: dict[str, int] = defaultdict(int)

        # 性能计时（最近 100 次）
        self.timings: dict[str, list[float]] = defaultdict(list)
        self._max_timing_samples = 100

        # 版本追踪
        self.version_jumps: list[dict] = []  # [{from, to, ts}]

    # ── 日志 ──

    def log(self, level: str, event: str, **kwargs):
        if not self.enabled:
            return
        record = {
            "ts": round(time.monotonic(), 3),
            "level": level,
            "event": event,
            **kwargs
        }
        print(json.dumps(record, ensure_ascii=False, default=str), flush=True)

    def info(self, event: str, **kwargs):
        self.log("INFO", event, **kwargs)

    def warn(self, event: str, **kwargs):
        self.log("WARN", event, **kwargs)

    def error(self, event: str, **kwargs):
        self.log("ERROR", event, **kwargs)

    # ── 计时 ──

    @contextmanager
    def timed(self, operation: str):
        """上下文管理器，自动计时并记录。"""
        if not self.enabled:
            yield
            return
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed = (time.monotonic() - t0) * 1000
            buf = self.timings[operation]
            buf.append(elapsed)
            if len(buf) > self._max_timing_samples:
                buf.pop(0)

    # ── 快照（供 /api/diag 查询） ──

    def snapshot(self) -> dict:
        """返回当前诊断快照，供调试端点使用（线程安全）。"""
        avg_timings = {}
        for op, samples in self.timings.items():
            if samples:
                sorted_samples = sorted(samples)
                avg_timings[op] = {
                    "avg_ms": round(sum(samples) / len(samples), 2),
                    "p50_ms": round(sorted_samples[len(samples) // 2], 2),
                    "p99_ms": round(sorted_samples[int(len(samples) * 0.99)], 2),
                    "samples": len(samples),
                }
        with self._counter_lock:
            return {
                "uptime_s": round(time.time() - self._start, 1),
                "connections": {
                    "connects": self.connects,
                    "disconnects": self.disconnects,
                    "hello_timeouts": self.hello_timeouts,
                    "lock_stolen_sent": self.lock_stolen_sent,
                },
                "broadcasts": {
                    "total": self.broadcasts,
                    "fails": self.broadcast_fails,
                    "by_type": dict(self.broadcast_by_type),
                },
                "timings": avg_timings,
            }


class WsTransport:
    """所有 WebSocket 网络 I/O 的唯一出口。上层模块不接触 ws/asyncio。"""

    def __init__(self, host="127.0.0.1", port=8081, diagnostics=None):
        self.host = host
        self.port = port
        self.loop: asyncio.AbstractEventLoop | None = None
        self._clients: dict[str, set] = {}  # session_id → {ws}
        self._lock = threading.Lock()
        self.diag = diagnostics or WsDiagnostics(enabled=False)

    # ── 连接管理 ──

    def register(self, session_id: str, ws):
        """注册连接到指定 session。"""
        with self._lock:
            self._clients.setdefault(session_id, set()).add(ws)
        with self.diag._counter_lock:
            self.diag.connects += 1
        self.diag.info("ws_connect", session=session_id[:8])

    def unregister(self, session_id: str, ws):
        """注销连接。"""
        with self._lock:
            clients = self._clients.get(session_id)
            if clients:
                clients.discard(ws)
                if not clients:
                    del self._clients[session_id]
        with self.diag._counter_lock:
            self.diag.disconnects += 1
        self.diag.info("ws_disconnect", session=session_id[:8])

    # ── 单播（请求-响应） ──

    async def reply(self, ws, msg: dict):
        """向单个连接发送消息（ok/error）。"""
        await ws.send(json.dumps(msg, ensure_ascii=False))

    # ── 广播（异步安全，可从任何线程调用） ──

    def broadcast(self, session_id: str, msg: dict):
        """向指定 session 的所有连接推送消息。
        在调用线程完成 JSON 序列化，最小化锁持有时间。"""
        if not self.loop or self.loop.is_closed():
            if self.diag.enabled:
                self.diag.warn("broadcast_skip", reason="loop_unavailable")
            return

        if self.diag.enabled:
            self.diag.info("broadcast", session=session_id[:8],
                           type=msg.get("type"), version=msg.get("data_version"))
            with self.diag._counter_lock:
                self.diag.broadcasts += 1
                self.diag.broadcast_by_type[msg.get("type", "unknown")] += 1

        # 在调用线程完成序列化（不在锁内做 I/O）
        msg_json = json.dumps(msg, ensure_ascii=False)

        # 锁内快速拷贝连接列表
        with self._lock:
            clients = list(self._clients.get(session_id, set()))

        for ws in clients:
            asyncio.run_coroutine_threadsafe(
                self._safe_send(ws, msg_json), self.loop
            )

    def broadcast_all(self, msg: dict):
        """向所有已注册 session 广播。"""
        with self._lock:
            all_sids = list(self._clients.keys())
        for sid in all_sids:
            self.broadcast(sid, msg)

    async def _safe_send(self, ws, msg_json: str):
        """发送消息，吞 ConnectionClosed 异常。"""
        try:
            await ws.send(msg_json)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            if self.diag.enabled:
                with self.diag._counter_lock:
                    self.diag.broadcast_fails += 1
                self.diag.warn("broadcast_fail", error=str(e))

    # ── 关闭 ──

    def close(self):
        """关闭所有连接并停止事件循环。线程安全，幂等。"""
        loop = self.loop
        if not loop or loop.is_closed():
            return

        # 1. 关闭所有客户端连接
        with self._lock:
            all_sids = list(self._clients.keys())
        for sid in all_sids:
            with self._lock:
                clients = self._clients.pop(sid, set())
            for ws in clients:
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.close(1001, "server shutting down"), loop
                    )
                except Exception:
                    pass

        # 2. 停止事件循环
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
