# WebSocket 前后端数据同步 — 架构设计

> 状态：设计阶段（已通过审查，详见 §十一 问题追踪）  
> 日期：2026-07-02  
> 最后修订：2026-07-02（合并审查意见）

---

## 目录

1. [当前前后端通信全景图](#一当前前后端通信全景图)
2. [当前数据同步链路分析](#二当前数据同步链路分析)
3. [WebSocket 架构设计](#三websocket-架构设计)
4. [数据一致性保证机制](#四数据一致性保证机制)
5. [关键流程对比](#五关键流程对比)
6. [前端架构改造](#六前端架构改造)
7. [后端架构改造](#七后端架构改造)
8. [文件结构规划](#八文件结构规划)
9. [关键设计决策说明](#九关键设计决策说明)
10. [实施计划](#十实施计划)

---

## 〇、并发模型前提

### 当前状态

`api_server.py` 使用标准库 `http.server.HTTPServer`（**单线程**），所有请求串行处理，不存在并发问题。

```python
# api_server.py L1585 — 当前实际代码
server = HTTPServer(("localhost", port), ApiHandler)
```

### WebSocket 改造后的并发模型

引入 WebSocket 后，系统将首次面临真正的多线程并发：

```
┌─────────────────────────────────────────────────────────┐
│                    主进程                                │
│  ┌───────────────────┐   ┌────────────────────────────┐ │
│  │ HTTP Server        │   │ WebSocket Server           │ │
│  │ ThreadingHTTPServer │   │ asyncio event loop         │ │
│  │ (主线程)            │   │ (独立线程)                  │ │
│  └─────────┬─────────┘   └──────────┬─────────────────┘ │
│            │                        │                    │
│            │    共享 SESSION_MGR    │                    │
│            │    共享 CanDatabase    │                    │
│            └──────────┬─────────────┘                    │
│                       ▼                                  │
│              必须加锁保护的临界区                          │
└─────────────────────────────────────────────────────────┘
```

**关键要求：**
1. **HTTP Server 必须升级为 `ThreadingHTTPServer`**（否则多标签页请求串行排队）
2. `CanDatabase` 已有 `__lock`（`threading.RLock()`）+ `with_lock()` 方法，但需扩大锁区间（见 §七）
3. 所有对 `db.messages` 的遍历、`db.data_version` 的读写必须在锁保护下
4. `WsTransport` 使用 `asyncio.run_coroutine_threadsafe()` 进行跨线程通信

---

## 一、当前前后端通信全景图

### 1.1 改造前的 29 个 API 端点（全部将通过 WebSocket 替代）

> 改造后，仅保留 `GET /api/diag` 诊断端点和 `GET /*` 静态文件服务。
> 以下 29 个端点全数迁移到 WebSocket 消息协议。

### 1.2 当前 4 层定时器体系

```
┌──────────────────────────────────────────────────────────────────┐
│  App.vue onMounted                                               │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │ 健康检查（全局，永不停）  store._healthTimer              │     │
│  │   每 2s → GET /api/status                                │     │
│  │   目的：判断 connected / offline / dead                   │     │
│  ├─────────────────────────────────────────────────────────┤     │
│  │ 全量轮询（全局，编辑器模式） store._fullReloadTimer        │     │
│  │   每 5s → loadMessages() + loadSelectedMessage()        │     │
│  │   目的：⚠️ 前后端数据同步的唯一机制                       │     │
│  ├─────────────────────────────────────────────────────────┤     │
│  │ 文件锁检查（仅编辑器模式） lockCheckTimer                  │     │
│  │   每 0.5s → GET /api/session/{id}/info                  │     │
│  │   目的：多标签页冲突检测                                   │     │
│  ├─────────────────────────────────────────────────────────┤     │
│  │ 心跳上报（仅编辑器模式）  heartbeatTimer                   │     │
│  │   每 10s → POST /api/heartbeat                          │     │
│  │   目的：告知后端「该标签页仍在编辑」                        │     │
│  └─────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、当前数据同步链路分析

### 2.1 信号编辑链路（核心问题所在）

```
用户编辑信号字段
  │
  ├→ @blur 触发 updateSignal()
  ├→ 乐观更新本地 store（立即显示新值）
  ├→ PUT /api/messages/{id}/signals/{uuid}  { field: value }
  │        │
  │        ├─ 后端校验通过 → 返回 {success:true, data:{signal完整对象}}
  │        └─ 后端修正/拒绝 → 返回 {success:true, data:{signal完整对象}}
  │
  ├→ ❌ 前端完全忽略响应中的标准数据
  ├→ 继续使用乐观更新的值
  │
  └→ 5s 后 _doFullReload() 触发
       ├─ loadMessages()     → 替换 this.messages 数组
       ├─ loadSelectedMessage() → 替换 messageCache[id]
       ├─ _syncBackendStatus()  → GET /api/status
       └─ 💥 Vue 全量 DOM diff → 焦点丢失
```

**核心矛盾：**

后端 `_put_signal` 返回的就是校验后的标准数据（`sig.to_dict()`），但前端不消费它，转而等 5s 后的全量刷新来获取同一份数据。

### 2.2 撤销/重做链路（额外同步需求）

```
用户 Ctrl+Z
  │
  ├→ POST /api/undo
  │   后端 pop 撤销栈 → 执行逆操作 → DB 已变
  │   返回 {success:true, undo_count:4, redo_count:1}
  │
  ├→ loadMessages()          ← 拉全量报文列表
  ├→ loadSelectedMessage()   ← 拉当前报文详情
  ├→ _syncBackendStatus()    ← 拉 undo/redo 计数
  │
  └→ ⚠️ 两次额外 API 调用，全量数据刷新
```

撤销/重做会直接修改后端 DB，前端没有乐观更新的基础，必须拉取最新数据。

### 2.3 每分钟请求量（用户只看不编辑的稳态）

```
lockCheckTimer:  120 次/分钟  (GET /api/session/{id}/info  @ 0.5s)
heartbeatTimer:    6 次/分钟  (POST /api/heartbeat          @ 10s)
_healthTimer:     30 次/分钟  (GET /api/status              @ 2s)
_fullReloadTimer: 12 轮/分钟  (每轮 3 个 API ≈ 36 次请求    @ 5s)
─────────────────────────────────────────────────────
合计：            192 次 HTTP 请求/分钟
```

其中 `_fullReloadTimer` 的 36 次请求用于"确认没有数据变化"，是完全冗余的开销。

---

## 三、WebSocket 架构设计

### 3.1 设计原则

| 原则 | 说明 |
|---|---|
| **后端是唯一真理源** | 所有数据变更必须以后端推送的为准，前端本地状态可以被覆盖 |
| **版本号保证顺序** | 每个变更携带单调递增的 `data_version`，前端丢弃版本 ≤ 当前值的事件 |
| **ws 断线自动重连** | WebSocket 断开后指数退避重连，重连成功后推送全量快照 |
| **增量优先，全量兜底** | 常规变更推增量事件，建连/重连/版本跳跃推全量快照 |
| **全双工 WebSocket** | 所有操作（CRUD + 推送）均通过单一 WebSocket 连接，HTTP 仅保留静态文件服务和诊断端点 |
| **请求-确认模式** | 写操作遵循 requestId → ok/error 响应，读操作通过 `full_sync` + 增量广播保持一致性 |
| **可复用 Handler** | 业务逻辑层与传输层解耦，同一 handler 可被 HTTP 或 WS 复用（设计预留，当前全走 WS） |

### 3.1.1 端口策略

WebSocket 与 HTTP 无法共用同一端口（`http.server` 同步阻塞 vs `websockets` asyncio 异步），采用**独立端口 + 偏移策略**：

```
HTTP port: 由 main() 参数指定（默认 8080）
WS port:   HTTP port + 1（默认 8081）

前端 WS URL 构建：
  const wsPort = parseInt(location.port) + 1
  const wsUrl = `${protocol}//${location.hostname}:${wsPort}/ws`
```

### 3.1.2 新增依赖

```
# requirements.txt
websockets>=12.0    # asyncio WebSocket 库
```

> **注意：** `websockets` v12+ 的 handler 签名为 `handler(ws)`（仅一个参数），
> 与旧版 `handler(ws, path)` 不兼容。本文档所有代码示例使用 v12+ API。

### 3.2 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                          后端 (Python)                                │
│                                                                      │
│  ┌──────────────────────────────────────────────┐                    │
│  │       WebSocket Server（全功能，唯一后端）      │                    │
│  │       ws://host:8081/ws                       │                    │
│  │                                               │                    │
│  │  ┌──────────────┐  ┌──────────┐  ┌─────────┐ │                    │
│  │  │ WsTransport  │→ │ Router   │→ │ Handlers│ │                    │
│  │  │ (I/O 封装)   │  │ (type→fn)│  │ (业务逻辑)│ │                    │
│  │  └──────────────┘  └──────────┘  └─────────┘ │                    │
│  │                                               │                    │
│  │  全双工：收发 ~25 种消息类型                     │                    │
│  │  请求→ok/error + 广播→version gate             │                    │
│  └──────────────────────────────────────────────┘                    │
│                                                                      │
│  ┌──────────────────────────────────────────────┐                    │
│  │  HTTP Server（仅静态文件 + 诊断）               │                    │
│  │  GET /* → dist/ 静态文件                       │                    │
│  │  GET /api/diag → JSON 诊断                    │                    │
│  └──────────────────────────────────────────────┘                    │
│                                                                      │
│  ┌──────────────────────────────────────────────┐                    │
│  │  SESSION_MGR (共享状态)                        │                    │
│  │  ThreadingHTTPServer + asyncio thread-safe     │                    │
│  └──────────────────────────────────────────────┘                    │
│                                  │  ③ 推送全量快照       │               │
│                                  │  ④ 之后推送增量       │               │
│                                  └──────────┬───────────┘               │
│                                             │                          │
│           ┌─────────────────────────────────┘                          │
│           │ ws://localhost:8081/ws                                      │
│           │                                                            │
│  ┌────────┴──────────────────────────────────────────────┐            │
│  │                    CanDatabase                          │            │
│  │  data_version: int  (每次变更 +1)                       │            │
│  │  messages: dict                                        │            │
│  │  modified: bool                                        │            │
│  └───────────────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        前端 (Vue + Pinia)                             │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │              WebSocket Client（全功能）                    │       │
│  │              ws://localhost:8081/ws                       │       │
│  │                                                          │       │
│  │  on connect → 发 hello {sessionId, dataVersion}           │       │
│  │                                                          │       │
│  │  ┌─────────────────┐   ┌──────────────────────┐          │       │
│  │  │ 广播处理          │   │ 请求-响应处理          │          │       │
│  │  │ _applyWsMessage  │   │ wsClient.request()   │          │       │
│  │  │ (版本校验+应用)   │   │ (requestId + Promise) │          │       │
│  │  └────────┬────────┘   └──────────┬───────────┘          │       │
│  │           │                       │                       │       │
│  │  ┌────────▼───────────────────────▼───────────────────┐  │       │
│  │  │           editor.js store (Pinia)                  │  │       │
│  │  │                                                    │  │       │
│  │  │  _dataVersion: int  ← 跟踪当前数据版本               │  │       │
│  │  │  _wsConnected: bool ← ws 连接状态                   │  │       │
│  │  │  _requestId: int    ← 递增请求 ID                   │  │       │
│  │  │                                                    │  │       │
│  │  │  updateSignal(sigUuid, field, value):               │  │       │
│  │  │    ① 乐观更新本地 → 立即渲染                          │  │       │
│  │  │    ② wsClient.request('edit_signal', {...})         │  │       │
│  │  │    ③ 等待 ok/error 响应 → 回滚或广播确认             │  │       │
│  │  │                                                    │  │       │
│  │  │  _applyWsMessage(event):  // 广播消息               │  │       │
│  │  │    if version <= _dataVersion → skip                │  │       │
│  │  │    _dataVersion = version                           │  │       │
│  │  │    switch type → 局部 patch / 全量替换               │  │       │
│  │  └────────────────────────────────────────────────────┘  │       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                      │
│  “一个连接完成所有通信——编辑、撤销、心跳、锁管理”                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 WebSocket 消息协议

消息分两类：

| 类别 | 方向 | 特征 | 示例 |
|---|---|---|---|
| **请求-响应** | 前端→后端→前端 | 携带 `requestId`，一对一确认 | `edit_signal` → `ok`/`error` |
| **广播通知** | 后端→全部连接 | 携带 `data_version`，一对多推送 | `signal_updated`、`lock_stolen` |

#### 3.3.1 全双工消息清单

| type | 类别 | 方向 | 说明 | 替代 HTTP |
|---|---|---|---|---|
| `hello` | 握手 | C→S | 连接注册（含 session_id、data_version） | — |
| `ping` | 心跳 | C→S | 10s 心跳 + 锁续期（一石二鸟） | `POST /api/heartbeat` |
| `pong` | 心跳 | S→C | 心跳应答 | — |
| `full_sync` | 广播 | S→C | 全量快照（建连/重连/版本跳跃） | `GET /api/messages` |
| `signal_updated` | 广播 | S→C | 信号字段变更后推送完整对象 | — |
| `signal_added` | 广播 | S→C | 新信号添加（含完整对象和 signal_count） | — |
| `signal_deleted` | 广播 | S→C | 信号删除（含 signal_count） | — |
| `message_added` | 广播 | S→C | 新报文添加 | — |
| `message_updated` | 广播 | S→C | 报文元数据变更 | — |
| `message_deleted` | 广播 | S→C | 报文删除 | — |
| `signal_errors_changed` | 广播 | S→C | 信号布局校验结果变更 | `GET /api/.../signal-errors` |
| `status_changed` | 广播 | S→C | modified / undo_count / redo_count | `GET /api/status` |
| `undo_applied` | 广播 | S→C | 撤销操作已完成（含 changed_message_ids） | — |
| `redo_applied` | 广播 | S→C | 重做操作已完成（含 changed_message_ids） | — |
| `lock_stolen` | 广播 | S→C | 锁被抢占通知 | `BroadcastChannel` |
| **`edit_signal`** | **请求** | **C→S** | **编辑信号字段 {msg_id, sig_uuid, field, value}** | **PUT /api/.../signals/{uuid}** |
| **`add_signal`** | **请求** | **C→S** | **添加信号 {msg_id, signal_data}** | **POST /api/.../signals** |
| **`delete_signal`** | **请求** | **C→S** | **删除信号 {msg_id, sig_uuid}** | **DELETE /api/.../signals/{uuid}** |
| **`batch_add_signals`** | **请求** | **C→S** | **批量添加信号 {msg_id, ...}** | **POST /api/.../signals/batch** |
| **`edit_message`** | **请求** | **C→S** | **编辑报文元数据 {msg_id, field, value}** | **PUT /api/messages/{id}** |
| **`add_message`** | **请求** | **C→S** | **添加报文 {message_data}** | **POST /api/messages** |
| **`delete_message`** | **请求** | **C→S** | **删除报文 {msg_id}** | **DELETE /api/messages/{id}** |
| **`undo`** | **请求** | **C→S** | **撤销 {}** | **POST /api/undo** |
| **`redo`** | **请求** | **C→S** | **重做 {}** | **POST /api/redo** |
| **`save`** | **请求** | **C→S** | **手动保存 {}** | **POST /api/save** |
| **`create_session`** | **请求** | **C→S** | **创建新会话** | **POST /api/session** |
| **`load_session`** | **请求** | **C→S** | **加载并锁定文件 {session_id}** | **POST /api/session/{id}/load** |
| **`rename_session`** | **请求** | **C→S** | **重命名会话 {name}** | **PUT /api/session** |
| **`delete_session`** | **请求** | **C→S** | **删除会话 {session_id}** | **DELETE /api/session/{id}** |
| **`get_sessions`** | **请求** | **C→S** | **获取会话列表** | **GET /api/sessions** |
| **`release_lock`** | **请求** | **C→S** | **释放文件锁 {abort?: bool}** | **POST /api/release** |
| **`steal_lock`** | **请求** | **C→S** | **抢占文件锁 {target_session_id}** | **POST /api/steal** |
| **`new_file`** | **请求** | **C→S** | **新建空文件 {}** | **POST /api/new** |
| **`import_file`** | **请求** | **C→S** | **导入 DBC 文件 {content, filename}** | **POST /api/import** |
| **`export_file`** | **请求** | **C→S** | **导出文件 {session_id?}** | **POST /api/export** |
| **`download_file`** | **请求** | **C→S** | **触发浏览器下载 {session_id}** | **GET /api/download** |
| **`get_summary`** | **请求** | **C→S** | **获取全量统计摘要 {}** | **GET /api/summary** |
| **`get_session_info`** | **请求** | **C→S** | **获取会话元数据 {session_id}** | **GET /api/session/{id}/info** |
| **`get_message`** | **请求** | **C→S** | **获取报文详情（含 signals）{msg_id}** | **GET /api/messages/{id}** |
| **`get_signal_errors`** | **请求** | **C→S** | **获取信号校验错误 {msg_id}** | **GET /api/.../signal-errors** |
| `ok` | 响应 | S→C | 请求成功（含 result data + new_version） | HTTP 200 |
| `error` | 响应 | S→C | 请求失败（含 error code + message） | HTTP 4xx/5xx |

#### 3.3.2 请求-响应协议

```jsonc
// ★ 前端发送请求
{
  "type": "edit_signal",
  "requestId": "r42",
  "data": {
    "msg_id": 256,
    "sig_uuid": "a1b2c3d4",
    "field": "start_bit",
    "value": 12
  }
}

// ★ 后端成功响应（仅发送者收到）
{
  "type": "ok",
  "requestId": "r42",
  "data": {
    "uuid": "a1b2c3d4",
    "name": "EngineSpeed",
    "start_bit": 12,
    "length": 16,
    "byte_order": "intel",
    "factor": 1.0,
    "offset": 0.0,
    "min_val": 0.0,
    "max_val": 65535.0,
    "unit": "rpm",
    "comment": ""
  },
  "new_version": 43
}

// ★ 后端错误响应
{
  "type": "error",
  "requestId": "r42",
  "code": "SIGNAL_NOT_FOUND",
  "message": "信号 a1b2c3d4 不存在"
}

// ★ 同时，后端向所有连接广播变更
{
  "type": "signal_updated",
  "data": { /* 完整 signal 对象 */ },
  "data_version": 43
}
```

#### 3.3.3 关键请求示例

```jsonc
// ── undo ──
// req: { "type": "undo", "requestId": "r50", "data": {} }
// res: { "type": "ok", "requestId": "r50",
//         "data": { "changed_message_ids": [256] } }
// bcast: { "type": "undo_applied", "data": { "changed_message_ids": [256] }, "data_version": 44 }

// ── batch_add_signals ──
// req: { "type": "batch_add_signals", "requestId": "r51",
//        "data": { "msg_id": 256, "nameTemplate": "Sig_{n}", "count": 8, ... } }
// res: { "type": "ok", "requestId": "r51",
//        "data": { "created": [{ "uuid": "real-uuid", ... }, ...],
//                  "errors": [{ "index": 2, "name": "Sig_3", "error": "overlap" }],
//                  "count": 7, "message": {...}, "signal_count": 13 } }
// （与当前 HTTP POST /api/messages/{id}/signals/batch 响应格式一致）
// bcast: { "type": "signal_added", ... } × N 和 { "type": "message_updated", ... }

// ── export_file ──
// req: { "type": "export_file", "requestId": "r52", "data": { "session_id": "abc" } }
// res: { "type": "ok", "requestId": "r52",
//        "data": { "content": "...", "filename": "EngineBus.dbc" } }
// （前端收到后触发浏览器下载）

// ── import_file ──
// req: { "type": "import_file", "requestId": "r53",
//        "data": { "content": "VERSION \"\"\n\nBO_ 256 EngineData: 8 Vector__XXX\n...",
//                  "filename": "EngineBus.dbc" } }
// res: { "type": "ok", "requestId": "r53",
//        "data": { "session_id": "def456", "message_count": 5 } }
// 前端随后发 create_session 或直接进入编辑器

// ── download_file ──
// req: { "type": "download_file", "requestId": "r55", "data": { "session_id": "abc" } }
// res: { "type": "ok", "requestId": "r55",
//        "data": { "content": "VERSION ...", "filename": "EngineBus.dbc", "mime": "text/plain" } }
// （前端收到后动态创建 <a> 标签触发浏览器另存为对话框）

// ── get_summary ──
// req: { "type": "get_summary", "requestId": "r56", "data": {} }
// res: { "type": "ok", "requestId": "r56",
//        "data": { "name": "EngineBus", "message_count": 5, "signal_count": 42, "modified": false,
//                  "messages": [{ "id": 256, "name": "EngineData", "signal_count": 8 }, ...] } }

// ── get_session_info ──
// req: { "type": "get_session_info", "requestId": "r57", "data": { "session_id": "abc" } }
// res: { "type": "ok", "requestId": "r57",
//        "data": { "session_id": "abc", "file_name": "EngineBus.dbc", "message_count": 5,
//                  "signal_count": 42, "created_at": "2026-07-02T10:00:00" } }

// ── steal_lock ──
// req: { "type": "steal_lock", "requestId": "r54",
//        "data": { "target_session_id": "victim-abc" } }
// res: { "type": "ok", "requestId": "r54", "data": {} }
// 后端同时向 victim-abc 的 WS 连接推送:
// bcast: { "type": "lock_stolen", "data": { "victim_session_id": "victim-abc",
//                                             "stealer_session_id": "my-session" } }

// ── new_file ──
// req: { "type": "new_file", "requestId": "r58", "data": {} }
// res: { "type": "ok", "requestId": "r58",
//        "data": { "session_id": "new-sid", "name": "NewFile" } }
// ★ handler 内部：unregister 旧 sid → release 旧文件 → 创建新 session → register 新 sid
//    → 推送 full_sync。前端无需断连重连，直接进入编辑器。
```

// ═══════════════════════════════════════════
// 类型 ②：增量事件 — 报文 CRUD
// ═══════════════════════════════════════════
{
  "type": "message_added",
  "data_version": 43,
  "data": {
    "message": { "id": 768, "id_hex": "0x300", "name": "NewMessage",
                 "dlc": 8, "cycle_time": 0, "signal_count": 0 }
  }
}

{
  "type": "message_updated",
  "data_version": 44,
  "data": {
    "message": { "id": 256, "name": "EngineRPM", "dlc": 8 }
  }
}

{
  "type": "message_deleted",
  "data_version": 45,
  "data": { "msg_id": 256 }
}

// ═══════════════════════════════════════════
// 类型 ③：增量事件 — 信号 CRUD
// ═══════════════════════════════════════════
{
  "type": "signal_added",
  "data_version": 46,
  "data": {
    "msg_id": 256,
    "signal": { "uuid": "sig-new", "name": "NewSignal", ... }
  }
}

{
  "type": "signal_updated",
  "data_version": 47,
  "data": {
    "msg_id": 256,
### 3.4 传输层：WsTransport

传输层封装所有 WebSocket I/O，上层模块不直接接触 `ws` 或 `asyncio` 对象。

```python
# ws_transport.py

class WsTransport:
    """WebSocket 传输层 —— 所有 I/O 的唯一出口"""

    def __init__(self, loop=None, diagnostics=None):
        self._connections: dict[str, set] = {}  # session_id → {ws}
        self._loop = loop
        self.diag = diagnostics or WsDiagnostics(enabled=False)

    # ── 连接管理 ──
    def register(self, session_id: str, ws): ...
    def unregister(self, session_id: str, ws): ...

    # ── 单播（请求-响应） ──
    async def reply(self, ws, msg: dict):
        """向单个连接发送消息（ok/error）。"""
        await ws.send(json.dumps(msg))

    # ── 广播（通知） ──
    def broadcast(self, session_id: str, msg: dict):
        """向指定 session 的所有连接推送消息。
        调度到事件循环中执行，不阻塞调用方。"""
        if not self._loop or self._loop.is_closed():
            return
        for ws in self._connections.get(session_id, set()):
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(msg)), self._loop
            )

    def broadcast_all(self, msg: dict):
        """向所有已注册 session 推送。"""
        ...
```

### 3.5 路由层：MessageRouter

路由层按消息 `type` 分发到对应 Handler。新增操作只需注册一行。

```python
# ws_router.py

class MessageRouter:
    """消息路由器 —— type → handler"""

    def __init__(self, transport: WsTransport):
        self._transport = transport
        self._handlers: dict[str, callable] = {}

    def register(self, msg_type: str, handler):
        self._handlers[msg_type] = handler

    async def dispatch(self, ws, msg: dict):
        """入口：从 _handler 协程调用，一条消息进来 → 找 handler → 执行 → 回复"""
        msg_type = msg.get("type")
        handler = self._handlers.get(msg_type)
        if not handler:
            await self._transport.reply(ws, {
                "type": "error",
                "requestId": msg.get("requestId"),
                "code": "UNKNOWN_TYPE",
                "message": f"Unknown message type: {msg_type}"
            })
            return
        try:
            result = await handler(msg["data"])
            await self._transport.reply(ws, {
                "type": "ok",
                "requestId": msg["requestId"],
                "data": result.data,
                "new_version": result.new_version
            })
            # handler 返回的 events 列表交给 broadcaster 广播
            for event in result.events:
                self._transport.broadcast(result.session_id, event)
            return result  # ★ 返回给 _handler 协程，用于 session 切换检测
        except HandlerError as e:
            await self._transport.reply(ws, {
                "type": "error",
                "requestId": msg["requestId"],
                "code": e.code,
                "message": e.message
            })

# ── 注册示例 ──
router = MessageRouter(transport)
router.register("edit_signal", EditSignalHandler(session_mgr))
router.register("add_signal", AddSignalHandler(session_mgr))
router.register("delete_signal", DeleteSignalHandler(session_mgr))
router.register("undo", UndoHandler(session_mgr))
router.register("redo", RedoHandler(session_mgr))
# ... 共 20+ 个 handler
```

### 3.6 Handler 设计模式

Handler 是纯业务逻辑函数/类，**不持有 ws 连接，不发送网络消息**。

```python
# handlers.py

from dataclasses import dataclass
from typing import Any, Optional

# 信号可编辑字段白名单（防止写入 uuid 等不可变字段）
EDITABLE_SIGNAL_FIELDS = {
    'name', 'start_bit', 'length', 'byte_order',
    'factor', 'offset', 'min_val', 'max_val', 'unit', 'comment'
}

@dataclass
class HandlerResult:
    data: dict
    events: list[dict]        # 需要广播的事件列表
    new_version: int
    session_id: str
    new_session_id: Optional[str] = None  # ★ new_file/import_file 切换时设此字段
    changed_msg_ids: Optional[list[int]] = None

class HandlerError(Exception):
    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}

# ── 示例：编辑信号 Handler ──
class EditSignalHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    async def __call__(self, data: dict) -> HandlerResult:
        session = self._sm.get(data["session_id"])
        if not session:
            raise HandlerError("SESSION_NOT_FOUND")

        field = data["field"]
        if field not in EDITABLE_SIGNAL_FIELDS:
            raise HandlerError("FIELD_NOT_EDITABLE", f"字段 {field} 不可编辑")

        db = session.db
        with db.with_lock():
            msg = db.messages.get(data["msg_id"])
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND")
            signal = next((s for s in msg.signals if s.uuid == data["sig_uuid"]), None)
            if not signal:
                raise HandlerError("SIGNAL_NOT_FOUND")

            # 字段级校验（复用现有 api_server.py 逻辑）
            value = data["value"]
            ok, err, info = db.validate_signal_field(
                data["msg_id"], signal, field, value)
            if not ok:
                raise HandlerError("VALUE_INVALID", err,
                                   {"error_code": info.get("error_code", ""), "field": field})

            old_val = getattr(signal, field)
            setattr(signal, field, value)
            db.modified = True

            # 自动推入撤销栈（通过 SessionManager 统一接口，使用 camelCase 键名）
            self._sm.push_undo(data["session_id"], {
                "type": "signal_update",
                "msgId": data["msg_id"],
                "sigUuid": data["sig_uuid"],
                "prev": {field: old_val},
                "next": {field: value}
            })

            new_version = db._bump_version()

            # 组装广播事件
            event = {
                "type": "signal_updated",
                "data": {"msg_id": data["msg_id"], "signal": signal.to_dict()},
                "data_version": new_version
            }

            return HandlerResult(
                data=signal.to_dict(),
                events=[event],
                new_version=new_version,
                session_id=data["session_id"]
            )
```

**关键约束**：
- Handler 只操作 `db` 和 `session_mgr`，不碰 `ws` / `transport`
- Signal 是 dataclass，用 `getattr`/`setattr` 操作字段
- 编辑字段通过 `EDITABLE_SIGNAL_FIELDS` 白名单校验
- undo 栈通过 `self._sm.push_undo(session_id, snapshot)` 调用
- 返回 `HandlerResult` → Router 负责 `reply` 和 `broadcast`
- 错误通过 `HandlerError` 抛出 → Router 转为 `error` 响应

---

## 四、数据一致性保证机制

```
┌─────────────────────────────────────────────────────────────────┐
│                    一致性保障四层机制                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  第 1 层：版本号单调递增                                          │
│        后端 CanDatabase.data_version：每次增删改 +1              │
│        前端 editorStore._dataVersion：记录已应用的最高版本         │
│        收到 event.data_version ≤ _dataVersion → 直接丢弃         │
│                                                                  │
│  第 2 层：ws 建连/重连 → 全量快照覆盖                              │
│        客户端发 hello { session_id, data_version: 0 }            │
│        服务端返回 full_sync → 前端直接替换所有 store 数据          │
│        保证：连接建立时 100% 前后端一致                            │
│                                                                  │
│  第 3 层：增量事件的幂等性                                        │
│        signal_updated 携带完整信号对象（不是部分字段）             │
│        前端收到后：按 uuid 找到信号 → 直接替换整个对象             │
│        重复收到同一版本 → 版本号去重，自动丢弃                     │
│                                                                  │
│  第 4 层：重连全量同步                                         │
│        ws 断开 → 自动重连（指数退避：1s→2s→4s→...→30s）      │
│        ws 重连 → 发 hello(dataVersion=0) → 全量快照覆盖       │
│        重连成功后全量快照覆盖，100% 数据一致                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 版本号跳跃处理

```
场景：ws 断线 30s，期间后端产生了 10 个版本变更

┌─ ws 重连 ─────────────────────────────────────────┐
│ 客户端发送 hello {data_version: 0}（★ 始终为0请求全量）  │
│                                                     │
│ 服务端：当前版本 = 15，delta 范围 = 6~15            │
│   如果 delta 数量 ≤ 20 → 逐条推送                   │
│   如果 delta 数量 > 20  → 直接推 full_sync          │
│                                                     │
│ 前端：收到 full_sync 后，整个 store 被覆盖          │
│       版本号跳到 15，数据 100% 一致                 │
└─────────────────────────────────────────────────────┘
```

---

## 五、关键流程对比

### 5.1 信号编辑流程（全 WS）

```
用户编辑 RPM 起始位
  │
  ├→ @blur 触发
  ├→ 乐观更新 store（显示 32） ✅
  │
  ├→ wsClient.request('edit_signal', { msg_id, sig_uuid, field: 'start_bit', value: 12 })
  │   ├─ 防抖：同一字段 300ms 内再次编辑 → 合并为新值
  │   └─ 重复 request 不等待前一个响应
  │
  ├→ 后端 handler 处理
  │   ├─ db 写入 + undo 栈推入
  │   └─ 返回 HandlerResult（含广播事件）
  │
  ├→ 两条 WS 消息几乎同时到达前端：
  │   ┌──────────────────────────────────────┐
  │   │ ① ok { requestId: "r42", data: {...} }│   ← 仅发送者收到
  │   │    → 确认写入（静默）                  │
  │   │                                      │
  │   │ ② signal_updated { signal: {...},    │   ← 广播（所有连接）
  │   │                     data_version: 43 } │
  │   │    → 版本校验通过 → patch 该信号       │
  │   │    → 显示 12 ✅                       │
  │   │    → 焦点保持 ✅（无全量 diff）         │
  │   └──────────────────────────────────────┘
  │
  └→ 错误处理
      ├─ ok 返回 → 确认成功
      └─ error { code: "VALUE_INVALID" }
          → 回滚乐观值 → showToast
```

### 5.2 撤销/重做流程（全 WS）

```
用户 Ctrl+Z
  │
  ├→ wsClient.request('undo', {})  // ← 不再是 POST /api/undo
  │
  ├→ 后端 handler 处理
  │   ├─ 加锁 pop 撤销栈 → 执行 inverse
  │   ├─ 返回 HandlerResult
  │   └─ Router 广播 undo_applied
  │
  ├→ 两条 WS 消息几乎同时到达：
  │   ┌──────────────────────────────────────┐
  │   │ ① ok { data: { changed_message_ids } }│  ← 仅发送者
  │   │                                      │
  │   │ ② undo_applied {                     │  ← 广播
  │   │      changed_message_ids: [256, 512], │
  │   │      status: {...},                   │
  │   │      data_version: 44 }               │
  │   │    → 按 changed_ids 只 reload 受影响报文│
  │   └──────────────────────────────────────┘
  │
  └→ 增量 patch，焦点保持 ✅
```

### 5.3 定时器前后对比

```
【现 在】                               【WebSocket 后】

lockCheckTimer  每 0.5s  HTTP  →      ❌ 移除（ws 连接隐含锁有效）
heartbeatTimer  每 10s   HTTP  →      ❌ 移除（ws ping/pong 替代）
_fullReloadTimer 每 5s   HTTP  →      ❌ 完全移除（ws 取代全部数据同步）
_healthTimer    每 2s    HTTP  →      ❌ 移除（ws 断开即知后端不可达）

每分钟请求：192 次                    每分钟请求：0 次（纯 WS）
```

---

## 六、前端架构改造

### 6.1 editor.js store 改造

#### 6.1.1 state 新增字段

```js
state: () => ({
  // ... 现有字段 ...
  _dataVersion: 0,           // 当前数据版本号
  _wsConnected: false,       // ws 连接状态
  _wsClient: null,           // ★ 使用独立 WsSyncClient 实例（非裸 WebSocket）
  _wsIntentionalClose: false,// 是否主动关闭（阻止自动重连）
  _requestId: 0,             // ★ 递增请求 ID（替代 _pendingLocalEdits）
})
```

#### 6.1.2 生命周期方法

```js
actions: {
  // ─── 全局启动（App.vue onMounted 调用） ───
  // ★ 文件浏览器模式的 WS 由 FileBrowser.vue 自行管理（见 §6.4）
  //    editor 模式的 WS 由 startEditorSync() 在进入编辑器时触发
  startPeriodicReload() {
    this.stopPeriodicReload()
    this._healthFailCount = 0
    this._startHealthCheck()  // ← 保留 2s HTTP 健康检查（全局）
    // WS 不在此时连接，FileBrowser.vue 或 startEditorSync() 各自管理
  },

  stopPeriodicReload() {
    this.stopEditorSync()
    if (this._healthTimer) {
      clearInterval(this._healthTimer)
      this._healthTimer = null
    }
  },

  // ─── 进入编辑器模式时调用（openFile / createNewFile 成功后） ───
  startEditorSync() {
    this._connectWebSocket()
  },

  // ─── 离开编辑器模式时调用（goBack / releaseSession 前） ───
  stopEditorSync() {
    this._wsIntentionalClose = true
    if (this._wsClient) {
      this._wsClient.disconnect()
      this._wsClient = null
    }
    this._wsConnected = false
  },

  // ─── WebSocket 连接管理（通过 WsSyncClient） ───
  _connectWebSocket() {
    if (this._wsClient?.connected) return

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsPort = parseInt(location.port) + 1  // ★ WS port = HTTP port + 1
    const wsUrl = `${protocol}//${location.hostname}:${wsPort}/ws`

    this._wsClient = new WsSyncClient({
      url: wsUrl,
      sessionId: getSessionId(),
      onMessage: (msg) => { this._applyWsMessage(msg) },
      onStatusChange: (status) => {
        if (status === 'connected') {
          this._wsConnected = true
        } else if (status === 'disconnected') {
          this._wsConnected = false
        }
      }
    })
    this._wsClient.connect()
  },

  // ═══════════════════════════════════════════
  // 核心：WebSocket 消息分发
  // ═══════════════════════════════════════════
  async _applyWsMessage(msg) {
    // 版本号去重
    if (msg.data_version && msg.data_version <= this._dataVersion) {
      return
    }
    if (msg.data_version) {
      this._dataVersion = msg.data_version
    }

    switch (msg.type) {

      // ── 全量快照 ──
      case 'full_sync': {
        const d = msg.data

        // ★ 锁状态检查：WS 断线期间锁可能被抢，重连后后端推 full_sync 时附带了 lock_status
        if (d.lock_status === 'lost') {
          this._applyWsMessage({ type: 'lock_stolen',
            data: { victim_session_id: getSessionId() } })
          return
        }

        this.messages = d.messages || []
        if (d.status) {
          this.backendDirty = d.status.modified || false
          this.undoCount = d.status.undo_count || 0
          this.redoCount = d.status.redo_count || 0
        }
        // ★ 检查 selectedMsgId 是否仍存在于新数据中（import 可能替换全部报文）
        if (this.selectedMsgId != null &&
            !this.messages.some(m => m.id === this.selectedMsgId)) {
          this.selectedMsgId = null
          this.messageCache = {}
          this.signalErrors = []
        }
        // ★ full_sync 已包含全量数据，无需 HTTP 补拉
        break
      }

      // ── 信号更新：按 uuid 原地替换（仅 patch 当前缓存报文） ──
      case 'signal_updated': {
        const { msg_id, signal } = msg.data

        // ★ 服务端值为准，直接覆盖乐观编辑
        const cache = this.messageCache[msg_id]
        if (cache) {
          const idx = cache.signals.findIndex(s => s.uuid === signal.uuid)
          if (idx >= 0) {
            cache.signals[idx] = signal
          }
        }
        // ★ signal_updated 不改变 signal_count，不需要更新 messages 列表
        break
      }

      // ── 信号添加 ──
      case 'signal_added': {
        const { msg_id, signal } = msg.data
        const cache = this.messageCache[msg_id]
        if (cache) {
          cache.signals = [...cache.signals, signal]
        }
        // 始终更新 messages 列表中的 signal_count
        const msgIdx = this.messages.findIndex(m => m.id === msg_id)
        if (msgIdx >= 0) {
          this.messages[msgIdx] = {
            ...this.messages[msgIdx],
            signal_count: cache ? cache.signals.length
              : this.messages[msgIdx].signal_count + 1
          }
        }
        break
      }

      // ── 信号删除 ──
      case 'signal_deleted': {
        const { msg_id, signal_uuid } = msg.data
        const cache = this.messageCache[msg_id]
        if (cache) {
          cache.signals = cache.signals.filter(s => s.uuid !== signal_uuid)
        }
        const msgIdx = this.messages.findIndex(m => m.id === msg_id)
        if (msgIdx >= 0) {
          this.messages[msgIdx] = {
            ...this.messages[msgIdx],
            signal_count: cache ? cache.signals.length
              : Math.max(0, this.messages[msgIdx].signal_count - 1)
          }
        }
        break
      }

      // ── 报文增/改/删 ──
      case 'message_added': {
        this.messages = [...this.messages, msg.data.message]
        break
      }
      case 'message_updated': {
        const m = msg.data.message
        const idx = this.messages.findIndex(x => x.id === m.id)
        if (idx >= 0) {
          this.messages[idx] = { ...this.messages[idx], ...m }
        }
        break
      }
      case 'message_deleted': {
        const deletedId = msg.data.msg_id
        this.messages = this.messages.filter(m => m.id !== deletedId)
        // ★ 清理当前选中状态
        if (this.selectedMsgId === deletedId) {
          this.selectedMsgId = null
          this.signalErrors = []
        }
        delete this.messageCache[deletedId]
        break
      }

      // ── 撤销/重做：广播自带完整数据，无需 HTTP 补拉 ──
      case 'undo_applied':
      case 'redo_applied': {
        if (msg.data.status) {
          this.backendDirty = msg.data.status.modified
          this.undoCount = msg.data.status.undo_count
          this.redoCount = msg.data.status.redo_count
        }
        // 全量报文列表（轻量，id+name+DLC+signal_count 不超过几 KB）
        if (msg.data.messages) {
          this.messages = msg.data.messages
        }
        // 受影响报文的详情（仅 changed_message_ids 涉及的报文）
        if (msg.data.message_details) {
          for (const [mid, detail] of Object.entries(msg.data.message_details)) {
            this.messageCache[parseInt(mid)] = detail
          }
        }
        break
      }

      // ── 状态变更 ──
      case 'status_changed': {
        const s = msg.data
        if ('modified' in s) this.backendDirty = s.modified
        if ('undo_count' in s) this.undoCount = s.undo_count
        if ('redo_count' in s) this.redoCount = s.redo_count
        if (s.save_error) {
          useUiStore().showToast(t('toast.autoSaveFailed', { error: s.save_error }), true)
        }
        break
      }

      case 'signal_errors_changed': {
        this.signalErrors = msg.data.errors || []
        break
      }

      // ── 锁被抢占（★ 完整清理 + 导航） ──
      case 'lock_stolen': {
        console.warn('[WS] lock stolen, victim:', msg.data?.victim_session_id,
                     msg.data?.stealer_session_id ? ', by: ' + msg.data.stealer_session_id : '')
        this._wsIntentionalClose = true
        // ★ 先清理 pending 请求，再断开连接（顺序不可反转）
        this._wsClient?._cleanupPendingRequests()
        this._wsClient?.disconnect()
        this._wsClient = null
        this._wsConnected = false
        this._wsClient?._cleanupPendingRequests()
        // ★ 清理编辑状态并导航回文件浏览器
        this.messages = []
        this.messageCache = {}
        this.selectedMsgId = null
        this.signalErrors = []
        this.clearUndoStack()
        // 触发 App.vue 返回文件浏览器
        window.dispatchEvent(new CustomEvent('navigate-browser'))
        useUiStore().showToast(t('toast.noEditPermission'), true)
        break
      }

      case 'pong':
        break
    }
  },

  // ═══════════════════════════════════════════
  // 辅助：乐观编辑保护
  // ═══════════════════════════════════════════

#### 6.1.3 编辑操作 —— 乐观更新 + WS request/response

```js
  // ★ 编辑信号：乐观更新 + WS 请求 → 服务端广播确认
  async updateSignal(sigUuid, field, value) {
    if (this.selectedMsgId == null) return
    const msg = this.messageCache[this.selectedMsgId]
    if (!msg) return
    const sig = msg.signals.find(s => s.uuid === sigUuid)
    if (!sig) return
    const oldVal = sig[field]

    // 乐观更新 (立即渲染)
    sig[field] = value
    this._localDirty = true

    try {
      await this._wsClient.request('edit_signal', {
        session_id: getSessionId(),
        msg_id: this.selectedMsgId,
        sig_uuid: sigUuid,
        field,
        value
      })
      // ok 响应 → 写入成功（不做额外操作，等广播 signal_updated 确认）
    } catch (e) {
      // error 响应 → 回滚乐观值
      sig[field] = oldVal
      useUiStore().showToast(e.message || '编辑失败', true)
    }
  },

  // ★ 布局拖拽松手后更新 start_bit（绕过防抖，立即发送）
  moveSignalByLayout(sigUuid, newStartBit) {
    this.updateSignal(sigUuid, 'start_bit', newStartBit, /* debounce */ false)
  },

  // ★ 自动修复 start_bit（绕过防抖，立即发送）
  autoFixSignal(sigUuid, newStartBit) {
    this.updateSignal(sigUuid, 'start_bit', newStartBit, /* debounce */ false)
  },

  // ★ 添加信号
  async addSignal(signalData) {
    if (this.selectedMsgId == null) return
    // ... 构建 fullData（与现有逻辑相同）...
    try {
      await this._wsClient.request('add_signal', {
        session_id: getSessionId(),
        msg_id: this.selectedMsgId,
        signal_data: fullData
      })
    } catch (e) {
      useUiStore().showToast(e.message || '添加失败', true)
    }
  },

  // ★ 删除信号（乐观删除 + WS 请求）
  async deleteSignal(sigUuid) {
    if (this.selectedMsgId == null) return
    const msg = this.messageCache[this.selectedMsgId]
    if (!msg) return
    const idx = msg.signals.findIndex(s => s.uuid === sigUuid)
    if (idx === -1) return
    const deleted = msg.signals.splice(idx, 1)[0]

    try {
      await this._wsClient.request('delete_signal', {
        session_id: getSessionId(),
        msg_id: this.selectedMsgId,
        sig_uuid: sigUuid
      })
    } catch (e) {
      // 回滚
      msg.signals.splice(idx, 0, deleted)
      useUiStore().showToast(e.message || '删除失败', true)
    }
  },

  // ★ 撤销（不再需要 loadMessages + loadSelectedMessage）
  async undo() {
    try {
      await this._wsClient.request('undo', { session_id: getSessionId() })
      // 前端等 undo_applied 广播 → _applyWsMessage 按 changed_message_ids 刷新
    } catch (e) {
      useUiStore().showToast(e.message || '撤销失败', true)
    }
  },

  // ★ 重做
  async redo() {
    try {
      await this._wsClient.request('redo', { session_id: getSessionId() })
    } catch (e) {
      useUiStore().showToast(e.message || '重做失败', true)
    }
  },

  // ★ 会话/文件操作
  async createSession() {
    const result = await this._wsClient.request('create_session', {})
    setSessionId(result.session_id)
  },

  async loadSession(sessionId) {
    const result = await this._wsClient.request('load_session', { session_id: sessionId })
    // full_sync 随后推送完整数据
  },

  async saveFile() {
    await this._wsClient.request('save', { session_id: getSessionId() })
    useUiStore().showToast('保存成功', false)
  },
}
```

### 6.2 ws-client.js（独立 WebSocket 连接管理类）

```js
/**
 * WebSocket Client — 前后端数据同步连接管理
 * 
 * 重连策略：指数退避（1s → 2s → 4s → ... → max 30s），无限次
 * 关闭码分类：4xxx 停止重连并通知 permanent_failure，其他码正常重连
 */
export class WsSyncClient {
  constructor({ url, sessionId, onMessage, onStatusChange }) {
    this.url = url
    this.sessionId = sessionId
    this.onMessage = onMessage
    this.onStatusChange = onStatusChange
    this._requestCounter = 0             // ★ 请求 ID 计数器
    this._pendingRequests = new Map()     // ★ requestId → { resolve, reject, timer }
    this._requestTimeout = 30000         // ★ 请求超时 30s
    this.baseDelay = 1000
    this.maxDelay = 30000
    this._intentionalClose = false
    this.ws = null
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return
    this._intentionalClose = false
    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      this.connected = true
      this.reconnectAttempt = 0
      this.onStatusChange?.('connected')
      this.ws.send(JSON.stringify({
        type: 'hello', session_id: this.sessionId, data_version: 0
      }))
      this._startPing()
    }

    this.ws.onmessage = (event) => this._handleMessage(event)

    this.ws.onclose = (event) => {
      this.connected = false
      this._stopPing()
      if (this._intentionalClose) return

      // ★ 4xxx 关闭码 = 永久失败，停止重连
      if (event.code >= 4000 && event.code < 5000) {
        this.onStatusChange?.('permanent_failure')
        return
      }

      this.onStatusChange?.('disconnected')
      const delay = Math.min(
        this.baseDelay * Math.pow(2, this.reconnectAttempt),
        this.maxDelay
      )
      this.reconnectAttempt++
      setTimeout(() => this.connect(), delay)
    }

    this.ws.onerror = () => { /* onclose follows */ }
  }

  disconnect() {
    this._intentionalClose = true
    this._stopPing()
    this._cleanupPendingRequests()
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    this.connected = false
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  // ★ 新：请求-响应模式
  request(type, data) {
    return new Promise((resolve, reject) => {
      const requestId = `r${++this._requestCounter}_${Date.now()}`
      const timer = setTimeout(() => {
        this._pendingRequests.delete(requestId)
        reject(new Error(`Request ${type} timed out`))
      }, this._requestTimeout)

      this._pendingRequests.set(requestId, { resolve, reject, timer })
      this.send({ type, requestId, data })
    })
  }

  // ★ 修改 onmessage：分叉 ok/error（响应）vs 其他（广播）
  _handleMessage(event) {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'ok' || msg.type === 'error') {
        // 响应 → 匹配 pending promise
        const pending = this._pendingRequests.get(msg.requestId)
        if (pending) {
          clearTimeout(pending.timer)
          this._pendingRequests.delete(msg.requestId)
          if (msg.type === 'ok') {
            pending.resolve(msg.data)
          } else {
            pending.reject(new ApiError(msg.message, msg.code))
          }
        }
      } else {
        // 广播 → 走原有处理链路
        this.onMessage?.(msg)
      }
    } catch (e) {
      console.error('[WsSyncClient] parse error:', e)
    }
  }

  // ★ 重连时清理所有未完成请求
  _cleanupPendingRequests() {
    for (const [id, pending] of this._pendingRequests) {
      clearTimeout(pending.timer)
      pending.reject(new Error('Connection lost'))
    }
    this._pendingRequests.clear()
  }

  _startPing() { /* ... 同前 ... */ }
  _stopPing() { /* ... 同前 ... */ }
}
```

请求冲突处理策略：

```js
// ★ updateSignal 防抖：同一信号字段 300ms 内重复编辑 → 合并为新值
//   debounce 参数：文本输入 @blur 使用防抖（默认 true），布局拖拽绕行直接发送（false）
const PENDING_EDITS = new Map()  // key: "signal_uuid_field" → {timer, abortFn}

async updateSignal(sigUuid, field, value, debounce = true) {
  const key = `${sigUuid}_${field}`
  if (PENDING_EDITS.has(key)) {
    const prev = PENDING_EDITS.get(key)
    clearTimeout(prev.timer)
    prev.abortFn?.()  // ★ 标记旧请求为"被取代"，reject 时跳过回滚
  }
  const oldVal = sig[field]
  // ... 乐观更新 ...

  let aborted = false
  PENDING_EDITS.set(key, {
    timer: setTimeout(async () => {
      PENDING_EDITS.delete(key)
      try {
        await this._wsClient.request('edit_signal', { ... })
      } catch (e) {
        if (!aborted) { sig[field] = oldVal }  // 仅未被取代时才回滚
      }
    }, debounce ? 300 : 0),
    abortFn: () => { aborted = true }
  })
}
```

### 6.3 App.vue 改动

```js
// ─── 生命周期 ───
onMounted(() => {
  store.startPeriodicReload()  // 仅启动健康检查，不建 WS
  // ❌ 移除 initTabSync()         — BroadcastChannel 由 WS lock_stolen 替代
  // ❌ 移除 lockCheckTimer        — 连接维持即锁有效
  // ❌ 移除 heartbeatTimer        — WS ping/pong 替代
  // ✅ 保留 beforeunloadHandler    — 页面关闭时释放锁
})

onUnmounted(() => {
  store.stopPeriodicReload()
  // ❌ 移除 cleanupTabSync()
})

// ─── 编辑器进入/退出 ───
async function openFile(sessionId) {
  fileBrowserWsClient?.disconnect()  // ★ 先关 FileBrowser WS（见 §6.4）
  await store.loadHistorySession(sessionId)
  mode.value = 'editor'
  store.startEditorSync()  // ★ 再开 Editor WS
}

async function goBack() {
  store.stopEditorSync()   // ★ 断开 WS
  await store.releaseSession()
  // ... 清理状态 ...
  mode.value = 'browser'
}

// ─── WS lock_stolen 处理 ───
// 监听 store 分发的导航事件
window.addEventListener('navigate-browser', () => {
  if (mode.value === 'editor') goBack()
})
```

### 6.4 FileBrowser.vue 改造

文件浏览器模式建立独立的 WS 连接（hello 无 session_id → 服务端返回 `session_created`）。
进入编辑器时 App.vue `openFile()` 先断开此 WS，再由 `startEditorSync()` 建立编辑器 WS。

```js
// FileBrowser.vue <script setup>
import { getSessionId, setSessionId } from './api/client.js'

let wsClient = null

onMounted(() => {
  wsClient = new WsSyncClient({
    url: wsUrl,
    sessionId: '',  // 浏览器模式无 session_id
    onMessage: handleWsMessage,
    onStatusChange: handleStatus
  })
  wsClient.connect()
})

onBeforeUnmount(() => { wsClient?.disconnect() })

function handleWsMessage(msg) {
  if (msg.type === 'session_created') {
    setSessionId(msg.data.session_id)
    wsClient.sessionId = msg.data.session_id
  }
}

// ★ 原 HTTP api() 调用改写：
async function loadSessions() {
  const data = await wsClient.request('get_sessions', {
    exclude_session: getSessionId()
  })
  sessions.value = data.sessions
}

async function deleteSession(sid) {
  await wsClient.request('delete_session', { session_id: sid })
}

async function stealLock(sid) {
  await wsClient.request('steal_lock', { target_session_id: sid })
}

async function createNewFile() {
  await wsClient.request('new_file', {})
}
```

---

## 七、后端架构改造

### 7.1 CanDatabase 线程安全增强

```python
# models.py

class CanDatabase:
    def __init__(self, name: str = "Untitled"):
        self.name = name
        self.messages: dict[int, Message] = {}
        self.modified = False
        self.__lock = threading.RLock()        # 已有
        self.data_version = 0                  # ★ 新增：数据版本号

    def with_lock(self):
        """返回锁上下文管理器，供外部需要原子操作时使用。"""
        return self.__lock                     # 已有

    def _bump_version(self) -> int:
        """原子递增版本号。必须在 __lock 持有下调用。
        返回新版本号，调用方应使用返回值而非再次读取 data_version。"""
        self.data_version += 1
        return self.data_version

    def _bump_version_safe(self) -> int:
        """带锁的安全版本，供锁外调用方使用。"""
        with self.__lock:
            self.data_version += 1
            return self.data_version
```

**关键约束：**
- `data_version += 1` 不是原子操作，必须持有 `__lock`
- `_bump_version()` 应在 CRUD 操作的同一锁区间内调用（与数据变更一起原子化）
- API handler 应使用 `_bump_version()` 的返回值作为广播的 version，而非再次读取 `db.data_version`
- `validate_all_signals()` 等只读方法遍历 `self.messages` 时需加锁（防止并发修改抛出 `RuntimeError`）

### 7.2 WebSocket 服务端（ws_server.py）

架构从单一广播器重构为三层：

```
WsTransport（传输层）→ MessageRouter（路由层）→ Handlers（业务层）
```

#### 7.2.1 传输层

```python
"""ws_transport.py — WebSocket I/O 封装"""

class WsTransport:
    """所有 WebSocket 网络 I/O 的唯一出口。上层模块不接触 ws/asyncio。"""

    def __init__(self, host="127.0.0.1", port=8081, diagnostics=None):
        self.host, self.port = host, port
        self.loop = None
        self._clients: dict[str, set] = {}  # session_id → {ws}
        self._lock = threading.Lock()
        self.diag = diagnostics or WsDiagnostics(enabled=False)

    # ── 连接管理 ──
    def register(self, session_id, ws):
        with self._lock:
            self._clients.setdefault(session_id, set()).add(ws)

    def unregister(self, session_id, ws):
        with self._lock:
            clients = self._clients.get(session_id)
            if clients:
                clients.discard(ws)
                if not clients:
                    del self._clients[session_id]

    # ── 单播（请求-响应） ──
    async def reply(self, ws, msg: dict):
        await ws.send(json.dumps(msg, ensure_ascii=False))

    # ── 广播（异步安全，可从任何线程调用） ──
    def broadcast(self, session_id: str, msg: dict):
        if not self.loop or self.loop.is_closed():
            return
        if self.diag.enabled:
            self.diag.info("broadcast", session=session_id[:8],
                           type=msg.get("type"), version=msg.get("data_version"))
            with self.diag._counter_lock:
                self.diag.broadcasts += 1
        msg_json = json.dumps(msg, ensure_ascii=False)
        with self._lock:
            clients = list(self._clients.get(session_id, set()))
        for ws in clients:
            asyncio.run_coroutine_threadsafe(
                self._safe_send(ws, msg_json), self.loop)

    def broadcast_all(self, msg: dict):
        """向所有已注册 session 广播。"""
        with self._lock:
            all_sids = list(self._clients.keys())
        for sid in all_sids:
            self.broadcast(sid, msg)

    async def _safe_send(self, ws, msg_json: str):
        try:
            await ws.send(msg_json)
        except websockets.exceptions.ConnectionClosed:
            pass
```

#### 7.2.2 路由层

```python
"""ws_router.py — type → handler 分发"""

class MessageRouter:
    def __init__(self, transport: WsTransport, session_mgr):
        self._transport = transport
        self._session_mgr = session_mgr
        self._handlers: dict[str, callable] = {}

    def register(self, msg_type: str, handler):
        self._handlers[msg_type] = handler

    async def dispatch(self, ws, msg: dict):
        msg_type = msg.get("type")
        handler = self._handlers.get(msg_type)
        if not handler:
            await self._transport.reply(ws, {
                "type": "error", "requestId": msg.get("requestId"),
                "code": "UNKNOWN_TYPE", "message": f"Unknown: {msg_type}"
            })
            return

        try:
            result = await handler(msg.get("data", {}))
            # 回复请求者
            await self._transport.reply(ws, {
                "type": "ok", "requestId": msg["requestId"],
                "data": result.data, "new_version": result.new_version
            })
            # 广播事件
            for event in result.events:
                self._transport.broadcast(result.session_id, event)
            return result  # ★ 返回给 _handler 协程，用于 session 切换检测（new_file/import_file）
        except HandlerError as e:
            await self._transport.reply(ws, {
                "type": "error", "requestId": msg.get("requestId"),
                "code": e.code, "message": e.message, "details": e.details
            })
        except Exception as e:
            # 兜底：Handler bug 不应断开 WS 连接
            print(f"[WS] handler exception: {type(e).__name__}: {e}")
            await self._transport.reply(ws, {
                "type": "error", "requestId": msg.get("requestId"),
                "code": "INTERNAL_ERROR", "message": str(e)
            })
```

#### 7.2.3 Handler 注册

```python
# ws_server.py main() 入口
router = MessageRouter(transport, session_mgr)

# ── 信号 CRUD ──
router.register("edit_signal",     EditSignalHandler(session_mgr))
router.register("add_signal",      AddSignalHandler(session_mgr))
router.register("delete_signal",   DeleteSignalHandler(session_mgr))
router.register("batch_add_signals", BatchAddSignalsHandler(session_mgr))

# ── 报文 CRUD ──
router.register("edit_message",    EditMessageHandler(session_mgr))
router.register("add_message",     AddMessageHandler(session_mgr))
router.register("delete_message",  DeleteMessageHandler(session_mgr))

# ── 操作 ──
router.register("undo",            UndoHandler(session_mgr))
router.register("redo",            RedoHandler(session_mgr))
router.register("save",            SaveHandler(session_mgr))
router.register("new_file",        NewFileHandler(session_mgr))
router.register("import_file",     ImportFileHandler(session_mgr))
router.register("export_file",     ExportFileHandler(session_mgr))

# ── 会话/锁管理 ──
router.register("create_session",  CreateSessionHandler(session_mgr))
router.register("load_session",    LoadSessionHandler(session_mgr))
router.register("rename_session",  RenameSessionHandler(session_mgr))
router.register("delete_session",  DeleteSessionHandler(session_mgr))
router.register("get_sessions",    GetSessionsHandler(session_mgr))
router.register("release_lock",    ReleaseLockHandler(session_mgr))
router.register("steal_lock",      StealLockHandler(session_mgr))

# ── 工具 ──
router.register("download_file",   DownloadFileHandler(session_mgr))
router.register("get_summary",     GetSummaryHandler(session_mgr))
router.register("get_session_info", GetSessionInfoHandler(session_mgr))
router.register("get_message",     GetMessageHandler(session_mgr))
router.register("get_signal_errors", GetSignalErrorsHandler(session_mgr))
```

#### 7.2.4 _handler 协程（连接生命周期）

```python
# ws_server.py

async def _handler(self, ws):
    session_id = None
    try:
        # 等待 hello
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
        except asyncio.TimeoutError:
            if self.diag.enabled:
                with self.diag._counter_lock:
                    self.diag.hello_timeouts += 1
            await ws.close(4001, "hello timeout")
            return

        msg = json.loads(raw)
        if msg.get("type") != "hello":
            await ws.close(4002, "expected hello")
            return

        session_id = msg.get("session_id", "")

        # ★ 首次连接（无 session_id）：创建新 session 并立即注册
        if not session_id:
            sm = get_session_manager()
            session_id = sm.create(file_name="", db=CanDatabase())  # ★ 使用正确的 create() 方法
            # ★ 使用专用 session_created 消息（非 ok，hello 无 requestId）
            await ws.send(json.dumps({
                "type": "session_created",
                "data": {"session_id": session_id}
            }, ensure_ascii=False))
            # ★ 不 return — 继续注册 + full_sync（同一连接）

        # 验证 + 注册
        session = get_session_manager().get(session_id)
        if not session:
            # ★ 旧 session 已丢失（后端重启/超时清理），创建新 session 恢复
            sm = get_session_manager()
            session_id = sm.create(file_name="", db=CanDatabase())  # ★ 使用正确的 create() 方法
            await ws.send(json.dumps({
                "type": "session_recovered",
                "data": {"session_id": session_id, "reason": "session_not_found"}
            }, ensure_ascii=False))
            # 继续注册 + full_sync（不 return）

        self._transport.register(session_id, ws)

        # 推送 full_sync
        await self._send_full_sync(ws, session_id)

        # 循环接收消息
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "ping":
                try:
                    await ws.send(json.dumps({"type": "pong"}))
                    get_session_manager().update_heartbeat(session_id)
                except Exception as e:
                    print(f"[WS] ping handler error: {e}")
            elif "requestId" in msg:
                # ★ 请求-响应类型：路由到 handler
                result = await self._router.dispatch(ws, msg)
                # ★ session 切换同步（new_file/import_file 可能改变 session_id）
                if result and result.new_session_id:
                    self._transport.unregister(session_id, ws)
                    session_id = result.new_session_id
                    self._transport.register(session_id, ws)
                    get_session_manager().update_heartbeat(session_id)

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[WS] handler error: {e}")
    finally:
        if session_id:
            self._transport.unregister(session_id, ws)
            get_session_manager().mark_stale(session_id)

async def _send_full_sync(self, ws, session_id: str):
    """构建并发送全量快照"""
    mgr = get_session_manager()
    session = mgr.get(session_id)
    if not session:
        return
    db = session.db
    with db.with_lock():
        messages_data = [
            {"id": mid, "id_hex": f"0x{mid:X}", "name": m.name,
             "dlc": m.dlc, "cycle_time": m.cycle_time, "signal_count": len(m.signals)}
            for mid, m in sorted(db.messages.items())
        ]
        status = {"modified": db.modified, "undo_count": len(session.undo_stack),
                   "redo_count": len(session.redo_stack), "save_error": session.save_error}
        version = db.data_version
    lock_held = mgr.has_lock(session_id)
    await ws.send(json.dumps({
        "type": "full_sync", "data_version": version,
        "data": {"messages": messages_data, "status": status,
                 "lock_status": "held" if lock_held else "lost",
                 "selected_message": None, "selected_errors": None}
    }, ensure_ascii=False))

# ── 服务启动（不变） ──
async def _serve(self):
    async with websockets.serve(self._handler, self.host, self.port,
                                 ping_interval=None, close_timeout=5):
        await asyncio.Future()

def start_in_thread(self):
    ready = threading.Event()
    def _run():
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        ready.set()
        self.loop.run_until_complete(self._serve())
    t = threading.Thread(target=_run, daemon=True, name="ws-server")
    t.start()
    ready.wait(timeout=3)
    return t
```

#### 7.2.5 Undo Handler 示例（广播完整数据）

```python
# handlers.py

class UndoHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    async def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND")
        if not session.undo_stack:
            raise HandlerError("UNDO_EMPTY", "撤销栈为空")

        # ★ 在锁内完成栈操作 + 数据变更（原子性）
        with session.db.with_lock():
            if not session.undo_stack:
                raise HandlerError("UNDO_EMPTY")
            snap = session.undo_stack.pop()        # ★ pop undo 栈
            session.redo_stack.append(snap)        # ★ push redo 栈

            self._sm._execute_undo(session, snap)  # (session, snap) 两参数
            session.db.modified = True
            # ★ 按快照类型分别提取 changed_ids（message_delete 快照无顶层 msgId）
            if snap["type"] == "message_delete":
                restored_id = snap["data"].get("id")
                changed_ids = [restored_id] if restored_id is not None else []
            else:
                changed_ids = [snap.get("msgId")]  # camelCase（与 _execute_undo 一致）

            message_details = {}
            for mid in changed_ids:
                m = session.db.messages.get(mid)
                if m:
                    message_details[str(mid)] = m.to_dict()

            messages = [
                {"id": mid, "id_hex": f"0x{mid:X}", "name": m.name,
                 "dlc": m.dlc, "cycle_time": m.cycle_time, "signal_count": len(m.signals)}
                for mid, m in sorted(session.db.messages.items())
            ]
            status = {"modified": session.db.modified,
                      "undo_count": len(session.undo_stack),
                      "redo_count": len(session.redo_stack)}
            version = session.db._bump_version()

            # ★ 在 bump 之后构建信号错误事件（使用新版本号，避免被前端 version gate 丢弃）
            signal_errors_events = []
            for mid in changed_ids:
                errors = session.db.validate_all_signals(mid)
                if errors:
                    signal_errors_events.append({
                        "type": "signal_errors_changed",
                        "data_version": version,
                        "data": {"msg_id": mid, "errors": errors}
                    })

        event = {
            "type": "undo_applied",
            "data_version": version,
            "data": {
                "changed_message_ids": changed_ids,
                "status": status,
                "messages": messages,
                "message_details": message_details
            }
        }
        return HandlerResult(
            data={"changed_message_ids": changed_ids},
            events=[event] + signal_errors_events,
            new_version=version,
            session_id=sid
        )
```

> ★ Handler 线程模型：Handler 声明为 `async def` 是因 MessageRouter 的 dispatch 是 async，但内部操作（`db.with_lock()`、栈操作、`to_dict()`）均为同步阻塞。实际运行时通过 `asyncio.to_thread()` 或 `loop.run_in_executor()` 在线程池中执行，避免阻塞 asyncio event loop：
> ```python
> # ws_router.py dispatch 中
> result = await asyncio.to_thread(handler, msg["data"])
> ```

### 7.2.6 自动保存线程与 WS 广播集成


> - 保存成功 →  → 前端  复位
> - 保存失败 →  → 前端触发 Toast 提示
> -  需在 SessionManager 中新增，内部遍历 + 回调

### 7.3 api_server.py 改造点

> ★ 所有 CRUD + 会话 + 文件 I/O 的 HTTP handler 均已移除。
> HTTP server 仅保留：① 静态文件服务（`GET /*`） ② 诊断接口（`GET /api/diag`）

**文件浏览器模式**同样建立 WS 连接——`hello` 发送时不带 `session_id`，服务端自动创建新会话并返回 `session_id`（见 §7.2.4 首次连接逻辑）。浏览器模式下的所有操作（列表、新建、删除、导入、锁抢占）均通过同一 WS 连接执行。

### 7.4 main() 入口简化

> HTTP handler 已全部移除。CRUD 逻辑由 Handler 层实现（§7.2.3）。
> 旧 §7.3 的 `_put_signal` / `_post_undo` 等 HTTP handler 代码已删除，
> 替换为 `EditSignalHandler` / `UndoHandler` 等 WS handler（见 §7.2.5）。

```python
# api_server.py main()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()

    # 启动 WS 服务（port + 1）
    transport = WsTransport(port=args.port + 1,
                            diagnostics=WsDiagnostics(enabled='--ws-debug' in sys.argv))
    router = MessageRouter(transport, SESSION_MGR)
    # ... 注册所有 handler（§7.2.3）...
    ws_server = WsServer(transport, router)
    ws_thread = ws_server.start_in_thread()

    # 注册锁释放回调
    SESSION_MGR.set_lock_released_callback(
        lambda sid: transport.broadcast(sid, {
            "type": "lock_stolen", "data": {"victim_session_id": sid}
        })
    )

    # HTTP server 仅保留静态文件 + 诊断
    HTTPServer((host, args.port), StaticFileHandler).serve_forever()
```

### 7.5 移除项总结

| 移除项 | 原位置 | 替代 |
|---|---|---|
| `_put_signal` / `_post_signal` / `_delete_signal` | api_server.py | `EditSignalHandler` / `AddSignalHandler` / `DeleteSignalHandler` |
| `_post_undo` / `_post_redo` | api_server.py | `UndoHandler` / `RedoHandler` |
| `_post_save` / `_post_new` / `_post_import` / `_post_export` | api_server.py | `SaveHandler` / `NewFileHandler` / `ImportFileHandler` / `ExportFileHandler` |
| `_post_session` / `_post_load` / `_put_session` / `_delete_session` | api_server.py | `CreateSessionHandler` / `LoadSessionHandler` / `RenameSessionHandler` / `DeleteSessionHandler` |
| `_post_heartbeat` / `_post_release` / `_post_steal` | api_server.py | WS ping / `ReleaseLockHandler` / `StealLockHandler` |
| `_get_messages` / `_get_message` / `_get_status` / `_get_sessions` | api_server.py | `full_sync` 广播 / `GetSessionsHandler` |
| `BROADCASTER` 全局变量 | api_server.py | `WsTransport` 通过依赖注入 |
| `_broadcast_change` 辅助函数 | api_server.py | `MessageRouter.dispatch` 自动处理 |

### 7.6 session_manager.py 保留项

| 方法 | 用途 | 变更 |
|---|---|---|
| `create_session(...)` | 创建新会话 | 无变更 |
| `get(session_id)` | 获取会话 + 续期 | 无变更 |
| `save(session_id)` | 保存到磁盘 | 无变更 |
| `release_session(session_id)` | 释放文件锁 | 无变更 |
| `update_heartbeat(session_id)` | ping 更新心跳 | 无变更 |
| `has_lock(session_id)` | 检查是否持锁 | 新增（§7.8） |
| `mark_stale(session_id)` | 标记即将超时 | ★ 新增（见下方伪代码） |
| `_cleanup_stale_heartbeats()` | 心跳超时清理 | 已存在（回调 lock_stolen） |
| `set_lock_released_callback(cb)` | 注册锁释放回调 | 已存在（§7.7） |

#### mark_stale 伪代码

```python
# session_manager.py
def mark_stale(self, session_id: str):
    """将心跳前推至即将超时，使 _cleanup_stale_heartbeats 尽快释放锁。
    WS disconnection finally 块中调用。"""
    with self._lock:  # ★ 与 _cleanup_stale_heartbeats / release_session 互斥
        if session_id in self._heartbeats:
            self._heartbeats[session_id] = time.time() - (HEARTBEAT_TIMEOUT - 10)
```

> 页面关闭时 `_handler` finally 的 `mark_stale` 可将锁释放时间从最长 2×HEARTBEAT_CLEANUP_INTERVAL 缩短至 ~10s。
> 如需即时释放，可额外保留 `POST /api/release` 端点专供 `sendBeacon` 使用。

### 7.7 旧广播辅助方法移除

已移除的广播器便捷方法（现由 `HandlerResult.events` 自动广播）：

`broadcast_signal_updated` `broadcast_signal_added` `broadcast_signal_deleted` `broadcast_message_added` `broadcast_message_updated` `broadcast_message_deleted` `broadcast_undo` `broadcast_redo` `broadcast_status` `broadcast_signal_errors` — 全部替换为 Handler 返回 `events` 列表，Router 统一广播。

---

## 八、文件结构规划

```
新增文件:
  docs/
    websocket-architecture.md        ← 本文档
    websocket-architecture-issue.md   ← 审查意见文档

  ws_server.py                       ← WebSocket 服务端（WsTransport + MessageRouter + Handlers）
  frontend/src/utils/
    ws-client.js                     ← WebSocket 客户端连接管理类

修改文件:
  requirements.txt                   ← 添加 websockets>=12.0
  models.py                          ← data_version + _bump_version + 锁增强
  session_manager.py                 ← undo/redo 返回 changed_message_ids + 心跳超时广播
  api_server.py                      ← HTTPServer→ThreadingHTTPServer + 广播插入 + WS启动 + GET /api/diag
  ws_server.py                       ← WsDiagnostics 类 + broadcast/_handler 埋点
  frontend/src/stores/
    editor.js                        ← _applyWsMessage + ws 连接管理 + pendingLocalEdits + 埋点
  frontend/src/utils/
    ws-client.js                     ← WsFrontendDiag 对象 + window.__ws_diag__
  frontend/src/App.vue               ← 移除 BroadcastChannel / lockCheckTimer / heartbeatTimer
  frontend/src/api/
    client.js                        ← 移除 BroadcastChannel 代码（initTabSync 等）
```

---

## 九、关键设计决策说明

### 9.1 为什么 undo/redo 广播携带完整数据？

全 WS 架构下无 HTTP 可用。undo/redo 广播自带：
- `messages`：全量报文列表（id+name+DLC+signal_count，数 KB）
- `message_details`：受影响报文详情
undo/redo 频率低（秒级），完全在 WS 帧容量内，无需按需拉取。
3. undo/redo 频率低，额外 1-2 次 HTTP 调用完全可以接受

### 9.2 为什么 ws 心跳不能替代 2s HTTP 健康检查？

ws 的 ping/pong 只能判断 ws 连接是否存活。但 `GET /api/status` 还承担了判断"后端 HTTP server 进程是否还在运行"的职责——ws 可能因 ws 端口问题断开，但 HTTP 仍然正常。因此 `/api/status` 的 2s 检查保留，作为独立的进程存活探针。

### 9.3 为什么 0.5s lockCheck 可以并入 ws？

- ws 建连时已验证 session_id，连接维持 = 锁有效
- 后端检测到锁被抢占 → 调用 `broadcast_lock_stolen` + 主动关闭 ws
- 前端 ws.onclose（收到 lock_stolen）→ 弹 toast → 返回文件浏览器

这样 `lockCheckTimer`（每 0.5s 120 次请求/分钟）可以被 ws 完全替代。

### 9.4 为什么增量事件推送完整对象而非部分字段？

```jsonc
// ✅ 好的做法：推送完整对象
{ "type": "signal_updated", "data": { "msg_id": 256, "signal": {全部字段} } }

// ❌ 坏的做法：只推送变更字段
{ "type": "signal_updated", "data": { "msg_id": 256, "signal_uuid": "...",
    "changes": { "start_bit": 48 } } }
```

原因：推送完整对象保证事件的**自包含性**和**幂等性**：
- 前端收到后，直接 `cache.signals[idx] = signal`，无需合并逻辑
- 如果旧事件因为重连延迟到达，版本号去重直接丢弃，不需要处理部分合并
- signal 对象通常 < 500 bytes，带宽开销可忽略

### 9.5 为什么 ws 端口独立于 HTTP？

Python `http.server.ThreadingHTTPServer` 是同步阻塞模型，而 `websockets` 是 asyncio 异步模型，两者无法共用同一端口。ws 服务运行在独立线程的 event loop 中，采用偏移策略：**WS port = HTTP port + 1**。（详见 §3.1.1）

### 9.6 WS 消息体大小限制

WebSocket 文本帧无硬性上限，但实际受限于 `websockets` 库默认 `max_size = 2 ** 20`（1MB）。

| 消息类型 | 典型大小 | 风险 |
|---|---|---|
| `edit_signal` 请求 | < 500 B | ✅ |
| `full_sync` 全量快照 | < 50 KB | ✅ |
| `undo_applied`（含全量 messages + details） | < 200 KB | ✅ |
| `import_file` / `export_file`（DBC 文本） | 通常 < 500 KB，大型网络可达 5 MB | ⚠️ |

**处理策略**：
1. 服务端设置 `max_size = 10 * 1024 * 1024`（10MB），覆盖实际场景
2. 超限消息：websockets 自动返回 1009（Message Too Big）→ 前端 `request()` reject → 显示 Toast 提示
3. 极端情况（> 10MB）：提示用户拆分为多个文件

### 9.7 ws 断线处理

ws 断线后由 `WsSyncClient` 自动指数退避重连（1s → 2s → 4s → ... → 30s）。
重连成功后，服务端推送全量快照（`full_sync`），前端覆盖全部 store 数据，保证一致性。

断线期间不缓存增量事件。重连时客户端发送 `hello {data_version: 0}`，服务端推送全量快照覆盖全部 store 数据。

**关键：不存在 HTTP 降级兜底。** ws 断线只重连，不退回旧的轮询机制。
旧的 `_fullReloadTimer`、`lockCheckTimer`、`heartbeatTimer` 在改造后彻底移除。

### 9.8 并发安全

引入 WS 后系统首次面临真正的多线程并发。关键在于：
1. **HTTP Server 必须升级为 `ThreadingHTTPServer`**（原 `HTTPServer` 为单线程）
2. 所有 CRUD handler 的"读-校验-写-推撤销栈-快照-递增版本号"必须在 `with db.with_lock():` 内原子完成
3. 广播（`WsTransport.broadcast()`）通过 `asyncio.run_coroutine_threadsafe` 跨线程安全执行，不阻塞 Handler 线程
4. `_build_full_sync()` 在锁内遍历 `db.messages`，防止 `RuntimeError`
5. `data_version` 的递增使用锁内 `_bump_version()` 返回值，避免 TOCTOU

### 9.9 WS 断线时的文件锁释放

页面关闭时通过 `navigator.sendBeacon('/api/release')` 释放文件锁，但 beacon 非 100% 可靠。
WS 连接关闭时，`_handler` 的 `finally` 块应主动标记 session 的心跳超时，缩短后端 `_cleanup_stale_heartbeats` 等待时间（从最长 60s 降到 5-10s）。

```python
# ws_server.py _handler finally 块
finally:
    if session_id:
        self.unregister(session_id, ws)
        # ★ 主动标记 session 可能已离线，缩短锁释放等待
        from session_manager import get_session_manager
        get_session_manager().mark_stale(session_id)
        # 将 _heartbeats[sid] 前推至即将超时，下轮 _cleanup_stale_heartbeats 即可释放锁
```

### 9.10 BroadcastChannel 移除

现有 `BroadcastChannel`（`canmatrix_tab_sync`）用于同浏览器标签页间通知 session 抢占，由 WS `lock_stolen` 事件完全替代：
- 后端 `_post_steal` + 心跳超时释放时 → 广播 `lock_stolen` → 前端清理状态 + 导航
- WS 建连时已验证 session_id，连接维持 = 锁有效
- 移除了 `initTabSync()` / `cleanupTabSync()` / `notifySessionChange()` / `notifySessionStolen()`

### 9.11 可开关的诊断/日志系统

#### 9.11.1 设计目标

- **CLI 可控**：后端通过 `--ws-debug` 参数开关，前端通过 `?ws_debug=1` URL 参数
- **结构化输出**：JSON 格式，`grep` / `jq` 可直接解析
- **零开销关闭**：开关关闭时所有日志代码不执行（计数器不递增、`performance.now()` 不调用）
- **前/后端统一**：共享字段命名约定，方便跨端关联分析

#### 9.11.2 开关方式

```
后端启动:  python api_server.py --ws-debug
          python api_server.py           # 默认关闭

前端访问:  http://localhost:8080/?ws_debug=1
          http://localhost:8080/           # 默认关闭
          localStorage.setItem('ws_debug', '1')  # 持久化开启
```

#### 9.11.3 后端诊断类（ws_server.py）

```python
import json
import time
from collections import defaultdict
from contextlib import contextmanager

class WsDiagnostics:
    """WebSocket 稳定性/性能诊断。

    开关：构造函数 `enabled` 参数，由 `--ws-debug` CLI 控制。
    输出：JSON lines，每行一条事件，可直接 `| jq` 解析。
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._start = time.time()
        self._counter_lock = threading.Lock()  # ★ 线程安全保护

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
        # JSON lines 格式，每行一条
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
        """上下文管理器，自动计时并记录。

        with diag.timed("full_sync_build"):
            data = self._build_full_sync(session_id)
        """
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
                    "p50_ms": round(sorted_samples[len(samples)//2], 2),
                    "p99_ms": round(sorted_samples[int(len(samples)*0.99)], 2),
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


# ═══ 在 WsTransport 中埋点 ═══

class WsTransport:
    def __init__(self, host="127.0.0.1", port=8081, diagnostics=None):
        # ... 现有字段 ...
        self.diag = diagnostics or WsDiagnostics(enabled=False)

    def broadcast(self, session_id, message):
        if not self.loop or self.loop.is_closed():
            if self.diag.enabled:
                self.diag.warn("broadcast_skip", reason="loop_unavailable")
            return
        if self.diag.enabled:
            self.diag.info("broadcast",
                           session=session_id[:8],
                           type=message.get("type"),
                           version=message.get("data_version"))
            with self.diag._counter_lock:
                self.diag.broadcasts += 1
                self.diag.broadcast_by_type[message.get("type", "unknown")] += 1
        # ... 原有广播逻辑 ...

    async def _handler(self, ws):
        # ... 建连后 ...
        with self.diag._counter_lock:
            self.diag.connects += 1
        self.diag.info("ws_connect", session=session_id[:8])
        try:
            # ... 原有逻辑（hello_timeout 分支递增 hello_timeouts）...
        finally:
            with self.diag._counter_lock:
                self.diag.disconnects += 1
            self.diag.info("ws_disconnect", session=session_id[:8])

    def broadcast_lock_stolen(self, session_id: str, stealer_sid: str = ""):
        with self.diag._counter_lock:
            self.diag.lock_stolen_sent += 1
        # ... 调用上方更新后的 broadcast_lock_stolen 方法 ...
        # ... 原有广播逻辑 ...
```

#### 9.11.4 前端诊断（ws-client.js + editor store）

```js
/**
 * 前端 WS 诊断
 *
 * 开关：
 *   1. URL 参数 ?ws_debug=1
 *   2. localStorage.setItem('ws_debug', '1')
 *   3. 控制台 window.__ws_diag__.enable()
 *
 * 脚本查询：window.__ws_diag__.snapshot()
 */
const WsFrontendDiag = {
  _enabled: false,
  _counters: { connects: 0, disconnects: 0, msg_received: 0, msg_dropped: 0,
                lock_stolen: 0, full_sync: 0, signal_updated: 0 },
  _timings: {},
  _lastVersion: 0,

  enable()  { this._enabled = true; console.log('[WS-DIAG] enabled') },
  disable() { this._enabled = false },

  _init() {
    if (new URLSearchParams(location.search).get('ws_debug') === '1'
        || localStorage.getItem('ws_debug') === '1') {
      this.enable()
    }
  },

  _log(level, event, data = {}) {
    if (!this._enabled) return
    const record = { ts: performance.now(), level, event, ...data }
    console.log(`[WS-DIAG] ${event}`, record)
  },

  count(name) {
    if (!this._enabled) return
    this._counters[name] = (this._counters[name] || 0) + 1
  },

  /** 返回 stop 函数 */
  timeStart(label) {
    if (!this._enabled) return () => {}
    const t0 = performance.now()
    return () => {
      const elapsed = performance.now() - t0
      const arr = this._timings[label] || (this._timings[label] = [])
      arr.push(elapsed)
      if (arr.length > 100) arr.shift()
    }
  },

  snapshot() {
    const avg = {}
    for (const [k, v] of Object.entries(this._timings)) {
      if (v.length) avg[k] = {
        avg_ms: Math.round(v.reduce((a,b)=>a+b,0)/v.length*100)/100,
        samples: v.length
      }
    }
    return { enabled: this._enabled, counters: {...this._counters}, timings: avg }
  }
}

// 挂载到 window 供 CLI 脚本访问
window.__ws_diag__ = WsFrontendDiag
WsFrontendDiag._init()


// ═══ 在 _applyWsMessage 中埋点 ═══
async _applyWsMessage(msg) {
    const stopTimer = window.__ws_diag__.timeStart('apply_msg')

    // 版本号去重
    if (msg.data_version && msg.data_version <= this._dataVersion) {
      window.__ws_diag__.count('msg_dropped')
      return
    }

    window.__ws_diag__.count('msg_received')
    window.__ws_diag__._lastVersion = msg.data_version

    // ... 原有逻辑 ...

    stopTimer()
}


// ═══ 诊断查询 HTTP 端点（后端新增） ═══
# api_server.py 新增路由:
# GET /api/diag → 返回 transport.diag.snapshot()

def _get_diag(self):
    """GET /api/diag - 诊断快照（仅 --ws-debug 模式下可用）"""
    if not transport or not transport.diag.enabled:
        self._send_json(404, _resp(False, error="Diagnostics not enabled"))
        return
    self._send_json(200, _resp(True, transport.diag.snapshot()))
```

#### 9.11.5 日志示例输出

```bash
# 后端 stdout（JSON lines）
$ python api_server.py --ws-debug
{"ts": 1.234, "level": "INFO", "event": "ws_connect", "session": "abc12345"}
{"ts": 1.240, "level": "INFO", "event": "full_sync_built", "messages": 15, "elapsed_ms": 3.2}
{"ts": 5.678, "level": "INFO", "event": "broadcast", "session": "abc12345", "type": "signal_updated", "version": 42}

# 脚本消费
$ python api_server.py --ws-debug 2>&1 | grep broadcast | jq '.type'
"signal_updated"
"message_added"

# 查询实时快照
$ curl http://localhost:8080/api/diag | jq '.connections'
{"connects": 1, "disconnects": 0, "hello_timeouts": 0, "lock_stolen_sent": 0}

$ curl http://localhost:8080/api/diag | jq '.timings.full_sync_build'
{"avg_ms": 3.14, "p50_ms": 2.8, "p99_ms": 8.2, "samples": 45}
```

```js
// 前端控制台
> window.__ws_diag__.snapshot()
{
  enabled: true,
  counters: { connects: 1, msg_received: 127, signal_updated: 89, msg_dropped: 0 },
  timings: { apply_msg: { avg_ms: 0.42, samples: 100 } }
}
```

#### 9.11.6 埋点清单

| 事件 | 位置 | 指标 |
|---|---|---|
| `ws_connect` / `ws_disconnect` | `_handler` 首尾 | 连接计数 |
| `hello_timeout` | `_handler` 超时分支 | 异常计数 |
| `full_sync_built` | `_build_full_sync` | 消息数量 + 耗时 |
| `broadcast` | `broadcast()` 入口 | 类型 + session |
| `broadcast_skip` | `broadcast()` loop 不可用 | 异常计数 |
| `lock_stolen` | `broadcast_lock_stolen` | 抢占计数 |
| `msg_received` | `_applyWsMessage` 入口 | 总消息数 |
| `msg_dropped` | 版本号去重分支 | 过期消息数 |
| `version_jump` | `_dataVersion` 变化 > 1 | 跳跃值 |
| `apply_msg` | `_applyWsMessage` 整体 | 耗时 |

#### 9.11.7 文件变更

| 文件 | 变更 |
|---|---|
| `ws_server.py` | 新增 `WsDiagnostics` 类，`WsTransport` 构造函数新增 `diagnostics` 参数 |
| `api_server.py` | main() 解析 `--ws-debug` 参数，新增 `GET /api/diag` 路由 |
| `frontend/src/stores/editor.js` | `_applyWsMessage` 中埋点 `count()`/`timeStart()` |
| `frontend/src/utils/ws-client.js` | 文件顶部新增 `WsFrontendDiag` 对象 + `_init()` |

---

## 十、实施计划

### Phase 0：基础设施准备（1-2 天）

1. `requirements.txt` 添加 `websockets>=12.0`
2. 端口策略确定（WS port = HTTP port + 1）
3. `models.py`：`data_version` + 线程安全 `_bump_version()`
4. `api_server.py`：`HTTPServer` → `ThreadingHTTPServer`（鉴于 `/api/status` 健康检查仍走 HTTP，必须升级）
5. 前端添加 WS URL 构建逻辑
6. ★ 桌面版：`desktop.spec` 的 `hiddenimports` 添加 `'websockets'`（PyInstaller 不会自动发现）
7. ★ 桌面版：`desktop.py` 端口检查循环同时验证 `port` 和 `port + 1` 可用性

### Phase 1：传输+路由层（3-4 天）

1. `ws_transport.py`：实现 `WsTransport` 类
   - 连接管理（register/unregister）
   - `reply()` 单播 + `broadcast()` 跨线程安全广播
   - `start_in_thread`（Event 同步等待 loop 就绪）
2. `ws_router.py`：实现 `MessageRouter` 类
   - `register(type, handler)` + `dispatch(ws, msg)`
   - 自动区分 OK/ERROR 响应 vs 广播
3. `handlers.py`：`HandlerResult` + `HandlerError` 基类
4. `ws_server.py`：`_handler` 协程（hello → full_sync → 消息循环 → dispatch）
5. 实现 `EditSignalHandler` 作为第一个端到端示例

### Phase 2：前端 WsClient（2-3 天）

1. `ws-client.js`：扩展 `WsSyncClient`
   - `request(type, data)` → Promise
   - `_pendingRequests` Map（requestId → {resolve, reject, timer}）
   - `_handleMessage` 分叉：ok/error → resolve，其他 → onMessage 广播
   - 重连时 `_cleanupPendingRequests`
2. `editor.js`：移除 `_pendingLocalEdits`，替换为 `_requestId` + `wsClient.request()`
   - `updateSignal`、`addSignal`、`deleteSignal` 全部改写
   - `undo`、`redo`、`saveFile` 全部改写
3. `full_sync` handler：移除 HTTP 补拉逻辑
4. `undo_applied` handler：从广播中直接读取 `messages` + `message_details`

### Phase 3：全部 Handler 实现（3-4 天）

1. 信号 CRUD：`AddSignalHandler`、`DeleteSignalHandler`、`BatchAddSignalsHandler`
2. 报文 CRUD：`EditMessageHandler`、`AddMessageHandler`、`DeleteMessageHandler`
3. 撤销/重做：`UndoHandler`（带完整 `messages` + `message_details` 广播）
4. 会话/文件：`CreateSessionHandler`、`LoadSessionHandler`、`SaveHandler` 等
5. 锁管理：`ReleaseLockHandler`、`StealLockHandler`
6. 前端逐类型实现 `_applyWsMessage` 的增量处理
7. 验证焦点保存（signal_updated 只 patch 单行）

### Phase 4：移除 HTTP + 旧代码（2 天）

1. `api_server.py`：移除全部 27 个 CRUD/session/lock HTTP handler
2. 仅保留：静态文件服务（`GET /*`）+ 诊断接口（`GET /api/diag`）
3. 移除 `BROADCASTER` 全局变量 + `_broadcast_change` 辅助函数
4. `App.vue`：移除 lockCheckTimer、heartbeatTimer、_fullReloadTimer
5. 保留 `_healthTimer`（`GET /api/status`，2s 间隔，判断后端进程存活）
6. `editor.js`：移除 `_doFullReload`、`_scheduleNextReload`
6. `client.js`：移除 `api()` 函数、BroadcastChannel 代码
7. `api-queue.js`：移除（防抖改为 `PENDING_EDITS` Map）

### Phase 5：验收（2-3 天）

1. 编辑信号 → 确认无焦点丢失 + wsClient.request 正常
2. Ctrl+Z 撤销 → 确认 WS 广播数据正确同步
3. ws 断开 → 确认自动重连 + full_sync 一致性
4. lock_stolen → 确认前端清理 + 导航
5. 多标签页 → 确认 lock_stolen 通过 WS 正确推送
6. 浏览器后退/前进 → 确认 WS 生命周期正确
6. 后端进程重启 → 确认 ws 断开+重连+全量同步
7. 大量报文（500+）→ 确认全量快照性能可接受
8. 多标签页 session 抢占 → 确认 lock_stolen 正确处理
9. `--ws-debug` 开关 → 确认诊断日志正确输出 + `/api/diag` 可查询

**总工时估计：13-17 天**

---

## 十一、问题追踪

> 合并自审查文档 `websocket-architecture-issue.md`，记录所有 32 条意见的处理结果。

### Critical Issues — 已解决

| 编号 | 问题 | 修复章节 |
|---|---|---|
| C1 | WS 端口与 HTTP 端口冲突 | §3.1.1 端口策略 |
| C2 | `_build_full_sync` 无锁遍历 dict | §7.2（`with db.with_lock()`） |
| C3 | `data_version += 1` 非原子 — 版本号可能重复 | §7.1（`_bump_version()` 须在锁内调用） |
| C4 | HTTPServer vs ThreadingHTTPServer — 并发前提错误 | §〇 并发模型前提 |
| C5 | `websockets` 依赖未纳入 + API v12 签名变更 | §3.1.2 + `_handler(ws)` 单参数 |
| C6 | Session 切换 WS 生命周期遗漏 | §6.1.2（`startEditorSync`/`stopEditorSync`） |
| C7 | `full_sync` 替换数组致焦点丢失 + `selected_message` 为 None | §6.1.3（`full_sync` 后 `loadSelectedMessage()`） |
| C8 | 广播在锁外推送过期数据 | §7.3（锁内快照 + 锁外广播） |
| C9 | CRUD 与 `_push_undo` 竞态窗口 | §7.3（整个流程在 `with db.with_lock()` 内） |
| C10 | 锁抢占通知缺乏后端集成 | §7.3（`_post_steal` 插入 `broadcast_lock_stolen`） |

### Warnings — 已解决

| 编号 | 问题 | 修复章节 |
|---|---|---|
| W1 | `self.loop` 启动竞态 | §7.2（`threading.Event` 同步 + `ready.wait()`） |
| W2 | `run_coroutine_threadsafe()` 返回值忽略 | §7.2（`RuntimeError` 捕获 + loop 防御检查） |
| W3 | `lock_stolen` 处理不完整 | §6.1.3（完整清理 + `navigate-browser` 事件） |
| W4 | undo HTTP 补拉覆盖 WS 新数据 | §6.1.3（`versionAtRequest` 版本保护） |
| W5 | 乐观更新与 WS 推送竞争 | §6.1.3（乐观更新 → wsClient.request → 确认/回滚） |
| W6 | 降级切换双写风险 | 已移除：ws 断线只重连，不降级到 HTTP 轮询 |
| W7 | undo/redo 缺 `changed_message_ids` | §7.5（`session_manager.py` 改造） |
| W8 | 未缓存报文增量事件静默丢弃 | §6.1.3（`signal_count` 与 cache 解耦，始终更新 messages 列表） |
| W9 | 双重心跳超时不匹配 | §7.2（`ping_interval=None` 禁用库内置 ping） |
| W10 | 文件浏览器模式 WS 策略 | §6.4（FileBrowser 独立 WS）+ §6.3（openFile 时先断再建） |
| W11 | `_get_db` 返回裸引用 + 无锁遍历 | §7.1 + §7.3（所有遍历在 `with db.with_lock()` 内） |
| W12 | `msg.signals` 无锁遍历 | §7.3（handler 整体在锁内） |
| W13 | 心跳降级间隙误释放锁 | 已移除：ws 断线只重连，不存在 HTTP 心跳间隙 |
| W14 | 广播调用侵入性高 | §7.3（`_broadcast_change` 辅助方法 + 事件缓冲区） |

### Suggestions — 已采纳/说明

| 编号 | 建议 | 处理 |
|---|---|---|
| S1 | 版本号跳跃策略描述与代码矛盾 | 断线重连一律推 full_sync，removed `_event_buffers` |
| S2 | `_disconnectWebSocket` 魔法数字 | §6.2（`_intentionalClose` 显式标志位） |
| S3 | WsSyncClient 与 store 内嵌重复 | 选择独立 `WsSyncClient` 类（§6.2），store 通过 `_wsClient` 引用 |
| S4 | `_post_import` 替换 db 引用不稳 | §7.3（import 后广播 `full_sync`） |
| S5 | `_dataVersion` JS 溢出 | 理论风险，无实际修复需要 |
| S6 | BroadcastChannel 与 WS lock_stolen 共存 | §9.8（WS 完全替代 BroadcastChannel） |
| S7 | `signal_count` 更新逻辑冗余 | §6.1.3（`signal_updated` 不再更新列表 `signal_count`） |
| S8 | 缺少 WS 状态用户可见反馈 | 建议在 StatusBar 增加 ws 连接状态图标（未在本文档详述） |
