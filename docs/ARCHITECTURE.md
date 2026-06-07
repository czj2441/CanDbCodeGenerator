# CAN Matrix Editor 架构特征

> 本文档记录项目的关键架构设计特征，作为后续开发和维护的参考标准。

---

## 一、整体架构

### 1.1 前后端分离

- **前端**：Vue 3 SPA + Vite + Pinia 状态管理
- **后端**：Python 轻量级 HTTP 服务器（同时服务静态文件）
- **通信**：RESTful API，JSON 格式，`X-Session-Id` 请求头实现多会话隔离
- **数据持久化**：TOML 格式（`data/` 目录）

### 1.2 会话模型

- 每个浏览器标签页对应独立 session，绑定一个 TOML 文件
- 后端 `session_manager.py` 管理会话生命周期（创建/恢复/销毁）
- 自动保存：变更延迟 500ms 写入磁盘
- 超时清理：30 分钟无操作自动回收

---

## 二、前端 Store 架构

### 2.1 双 Store 设计

| Store | 职责 | 文件 | 行数 |
|-------|------|------|------|
| **editorStore** | 业务逻辑（数据操作、会话管理、撤销/重做、剪贴板） | `stores/editor.js` | 930 |
| **uiStore** | UI 状态（Toast、模态框、主题、语言、布局视图） | `stores/uiStore.js` | 81 |

### 2.2 延迟引用模式

**避免循环依赖**：在 action 内部调用 `useUiStore()`，而非文件顶层 import。

```javascript
// ✅ 正确：延迟引用
async updateSignal(sigUuid, field, value) {
  const ui = useUiStore()
  ui.showToast('更新成功')
}

// ❌ 错误：顶层引用会导致循环依赖
import { useUiStore } from './uiStore.js'
```

### 2.3 Store 职责边界

#### editorStore（业务数据）

- **核心数据**：`messages`, `selectedMsgId`, `messageCache`
- **会话管理**：`currentFileName`, `sessionHistory`
- **运行时状态**：`isLoading`, `apiStatus`, `modified`, `signalErrors`
- **撤销/重做**：`_undoRedo`, `undoCount`, `redoCount`
- **剪贴板**：`clipboard`
- **日志**：`logEntries`（与撤销/重做紧密相关，属于业务数据）

#### uiStore（UI 状态）

- **提示**：`toast` + `_toastTimer`
- **上下文菜单**：`contextMenu`
- **模态框**：`batchModalOpen`, `historyModalOpen`, `newConfirmOpen`
- **视图状态**：`layoutViewMode`, `selectedSignalUuid`
- **主题/语言**：`theme`, `locale`
- **面板**：`showLogPanel`

### 2.4 统一封装原则

**撤销计数器同步**：所有操作栈变更后调用 `_syncUndoRedoCounts()`，禁止手动同步。

```javascript
pushUndo(snapshot) {
  this.initUndoRedo()
  this._undoRedo.pushUndo(snapshot)
  this._syncUndoRedoCounts()  // ← 统一封装
}
```

**修改状态标记**：使用 `markModified(store)` 工具函数，避免重复代码。

```javascript
// utils/storeHelpers.js
export function markModified(store) {
  store.modified = true
  store.modifiedAt = Date.now()
  store._scheduleModifiedCheck()
}
```

---

## 三、撤销/重做机制

### 3.1 架构设计

- **最大深度**：50 步
- **操作类型**：7 种（`message_delete`, `signal_delete`, `message_update`, `signal_update`, `message_add`, `signal_add`, `batch_signal_add`）
- **快照深拷贝**：`cloneSnapshot()` 使用 `JSON.parse(JSON.stringify())` 避免引用污染
- **失败回退**：序列化失败时回退到浅拷贝 `{ ...snapshot }`

### 3.2 操作处理器

**撤销处理器**（`UNDO_HANDLERS`）：根据操作类型执行 API 回滚。

**重做处理器**（`REDO_HANDLERS`）：撤销的逆操作（预留扩展）。

### 3.3 响应式计数器

- `undoCount` / `redoCount` 为 state 属性（非 getter）
- `canUndo` / `canRedo` 为 computed getter，基于计数器返回布尔值
- 所有栈变更操作后必须调用 `_syncUndoRedoCounts()`

### 3.4 会话切换清理

切换会话时清空撤销栈（`clearUndoStack()`），同时清理 modified 定时器。

---

## 四、乐观更新模式

### 4.1 工作流程

1. **入栈**：值变化时先 `pushUndo(snapshot)`
2. **更新本地**：立即更新 Pinia state
3. **发送 API**：异步调用后端接口
4. **失败回滚**：API 失败时恢复旧值 + Toast 提示

### 4.2 示例（updateSignal）

```javascript
async updateSignal(sigUuid, field, value) {
  const msg = this.selectedMessage
  const sig = msg?.signals?.find(s => s.uuid === sigUuid)
  if (!sig) return

  const prevValue = sig[field]
  
  // 1. 入栈
  this.pushUndo({
    type: 'signal_update',
    msgId: msg.id,
    sigUuid,
    prev: { [field]: prevValue },
    next: { [field]: value },
  })

  // 2. 更新本地
  sig[field] = value
  markModified(this)

  // 3. 异步 API
  try {
    await api('PUT', `/api/messages/${msg.id}/signals/${sigUuid}`, { [field]: value })
  } catch (e) {
    // 4. 回滚
    sig[field] = prevValue
    const ui = useUiStore()
    ui.showToast('更新失败：' + e.message, true)
  }
}
```

---

## 五、代码组织规范

### 5.1 editor.js 区域划分

| 区域 | 内容 | 位置 |
|------|------|------|
| **区域 C**：撤销/重做 | `initUndoRedo`, `pushUndo`, `undo`, `redo`, `clearUndoStack` | L54 |
| **区域 B**：会话管理 | `initSession`, `createDemoSession`, `loadHistorySession`, `createNewSession` | L142 |
| **区域 A**：数据操作 | `loadMessages`, `selectMessage`, `addMessage`, `updateSignal`, `deleteSignal` | L211 |
| **区域 D**：剪贴板 | `copySignal`, `cutSignal`, `pasteSignal` | L841 |

**排列顺序**：C → B → A → D（按调用频率/初始化顺序）

### 5.2 JSDoc 注释要求

- 所有 action 必须有 JSDoc（`@param`, `@returns`, 功能说明）
- 复杂逻辑（乐观更新、回滚、会话切换）必须有行内注释
- 私有方法使用 `_` 前缀（如 `_syncUndoRedoCounts`）

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

### 6.2 Modified 检查定时器

**状态**：`editorStore._modifiedTimer`

**清理时机**：切换会话时（`clearUndoStack()` 中清理）

---

## 七、信号验证规则

### 7.1 DBC 标准验证

- **越界检测**（`out_of_bounds`）：信号起始位 + 长度 > 64 bit
- **重叠检测**（`overlap`）：两个信号的 bit 范围有交集

### 7.2 字节序处理

- **Intel（小端序）**：连续递增
- **Motorola（大端序）**：锯齿规则展开

### 7.3 自动修复

- 检测重叠后推荐空闲位置
- 信号表格显示错误高亮 + 自动修复按钮

---

## 八、关键文件映射

### 8.1 前端核心文件

| 文件 | 职责 |
|------|------|
| `stores/editor.js` | 业务状态管理（数据操作、会话、撤销、日志） |
| `stores/uiStore.js` | UI 状态管理（Toast、模态框、主题、语言） |
| `utils/storeHelpers.js` | 工具函数（`markModified`） |
| `utils/useUndoRedo.js` | 撤销/重做管理器 |
| `api/client.js` | API 客户端（自动注入 SessionId，统一错误处理） |
| `components/SignalTable.vue` | 信号表格（内联编辑、错误高亮、自动修复） |
| `components/SignalLayoutVisualizer.vue` | 布局可视化（vue-konva，拖拽调整） |

### 8.2 后端核心文件

| 文件 | 职责 |
|------|------|
| `api_server.py` | REST API 路由，CRUD 端点，数据模型定义 |
| `session_manager.py` | 多会话生命周期管理，自动保存，超时清理 |
| `core/can_database.py` | 数据模型（dataclass）：Signal/Message/CanDatabase |
| `core/toml_io.py` | TOML 格式读写，自定义序列化逻辑 |
| `core/dbc_io.py` | DBC 格式导出 |
| `core/json_io.py` | JSON 格式导出 |
| `core/xml_io.py` | XML 格式导出 |

---

## 九、开发注意事项

### 9.1 新增操作类型

需要在 `useUndoRedo.js` 中同步更新：

1. `UNDO_HANDLERS` 映射表
2. `REDO_HANDLERS` 映射表（可选）
3. `TYPE_LABELS` 标签映射

### 9.2 组件状态引用

- UI 状态统一从 `uiStore` 获取（`useUiStore()`）
- 业务状态从 `editorStore` 获取（`useEditorStore()`）
- 单一数据源：避免组件内部维护与 Store 重复的状态

### 9.3 会话切换

切换会话时必须清理：

- 撤销栈（`clearUndoStack()`）
- 修改状态（`signalErrors = []`）
- Modified 定时器（已在 `clearUndoStack()` 中清理）

---

*文档版本：v1.0*  
*创建时间：2026-06-06*  
*维护原则：仅记录架构特征，不记录实施过程*
