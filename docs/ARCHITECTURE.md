# CAN Matrix Editor 架构特征

> 本文档记录项目的关键架构设计特征，作为后续开发和维护的参考标准。
>
> 最后更新：2026-07-11

---

## 一、整体架构

### 1.1 前后端分离

- **前端**：Vue 3 SPA + Vite + Pinia 状态管理
- **后端**：Python 轻量级 HTTP 服务器（同时服务静态文件）
- **通信**：WebSocket 全双工通信（CRUD 操作）+ HTTP 辅助（静态文件 / 导出 / 版本检查）
- **数据持久化**：Properties 格式（`data/` 目录）

### 1.2 会话模型

- 每个浏览器标签页对应独立 session，绑定一个 Properties 文件
- 后端 `app/services/session_manager.py` 管理会话生命周期（创建/恢复/销毁）
- 手动保存：前端显式发送 `save` WS 请求触发后端写入磁盘
- 超时清理：30 分钟无操作自动回收

### 1.3 文件锁模型

- 打开文件时自动获取排他锁，其他标签页以只读模式打开
- 锁被抢占时（`lock_stolen` 事件），受害者 WS 连接断开并跳转回文件列表
- 支持 `steal_lock` 主动抢占和 `release_lock` 主动释放

---

## 二、前端 Store 架构

### 2.1 七 Store 设计

| Store | 职责 | 文件 | 行数 |
|-------|------|------|------|
| **editor** | 核心数据（messages/cache）、WS 连接管理、消息分发、健康检查、日志 | `stores/editor.js` | 422 |
| **ui** | UI 状态（Toast、上下文菜单、模态框、主题、布局视图、日志面板） | `stores/uiStore.js` | 76 |
| **messages** | 报文 CRUD（加载、选中、添加、删除、属性编辑） | `stores/messages.js` | 112 |
| **signals** | 信号 CRUD（添加、编辑、删除、批量创建、自动修复、错误加载） | `stores/signals.js` | 180 |
| **clipboard** | 信号/报文剪贴板（复制、剪切、粘贴、复制报文） | `stores/clipboard.js` | 98 |
| **fileOperations** | 文件操作（保存、加载、另存为、新建、导入、释放锁） | `stores/fileOperations.js` | 205 |
| **undoRedo** | 撤销/重做计数器 + WS 请求（undo/redo/clearUndoStack/syncCounts） | `stores/undoRedo.js` | 67 |

### 2.2 Store 间协作模式

- **editor** 持有 WS 连接（`_wsClient`）和核心数据（`messages`, `messageCache`）
- 其他 Store 通过 `useEditorStore()._wsRequest(type, data)` 发起 WS 请求
- 后端执行操作后广播事件（如 `signal_added`, `message_updated`），由 editor 的 `_applyWsMessage()` 统一分发更新

### 2.3 Store 职责边界

#### editor（核心 + 通信）

- **核心数据**：`messages`, `selectedMsgId`, `messageCache`
- **会话与文件**：`currentFileName`
- **运行时状态**：`isLoading`, `apiStatus`, `backendDirty`, `signalErrors`, `logEntries`
- **WS 管理**：`_wsClient`, `_wsConnected`, `_connectWebSocket()`, `_wsRequest()`, `_applyWsMessage()`
- **健康检查**：`checkApiHealth()`（2s 定时器）

#### ui（UI 状态）

- **提示**：`toast` + `_toastTimer`
- **上下文菜单**：`contextMenu`
- **模态框**：`batchModalOpen`, `newConfirmOpen`
- **视图状态**：`layoutViewMode`, `selectedSignalUuid`
- **主题**：`theme`（dark/light，持久化到 localStorage）
- **日志面板**：`showLogPanel`

#### messages（报文操作）

- `loadMessages()`、`selectMessage(id)`、`loadSelectedMessage()`
- `addMessage()`、`deleteMessage(id)`、`updateMessageField(field, value)`

#### signals（信号操作）

- `addSignal(signalData)`、`updateSignal(sigUuid, field, value)`、`deleteSignal(sigUuid)`
- `batchAddSignals(params)` — 批量创建，含边界检查
- `autoFixSignal()`、`moveSignalByLayout()`、`resizeSignalByLayout()`
- `loadSignalErrors()`

#### clipboard（剪贴板）

- `copySignal(sigUuid)`、`cutSignal(sigUuid)`、`pasteSignal()`
- `copyMessage()`、`pasteMessage()`、`duplicateMessage()`

#### fileOperations（文件管理）

- `saveSession()`、`loadHistoryFile(fileName)`、`saveAs(name)`
- `createNewSession(name)`、`importFile(params)`、`newFile(name)`
- `releaseSession()`

#### undoRedo（撤销/重做）

- `undo()`、`redo()` — 调用后端 WS
- `clearUndoStack()` — 切换会话时清理前端计数器
- `syncCounts(status)` — 从后端状态同步计数

---

## 三、WebSocket 通信协议

### 3.1 连接生命周期

```
前端                                    后端
 │                                       │
 │ ── hello {session_id} ──→             │  握手（5s 超时）
 │                                       │  验证/创建 session
 │ ←── hello_ack {session_id} ──         │
 │                                       │  构建 full_sync
 │ ←── full_sync {messages, status} ──   │  初始数据同步
 │                                       │
 │ ── request {type, data, requestId} →  │  请求-响应
 │ ←── ok {data, requestId} ──           │
 │                                       │
 │ ←── broadcast {type, data} ──         │  广播事件（所有同 session 连接）
 │                                       │
 │ ── ping ──→                           │  心跳（30s 间隔）
 │ ←── pong ──                           │
```

### 3.2 请求-响应模式

- 前端每条请求携带 `requestId`，后端响应中回传同一 `requestId`
- `WsSyncClient` 内部维护 `pendingRequests` Map，超时自动 reject
- 重连策略：指数退避（1s → 2s → 4s → ... → max 30s），无限次

### 3.3 已注册的 WS Handler（27 个 type）

| 业务域 | Type | Handler |
|--------|------|---------|
| 信号 | `edit_signal` | `EditSignalHandler` |
| 信号 | `add_signal` | `AddSignalHandler` |
| 信号 | `delete_signal` | `DeleteSignalHandler` |
| 信号 | `batch_add_signals` | `BatchAddSignalsHandler` |
| 信号 | `get_signal_errors` | `GetSignalErrorsHandler` |
| 报文 | `edit_message` | `EditMessageHandler` |
| 报文 | `add_message` | `AddMessageHandler` |
| 报文 | `delete_message` | `DeleteMessageHandler` |
| 报文 | `duplicate_message` | `DuplicateMessageHandler` |
| 报文 | `get_message` | `GetMessageHandler` |
| 报文 | `get_messages` | `GetMessagesHandler` |
| 文件 | `save` | `SaveHandler` |
| 文件 | `new_file` | `NewFileHandler` |
| 文件 | `import_file` | `ImportFileHandler` |
| 文件 | `download_file` | `DownloadFileHandler` |
| 文件 | `create_file` | `CreateFileHandler` |
| 文件 | `load_file` | `LoadFileHandler` |
| 文件 | `save_as` | `SaveAsHandler` |
| 文件 | `delete_file` | `DeleteFileHandler` |
| 文件 | `get_sessions` | `GetSessionsHandler` |
| 系统 | `undo` | `UndoHandler` |
| 系统 | `redo` | `RedoHandler` |
| 系统 | `release_lock` | `ReleaseLockHandler` |
| 系统 | `steal_lock` | `StealLockHandler` |
| 系统 | `get_summary` | `GetSummaryHandler` |
| 系统 | `get_session_info` | `GetSessionInfoHandler` |
| 系统 | `get_status` | `GetStatusHandler` |

### 3.4 广播事件类型

| 事件 | 触发时机 |
|------|----------|
| `full_sync` | 连接握手 / 文件切换（全量数据同步） |
| `signal_added` | 添加信号后 |
| `signal_updated` | 编辑信号后 |
| `signal_deleted` | 删除信号后 |
| `message_added` | 添加报文后 |
| `message_updated` | 编辑报文后（含 ID 变更） |
| `message_deleted` | 删除报文后 |
| `undo_applied` | 撤销后（含完整数据快照） |
| `redo_applied` | 重做后（含完整数据快照） |
| `status_changed` | 修改状态 / 撤销计数变化 |
| `signal_errors_changed` | 信号验证错误变化 |
| `lock_stolen` | 文件锁被抢占 |
| `pong` | 心跳响应 |

### 3.5 数据版本控制

- 每条广播携带 `data_version`（递增整数）
- 前端 `_applyWsMessage()` 丢弃 `data_version` 小于当前值的消息，防止乱序更新

---

## 四、撤销/重做机制

### 4.1 后端撤销引擎

- **实现**：`app/services/undo_engine.py`
- **最大深度**：`Session.MAX_UNDO_SIZE`（默认 50 步）
- **操作类型**：`message_delete`, `signal_delete`, `message_update`, `signal_update`, `message_add`, `signal_add`, `batch_signal_add`
- **快照深拷贝**：`json.loads(json.dumps(snapshot))`，失败时回退浅拷贝
- **孤儿栈**：会话销毁后撤销栈保留在 `UndoEngine._orphan_stacks` 中，恢复会话时自动还原

### 4.2 前端计数器同步

- `undoRedo.js` 仅维护 `undoCount` / `redoCount` 计数器
- `canUndo` / `canRedo` 为 computed getter
- 计数器通过以下途径同步：
  - `full_sync` 中的 `status` 字段
  - `undo_applied` / `redo_applied` 广播中的 `status` 字段
  - `status_changed` 广播

---

## 五、代码组织规范

### 5.1 多 Store 分工

| 关注点 | 负责 Store | 说明 |
|--------|-----------|------|
| WS 连接与重连 | `editor` | `_connectWebSocket()`, `_wsRequest()` |
| 数据同步分发 | `editor` | `_applyWsMessage()` 处理所有广播 |
| 报文 CRUD | `messages` | 通过 `editor._wsRequest()` 调用 |
| 信号 CRUD | `signals` | 通过 `editor._wsRequest()` 调用 |
| 剪贴板操作 | `clipboard` | 调用 `signals` / `messages` 的方法 |
| 文件生命周期 | `fileOperations` | 会话创建/切换/保存/导入 |
| 撤销/重做 | `undoRedo` | 调用后端 WS，前端仅维护计数器 |
| UI 反馈 | `ui` | Toast、模态框、主题、上下文菜单 |
| 日志记录 | `editor` | `addLogEntry()` / `clearLog()` |

### 5.2 JSDoc 注释要求

- 所有 action 必须有 JSDoc（`@param`, `@returns`, 功能说明）
- 复杂逻辑（WS 消息分发、会话切换）必须有行内注释
- 私有方法使用 `_` 前缀（如 `_wsRequest`, `_applyWsMessage`）

---

## 六、定时器管理规范

### 6.1 Toast 定时器

**状态**：`uiStore._toastTimer`

**规则**：创建新定时器前必须先清理旧定时器。

```javascript
showToast(text, isError = false) {
  if (this._toastTimer) clearTimeout(this._toastTimer)  // ← 先清理
  this.toast = { text, isError, visible: true }
  this._toastTimer = setTimeout(() => {
    this.toast.visible = false
    this._toastTimer = null
  }, 2000)
}
```

### 6.2 健康检查定时器

**状态**：`editor._healthTimer`

**规则**：`startEditorSync()` 启动 2s 定时器调用 `checkApiHealth()`，`stopEditorSync()` 清理。

---

## 七、信号验证规则

### 7.1 DBC 标准验证

- **越界检测**（`out_of_bounds`）：信号 bit 位置 ≥ dlc × 8
- **重叠检测**（`overlap`）：两个信号的 bit 集合有交集

### 7.2 字节序处理

- **Intel（小端序）**：连续递增（bit 0, 1, 2, ...）
- **Motorola（大端序）**：锯齿规则展开（`motorolaNextBit`: `bit % 8 === 0 ? bit + 15 : bit - 1`）

### 7.3 验证执行位置

- 后端 `app/models/database.py` 的 `validate_signal()` 方法
- 前端通过 `get_signal_errors` WS 请求获取验证结果
- 信号表格显示错误高亮 + 自动修复按钮

---

## 八、关键文件映射

### 8.1 前端核心文件

| 文件 | 职责 |
|------|------|
| `stores/editor.js` | 核心数据 + WS 连接 + 消息分发 + 健康检查 + 日志 |
| `stores/uiStore.js` | UI 状态管理（Toast、模态框、主题、上下文菜单） |
| `stores/messages.js` | 报文 CRUD |
| `stores/signals.js` | 信号 CRUD + 批量创建 + 自动修复 |
| `stores/clipboard.js` | 信号/报文剪贴板 |
| `stores/fileOperations.js` | 文件操作（保存、加载、新建、导入、释放锁） |
| `stores/undoRedo.js` | 撤销/重做计数器 + WS 请求 |
| `utils/ws-client.js` | WS 客户端（连接管理 + 请求-响应 + 重连 + 心跳） |
| `utils/storeHelpers.js` | Store 工具函数（`translateError`, `findNextAvailableStartBit`, `generateMessageId` 等） |
| `utils/signalLayout.js` | 信号 bit 布局计算（`getSignalBits`, `motorolaNextBit`） |
| `utils/format.js` | 格式化工具（十六进制显示、模板展开） |
| `utils/version-check.js` | 前后端版本一致性检查 |
| `api/client.js` | Session ID 管理（`sessionStorage` 持久化） |
| `directives/lazyValue.js` | Vue 自定义指令（延迟值更新） |
| `components/FileBrowser.vue` | 文件浏览器（创建/加载/删除/导入文件） |
| `components/SignalTable.vue` | 信号表格（内联编辑、错误高亮、自动修复） |
| `components/SignalLayoutVisualizer.vue` | 信号布局可视化 |
| `components/LogPanel.vue` | 操作日志面板 |

### 8.2 后端核心文件

| 文件 | 职责 |
|------|------|
| `app/server/lifecycle.py` | HTTP + WS 服务启动入口 + 生命周期管理 + Handler 注册 |
| `app/server/http_handler.py` | 静态文件服务 + HTTP 工具端点（status/version/export/diag/release） |
| `app/server/port_utils.py` | 端口检测工具 |
| `app/ws/server.py` | WebSocket 服务端（连接生命周期 + full_sync 构建） |
| `app/ws/transport.py` | WS I/O 封装（连接管理 + 广播 + 诊断） |
| `app/ws/router.py` | 消息路由（type → handler 分发 + HandlerResult/HandlerError） |
| `app/ws/handlers/signal_handlers.py` | 信号 Handler（5 个） |
| `app/ws/handlers/message_handlers.py` | 报文 Handler（6 个） |
| `app/ws/handlers/file_handlers.py` | 文件 Handler（9 个） |
| `app/ws/handlers/system_handlers.py` | 系统 Handler（7 个） |
| `app/models/database.py` | CanDatabase 运行时模型（RLock + 信号验证 + 序列化） |
| `app/models/signal.py` | Signal 数据类 |
| `app/models/message.py` | Message 数据类 |
| `app/services/session_manager.py` | 多会话生命周期管理 |
| `app/services/session.py` | Session 数据类 |
| `app/services/undo_engine.py` | 撤销/重做引擎（含孤儿栈） |
| `app/services/file_lock.py` | 文件锁（多标签页互斥） |
| `app/services/file_persistence.py` | 磁盘持久化（原子写入） |
| `app/io/properties_io.py` | Properties 格式读写 |
| `app/io/dbc_io.py` | DBC 格式导入导出 |
| `app/io/json_io.py` | JSON 格式读写 |
| `app/io/xml_io.py` | XML 格式读写 |
| `app/io/c_code_gen.py` | C 代码生成（Jinja2 模板） |

---

## 九、开发注意事项

### 9.1 新增 WS 消息类型

需要在以下位置同步更新：

1. **后端**：`app/ws/handlers/` 中新建 Handler 类
2. **后端**：`app/ws/handlers/__init__.py` 中导出
3. **后端**：`app/server/lifecycle.py` 中 `ws_router.register()` 注册
4. **前端**：`editor.js` 的 `_applyWsMessage()` 中添加广播事件处理分支

### 9.2 组件状态引用

- UI 状态统一从 `uiStore` 获取（`useUiStore()`）
- 核心数据从 `editorStore` 获取（`useEditorStore()`）
- 报文操作从 `messagesStore` 获取（`useMessagesStore()`）
- 信号操作从 `signalsStore` 获取（`useSignalsStore()`）
- 剪贴板操作从 `clipboardStore` 获取（`useClipboardStore()`）
- 文件操作从 `fileOperationsStore` 获取（`useFileOperationsStore()`）
- 撤销/重做从 `undoRedoStore` 获取（`useUndoRedoStore()`）
- 单一数据源：避免组件内部维护与 Store 重复的状态

### 9.3 会话切换

切换会话时需要清理：

- `editor.resetEditorState()` — 清空 messages/cache/selectedMsgId/signalErrors/logEntries
- `undoRedo.clearUndoStack()` — 重置前端撤销计数器
- WS 连接重建（`stopEditorSync()` + `startEditorSync()`）

---

*文档版本：v2.0*
*创建时间：2026-06-06*
*最后更新：2026-07-11*
*维护原则：仅记录架构特征，不记录实施过程*
