# CAN Matrix Editor 前端架构重构方案

> **目标**：优化 `editor.js` 的可维护性，提取重复逻辑，标准化乐观更新模式，优化撤销/重做机制。
>
> **方案**：渐进式重构（低风险，1-2 周完成）

---

## 目录

- [1. 架构设计](#1-架构设计)
- [2. 乐观更新模式优化](#2-乐观更新模式优化)
- [3. 撤销/重做机制优化](#3-撤销重做机制优化)
- [4. 组件与 Store 交互规范](#4-组件与-store-交互规范)
- [5. 重构实施步骤](#5-重构实施步骤)
- [6. 数据流图与架构示意](#6-数据流图与架构示意)

---

## 1. 架构设计

### 1.1 核心策略

在 `editor.js` 内部用**代码组织**代替**模块拆分**，仅提取 `uiStore.js`：

```javascript
// stores/editor.js（重构后结构）
import { defineStore } from 'pinia'
import { api } from '../api/client.js'
import { createUndoRedoManager } from '../utils/useUndoRedo.js'
import { useUiStore } from './uiStore.js'
import { markModified, withErrorHandling } from '../utils/storeHelpers.js'

export const useEditorStore = defineStore('editor', {
  state: () => ({
    // ═══════════════════════════════════════════
    // 数据状态
    // ═══════════════════════════════════════════
    messages: [],
    messageCache: {},
    selectedMsgId: null,
    selectedSignalUuid: null,
    signalErrors: [],
    layoutViewMode: false,

    // ═══════════════════════════════════════════
    // 会话状态
    // ═══════════════════════════════════════════
    currentFileName: '',
    apiStatus: 'connecting',
    modified: false,
    modifiedAt: 0,
    sessionHistory: [],
    clipboard: null,

    // ═══════════════════════════════════════════
    // 撤销状态
    // ═══════════════════════════════════════════
    _undoRedo: null,  // createUndoRedoManager() 返回的对象实例
    // ⚠️ 必须使用响应式计数器，因为 _undoRedo.undoCount 不是响应式的
    // Pinia getter 不会追踪普通对象内部的变化
    undoCount: 0,
    redoCount: 0,
  }),

  getters: {
    // ── 数据相关 ──
    selectedMessage(state) { ... },
    messageCount(state) { ... },

    // ── 撤销相关 ──
    // ✅ 使用响应式计数器，确保按钮状态正确更新
    canUndo: (state) => state.undoCount > 0,
    canRedo: (state) => state.redoCount > 0,
  },

  actions: {
    // ═══════════════════════════════════════════
    // 区域 A：数据操作
    // ═══════════════════════════════════════════
    async loadMessages() { ... },
    async selectMessage(id) { ... },
    async addSignal(signalData) { ... },
    async updateSignal(sigUuid, field, value) { ... },

    // ═══════════════════════════════════════════
    // 区域 B：会话管理
    // ═══════════════════════════════════════════
    async initSession() { ... },
    async createDemoSession() { ... },
    async loadHistorySession(sessionId) { ... },

    // ═══════════════════════════════════════════
    // 区域 C：撤销/重做
    // ═══════════════════════════════════════════
    initUndoRedo() { ... },
    async undo() {
      await this._undoRedo?.undo()  // 内部会触发 onReload 回调
      // ✅ 立即更新响应式计数器（确保按钮状态正确）
      this.undoCount = this._undoRedo?.undoCount || 0
      this.redoCount = this._undoRedo?.redoCount || 0
    },
    async redo() {
      await this._undoRedo?.redo()  // 内部会触发 onReload 回调
      // ✅ 立即更新响应式计数器
      this.undoCount = this._undoRedo?.undoCount || 0
      this.redoCount = this._undoRedo?.redoCount || 0
    },
    pushUndo(snapshot) {
      this._undoRedo?.pushUndo(snapshot)
      // ✅ 更新响应式计数器（pushUndo 会清空 redoStack）
      this.undoCount = this._undoRedo?.undoCount || 0
      this.redoCount = 0
    },

    // ═══════════════════════════════════════════
    // 区域 D：剪贴板
    // ═══════════════════════════════════════════
    copySignal(sigUuid) { ... },
    async pasteSignal() { ... },
  }
})
```

**收益**：
- ✅ 保持单一 Store，避免循环依赖
- ✅ 内部职责通过代码组织清晰化（4 个区域注释）
- ✅ 组件引用无需修改（仍使用 `useEditorStore`）
- ✅ `uiStore.js` 独立后，减少 ~150 行
- ✅ 撤销/重做逻辑已提取到 `useUndoRedo.js`，无需进一步拆分

### 1.2 文件结构

```
stores/
  ├── editor.js          # 核心 Store（~650行，内部按区域组织）
  ├── uiStore.js         # UI 状态（~120行）
  └── ...

utils/
  ├── storeHelpers.js    # 可复用工具函数（~80行）
  └── useUndoRedo.js     # 撤销/重做管理器（277行）
```

### 1.3 uiStore.js - UI 状态管理

**⚠️ 重要修复**：
1. 不要在 getters 中引用其他 Store，这会导致 Pinia getter 返回函数而非值
2. **必须使用响应式计数器**（undoCount/redoCount），因为 `_undoRedo.undoCount` 是普通 JS getter
3. Pinia getter **不会追踪**非响应式对象内部的变化
4. 每次 pushUndo/undo/redo 后必须手动更新响应式计数器
5. **关键时序**：必须在 `_undoRedo.undo()/redo()` **之后**立即更新计数器，因为 onReload 回调可能触发其他 state 变化

```javascript
// stores/uiStore.js
import { defineStore } from 'pinia'

export const useUiStore = defineStore('ui', {
  state: () => ({
    // Toast 提示
    toast: { text: '', isError: false, visible: false },
    // 上下文菜单
    contextMenu: { visible: false, x: 0, y: 0, target: null, idx: null },
    // Modal 状态
    batchModalOpen: false,
    historyModalOpen: false,
    newConfirmOpen: false,
    // 主题与语言
    theme: localStorage.getItem('canmatrix_theme') || 'dark',
    locale: localStorage.getItem('canmatrix_locale') || 'zh',
    // 日志面板
    showLogPanel: false,
    logEntries: [],
  }),

  // ❌ 错误：getters 中引用其他 Store 会导致 getter 返回函数
  // getters: {
  //   canUndo: () => {  // 这会返回一个函数，不是布尔值！
  //     const undoStore = useUndoStore()
  //     return undoStore.undoCount > 0
  //   },
  // },

  // ✅ 正确：不在 uiStore 中定义 canUndo，让组件直接读取 undoStore
  // 组件中使用方式：
  // const undoStore = useUndoStore()
  // const canUndo = computed(() => undoStore.undoCount > 0)

  actions: {
    showToast(text, isError = false) {
      this.toast = { text, isError, visible: true }
      setTimeout(() => { this.toast.visible = false }, 2000)
    },

    hideToast() {
      this.toast.visible = false
    },

    showContextMenu(x, y, target, idx) {
      this.contextMenu = { visible: true, x, y, target, idx }
    },

    hideContextMenu() {
      this.contextMenu.visible = false
    },

    setTheme(theme) {
      this.theme = theme
      localStorage.setItem('canmatrix_theme', theme)
      document.documentElement.setAttribute('data-theme', theme)
    },

    toggleTheme() {
      const next = this.theme === 'dark' ? 'light' : 'dark'
      this.setTheme(next)
    },

    setLocale(locale) {
      this.locale = locale
      localStorage.setItem('canmatrix_locale', locale)
      location.reload()
    },

    toggleLocale() {
      const next = this.locale === 'zh' ? 'en' : 'zh'
      this.setLocale(next)
    },

    // ── 操作日志 ──

    addLogEntry(type, description) {
      const now = new Date()
      const time = now.toLocaleTimeString('zh-CN', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      })
      this.logEntries.unshift({ time, type, description })
      if (this.logEntries.length > 200) {
        this.logEntries.pop()
      }
    },

    clearLog() {
      this.logEntries = []
    },
  },
})
```

**职责边界**：
- ✅ 管理所有 UI 组件的显示/隐藏状态
- ✅ 管理 Toast 提示
- ✅ 管理主题、语言偏好
- ✅ 管理操作日志显示
- ❌ 不包含业务数据
- ❌ 不包含 API 调用逻辑
- ❌ **不包含跨 Store 的 getter（如 canUndo/canRedo）**

---

## 2. 乐观更新模式优化

### 2.1 问题分析

当前代码中，每个 CRUD 操作都实现了类似的乐观更新模式，代码重复6+次。

### 2.2 提取可复用工具函数

不采用统一的 `executeOptimisticUpdate` 模板，而是提取**可复用的工具函数**，每个 action 保留自己的乐观更新逻辑：

```javascript
// utils/storeHelpers.js

/**
 * 统一标记修改状态
 */
export function markModified(store) {
  store.modified = true
  store.modifiedAt = Date.now()
  setTimeout(() => store._checkModifiedStatus(), 2000)
}

/**
 * 统一错误处理模式
 */
export async function withErrorHandling(actionFn, store, successMsg) {
  try {
    const result = await actionFn()
    store.showToast(successMsg, false)
    return result
  } catch (error) {
    store.showToast(error.message, true)
    throw error
  }
}

/**
 * 统一撤销入栈模式
 */
export function pushUndoWithCheck(store, snapshot, shouldPush = true) {
  if (shouldPush && store._undoRedo) {
    store._undoRedo.pushUndo(snapshot)
  }
}
```

**使用示例**：

```javascript
// editor.js 中的 updateSignal action
async updateSignal(sigUuid, field, value) {
  const msg = this.selectedMessage
  if (!msg) return

  const sig = msg.signals.find(s => s.uuid === sigUuid)
  if (!sig) return

  // 1. 保存旧值
  const oldValue = sig[field]

  // 2. 推入撤销栈（在修改前）
  this._undoRedo?.pushUndo({
    type: 'signal_update',
    msgId: this.selectedMsgId,
    sigUuid,
    field,
    oldValue,
    newValue: value,
  })

  // 3. 乐观更新
  sig[field] = value

  // 4. 标记修改
  markModified(this)

  // 5. API 调用
  try {
    await api('PUT', `/api/messages/${this.selectedMsgId}/signals/${sigUuid}`, {
      [field]: value,
    })
    this.showToast('更新成功')
  } catch (error) {
    // 6. 回滚
    sig[field] = oldValue
    this.showToast('更新失败', true)
    throw error
  }
}
```

**优势**：
- ✅ 每个操作保留自己的逻辑（适应不同场景）
- ✅ 消除重复的工具代码（markModified、错误处理）
- ✅ 不引入复杂的统一模板
- ✅ 更易理解和维护

**⚠️ 注意**：
- `withErrorHandling` 是可选工具函数，在简单场景中可能不需要
- 乐观更新通常需要自定义回滚逻辑，建议在 action 中直接处理

---

## 3. 撤销/重做机制优化

### 3.1 当前问题

1. **耦合度高**：`useUndoRedo.js` 直接依赖 `api` 和回调函数
2. **快照序列化**：未处理循环引用、不可序列化对象
3. **并发锁**：仅保护 undo/redo 执行，未保护与正常操作的并发

### 3.2 保留静态对象模式

当前项目规模小（7 种操作类型），静态对象已足够：

```javascript
// utils/useUndoRedo.js（优化版，保留静态对象）

const UNDO_HANDLERS = {
  message_delete: {
    undo: async (snap) => await api('POST', '/api/messages', snap.data),
    redo: async (snap) => await api('DELETE', `/api/messages/${snap.data.id}`),
  },
  signal_delete: {
    undo: async (snap) => await api('POST', `/api/messages/${snap.msgId}/signals`, snap.data),
    redo: async (snap) => await api('DELETE', `/api/messages/${snap.msgId}/signals/${snap.data.uuid}`),
  },
  // ... 其他 5 种操作类型
}

/**
 * 深度克隆快照（避免引用问题）
 */
function cloneSnapshot(snapshot) {
  try {
    return JSON.parse(JSON.stringify(snapshot))
  } catch (e) {
    console.warn('[UndoRedo] 快照序列化失败，使用浅拷贝', e)
    return { ...snapshot }
  }
}

export function createUndoRedoManager({ maxSize = 50, onReload, onToast, onLog } = {}) {
  const undoStack = []
  const redoStack = []
  let isExecuting = false
  let executionQueue = []

  function pushUndo(snapshot) {
    undoStack.push(cloneSnapshot(snapshot))
    if (undoStack.length > maxSize) {
      undoStack.shift()
    }
    redoStack.length = 0
  }

  async function executeWithLock(fn) {
    return new Promise((resolve, reject) => {
      executionQueue.push({ fn, resolve, reject })
      if (executionQueue.length === 1) {
        processQueue()
      }
    })
  }

  async function processQueue() {
    if (executionQueue.length === 0) {
      isExecuting = false
      return
    }

    isExecuting = true
    const { fn, resolve, reject } = executionQueue.shift()

    try {
      const result = await fn()
      resolve(result)
    } catch (error) {
      reject(error)
    } finally {
      processQueue()
    }
  }

  async function undo() {
    return executeWithLock(async () => {
      if (undoStack.length === 0) {
        onToast?.('无操作可撤销', false)
        return
      }

      const snap = undoStack.pop()
      const handler = UNDO_HANDLERS[snap.type]

      if (!handler) {
        console.warn(`[UndoRedo] 未定义的操作类型: ${snap.type}`)
        return
      }

      await handler.undo(snap)
      redoStack.push(snap)
      await onReload?.()
      onToast?.('撤销成功', false)
      // 日志描述函数需要根据实际情况实现
      const logDesc = `撤销: ${snap.type}`
      onLog?.('undo', logDesc)
    })
  }

  async function redo() {
    return executeWithLock(async () => {
      if (redoStack.length === 0) {
        onToast?.('无操作可重做', false)
        return
      }

      const snap = redoStack.pop()
      const handler = UNDO_HANDLERS[snap.type]

      if (!handler) {
        console.warn(`[UndoRedo] 未定义的重做操作类型: ${snap.type}`)
        return
      }

      await handler.redo(snap)
      undoStack.push(snap)
      await onReload?.()
      onToast?.('重做成功', false)
      // 日志描述函数需要根据实际情况实现
      const logDesc = `重做: ${snap.type}`
      onLog?.('redo', logDesc)
    })
  }

  function clear() {
    undoStack.length = 0
    redoStack.length = 0
    executionQueue.length = 0
  }

  return {
    get undoCount() { return undoStack.length },
    get redoCount() { return redoStack.length },
    pushUndo,
    undo,
    redo,
    clear,
  }
}
```

**优势**：
- ✅ 加载时即完整（编译/加载时发现遗漏）
- ✅ IDE 支持好（自动补全、检查）
- ✅ 代码直观（一目了然）
- ✅ 适合当前项目规模

---

## 4. 组件与 Store 交互规范

### 4.1 核心原则

1. **组件不直接操作状态**：所有状态修改必须通过 Store actions
2. **组件不直接调用 API**：API 调用封装在 Store 中
3. **单向数据流**：Store → Computed → 组件渲染 → 用户交互 → Store action

### 4.2 组件调用示例

#### SignalTable.vue

```vue
<script setup>
import { computed } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useUiStore } from '../stores/uiStore.js'

const editor = useEditorStore()
const ui = useUiStore()

const msg = computed(() => editor.selectedMessage)

function handleAddSignal() {
  editor.addSignal({ name: 'NewSignal', start_bit: 0, length: 8 })
}

function handleUpdateSignal(uuid, field, value) {
  editor.updateSignal(uuid, field, value)
}

function handleDeleteSignal(uuid) {
  editor.deleteSignal(uuid)
}

function handleDeleteMessage() {
  if (editor.selectedMsgId != null) {
    editor.deleteMessage(editor.selectedMsgId)
  }
}
</script>
```

### 4.3 规范总结

| 操作 | 正确方式 | 错误方式 |
|------|---------|---------|
| 修改状态 | `editor.selectMessage(id)` | `editor.selectedMsgId = id` (在组件中) |
| 调用 API | `editor.createMessage(data)` | `api('POST', '/api/messages', data)` (在组件中) |
| 显示 Toast | `ui.showToast('消息')` | 直接在组件中管理 Toast 状态 |
| 撤销操作 | `editor.undo()` | 直接在组件中管理撤销栈 |

---

## 5. 重构实施步骤

### 总体策略：渐进式重构，保持功能可用

**核心原则**：
- ✅ 每个阶段完成后，系统必须保持完整功能
- ✅ 每迁移一个方法即测试，避免累积错误
- ✅ 保留 `editor.js` 直到所有功能迁移完成

### 阶段一：提取工具函数（1-2 天）

**目标**：消除重复代码，不改变 Store 结构

**任务清单**：
- [ ] 创建 `utils/storeHelpers.js`（markModified、withErrorHandling、pushUndoWithCheck）
- [ ] 重构 `useUndoRedo.js`（添加 cloneSnapshot 函数）
- [ ] 在 3-5 个 action 中试用工具函数
- [ ] 编写单元测试

**验证方式**：
- 运行现有测试，确保无破坏
- 手动测试核心功能（添加/删除报文、信号）
- 验证无行为变化

**⚠️ 关键检查点**：
- [ ] 工具函数单元测试通过
- [ ] 重构后的 action 行为与原逻辑一致
- [ ] 无遗漏的 markModified 调用

---

### 阶段二：提取 UI 状态（3-4 天）

**⚠️ 注意**：当前代码中有 **13 个组件**直接使用 `store.xxx` 引用 UI 状态

**目标**：将 `uiStore.js` 独立出来（无循环依赖风险）

**任务清单**：
- [ ] 创建 `stores/uiStore.js`
- [ ] 将 `toast`、`contextMenu`、`batchModalOpen` 等状态迁移到 `uiStore.js`
- [ ] 将 `theme`、`locale` 管理迁移到 `uiStore.js`
- [ ] 将 `showLogPanel`、`logEntries` 迁移到 `uiStore.js`
- [ ] 更新 **13 个组件**中 UI 相关引用
- [ ] 删除 `editor.js` 中的对应代码

**组件迁移清单**：

**⚠️ 重要**：以下组件需要修改 UI 状态引用（从 `store.xxx` 改为 `uiStore.xxx`）：

| 组件 | 需要修改的内容 |
|------|---------------|
| `App.vue` | `store.toast` → `uiStore.toast`<br>`store.contextMenu` → `uiStore.contextMenu`<br>`store.theme` → `uiStore.theme` |
| `TopBar.vue` | `store.toggleLocale` → `uiStore.toggleLocale`<br>`store.toggleTheme` → `uiStore.toggleTheme`<br>`store.locale` → `uiStore.locale`<br>`store.theme` → `uiStore.theme`<br>`store.showLogPanel` → `uiStore.showLogPanel` |
| `MessageList.vue` | `store.contextMenu` → `uiStore.contextMenu` |
| `SignalTable.vue` | `store.batchModalOpen` → `uiStore.batchModalOpen` |
| `MessagePanel.vue` | `store.batchModalOpen` → `uiStore.batchModalOpen` |
| `SignalLayoutVisualizer.vue` | `store.batchModalOpen` → `uiStore.batchModalOpen` |
| `BatchModal.vue` | `v-model:visible="store.batchModalOpen"` → `uiStore.batchModalOpen` |
| `HistoryModal.vue` | `store.historyModalOpen` → `uiStore.historyModalOpen` |
| `ContextMenu.vue` | `store.contextMenu` → `uiStore.contextMenu` |
| `Toast.vue` | `store.toast` → `uiStore.toast` |
| `StatusBar.vue` | 可能不需要修改（需验证） |
| `LoadingOverlay.vue` | 可能不需要修改（需验证） |
| `LogPanel.vue` | `store.showLogPanel` → `uiStore.showLogPanel`<br>`store.logEntries` → `uiStore.logEntries` |

**验证方式**：
- 测试 Toast 提示、主题切换、语言切换
- 测试 Modal 打开/关闭
- 测试右键菜单
- 验证 `editor.js` 中已迁移的代码不再被调用

**⚠️ 关键检查点**：
- [ ] 所有组件的 UI 状态引用已更新
- [ ] `uiStore` 可独立加载（无循环依赖）
- [ ] `editor.js` 行数减少 ~150 行

---

### 阶段三：内部代码组织（3-4 天）

**目标**：在 `editor.js` 内部按区域组织代码

**任务清单**：
- [ ] 添加区域注释（数据操作、会话管理、撤销/重做、剪贴板）
- [ ] 按区域重新排列 actions（不改变逻辑）
- [ ] 添加 JSDoc 注释到关键函数
- [ ] 清理未使用的代码和注释
- [ ] 代码审查

**验证方式**：
- 运行全量测试
- 手动测试所有功能
- 验证代码结构清晰（新开发者能快速定位代码）

**⚠️ 关键检查点**：
- [ ] 代码按 4 个区域组织
- [ ] 无功能变化（纯重构）
- [ ] 代码审查通过

---

## 6. 数据流图与架构示意

### 6.1 重构前架构

```
┌─────────────────────────────────────────┐
│           editor.js (779 行)            │
│  ┌───────────────────────────────────┐  │
│  │  messages, messageCache           │  │
│  │  selectedMsgId, toast, modals     │  │
│  │  theme, locale, clipboard         │  │
│  │  _undoRedo                        │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │  乐观更新逻辑（重复 6+ 次）       │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
          ↓              ↓              ↓
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │SignalTable│  │MessagePan│  │  TopBar  │
    └──────────┘  └──────────┘  └──────────┘
```

---

### 6.2 重构后架构

```
┌───────────────────────────────────────────────────────┐
│                    组件层 (Vue Components)              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ SignalTable  │  │MessagePanel  │  │   TopBar     │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└───────────────────────────────────────────────────────┘
              ↓                        ↓
┌──────────────────────┐    ┌──────────────────────┐
│   editor.js          │    │    uiStore.js        │
│  - messages          │    │  - toast             │
│  - messageCache      │    │  - modals            │
│  - selectedMsgId     │    │  - theme/locale      │
│  - clipboard         │    │  - logEntries        │
│  - _undoRedo         │    └──────────────────────┘
└──────────────────────┘
          ↓
┌───────────────────────────────────────────────────────┐
│                      工具层 (Utils)                     │
│  ┌──────────────────────────┐  ┌────────────────────┐ │
│  │ storeHelpers.js          │  │  useUndoRedo.js    │ │
│  │ - markModified           │  │ - cloneSnapshot    │ │
│  │ - withErrorHandling      │  │ - executeWithLock  │ │
│  │ - pushUndoWithCheck      │  │ - static handlers  │ │
│  └──────────────────────────┘  └────────────────────┘ │
│  ┌──────────────────────────┐                          │
│  │ api/client.js            │                          │
│  └──────────────────────────┘                          │
└───────────────────────────────────────────────────────┘
```

---

### 6.3 数据流向图（以"添加信号"为例）

```
用户点击"添加信号"按钮
        ↓
SignalTable.vue 调用 editor.addSignal()
        ↓
editor.js addSignal action:
  1. 保存旧值 (oldSignals, oldMsgEntry)
  2. pushUndo({ type: 'signal_add', ... })
  3. 乐观更新: msg.signals.push(newSig)
  4. markModified(this)
  5. API 调用: api('POST', '/api/messages/.../signals')
        ↓
┌─────────────────────────────────┐
│ 成功                             │
│  → showToast('添加成功')         │
│  → loadSignalErrors()           │
└─────────────────────────────────┘
        或
┌─────────────────────────────────┐
│ 失败                             │
│  → 回滚: msg.signals = oldSignals│
│  → showToast('添加失败', true)   │
└─────────────────────────────────┘
```

---

## 附录 A：重构检查清单

### 代码质量检查
- [ ] `editor.js` 按 4 个区域组织，代码清晰
- [ ] `uiStore.js` 独立，无循环依赖
- [ ] 无重复的乐观更新逻辑（使用工具函数）
- [ ] 所有 API 调用封装在 Store 中
- [ ] 组件中无直接状态修改
- [ ] 错误处理统一（Toast 提示 + 日志记录）

### 测试覆盖检查
- [ ] `storeHelpers.js` 单元测试
- [ ] `useUndoRedo.js` 单元测试
- [ ] `editor.js` actions 测试
- [ ] E2E 测试（核心用户流程）

---

## 附录 B：常见问题与解决方案

### Q1：如何避免 canUndo getter 返回函数？

**A**：不要在 uiStore 的 getters 中引用其他 Store，组件中使用 computed：

```javascript
// ❌ 错误：在 uiStore getters 中引用其他 Store
getters: {
  canUndo: () => {
    const undoStore = useUndoStore()
    return undoStore.undoCount > 0  // 返回函数，不是布尔值！
  },
}

// ✅ 正确：组件中使用 computed
const undoStore = useUndoStore()
const canUndo = computed(() => undoStore.undoCount > 0)
```

### Q2：乐观更新时如何处理并发操作？

**A**：在 `useUndoRedo.js` 中使用执行队列：

```javascript
let isExecuting = false
let executionQueue = []

async function executeWithLock(fn) {
  return new Promise((resolve, reject) => {
    executionQueue.push({ fn, resolve, reject })
    if (executionQueue.length === 1) {
      processQueue()
    }
  })
}
```

### Q3：如何测试乐观更新和回滚逻辑？

**A**：使用 Mock API 模拟失败场景：

```javascript
import { vi } from 'vitest'
import { api } from '../api/client.js'

test('添加信号失败时回滚', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('API Error'))

  const editor = useEditorStore()
  const initialCount = editor.selectedMessage.signals.length
  await editor.addSignal({ name: 'Test' })

  expect(editor.selectedMessage.signals.length).toBe(initialCount)
})
```

---

## 总结

本重构方案通过以下核心改进提升代码质量：

1. **工具函数提取**：消除重复代码（markModified、错误处理、撤销入栈）
2. **UI 状态独立**：将 `uiStore.js` 拆出，减少 ~150 行
3. **内部代码组织**：`editor.js` 按 4 个区域组织，职责清晰
4. **撤销/重做优化**：添加快照序列化保护，保留静态对象模式
5. **循环依赖防范**：仅拆分无依赖的 `uiStore`，避免复杂引用

**预期收益**：
- 📉 代码行数减少 15-20%（提取工具函数 + uiStore）
- 🔧 可维护性提升（内部组织清晰，易于定位问题）
- 🧪 可测试性提升（uiStore 可独立测试，工具函数易于测试）
- 🚀 可扩展性保留（未来可基于此进一步拆分）
- ⚡ 实施风险低（3 个阶段，每阶段可独立回滚）

**下一步行动**：
1. 评审本方案，确认可行性
2. 创建开发分支开始实施
3. 从阶段一（工具函数提取）开始，每完成一个阶段进行代码审查
4. 建立自动化测试覆盖，确保重构不破坏现有功能

---

**文档版本**：v2.1（简化版）  
**创建时间**：2026-06-06  
**方案**：渐进式重构（低风险）  
**审阅结论**：✅ 方案可行，可开始实施
