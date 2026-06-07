# 阶段二评审报告

> **评审日期**: 2026-06-07  
> **评审范围**: uiStore.js 提取 + 13 个组件迁移  
> **评审方式**: 3 个 sub-agent 并行评审  
> **总体结论**: ⚠️ 有条件通过（需修复 5 个 Critical 问题）

---

## 📊 评审概览

| 评审维度 | 评审 Agent | 结论 | Critical | Warning |
|---------|-----------|------|----------|---------|
| **架构设计** | architecture-design-auditor | ⚠️ 有条件通过 | 3 | 5 |
| **前端状态同步** | frontend-state-sync-auditor | ⚠️ 有条件通过 | 2 | 6 |
| **代码质量** | CodeReview | ✅ 通过 | 0 | 3 |

---

## 🔴 Critical 问题（必须修复）

### C1. `logEntries` 不应属于 UI Store

**来源**: architecture-design-auditor  
**文件**: `frontend/src/stores/uiStore.js:18`

**问题描述**:  
`logEntries` 用于存储操作日志，但日志本质上是**应用运行时状态**而非 UI 展示状态。

**根因分析**:
- UI Store 应仅管理"如何展示"（toast、contextMenu、modal 开关、theme、locale）
- 日志是"发生了什么"的业务审计数据，与撤销/重做、数据变更属于同一语义层
- 当前 `useUndoRedo.js` 通过回调 `onLog` 写入日志，建立了 editor → uiStore 的隐式依赖链

**影响**:
- 违反单一职责原则，uiStore 承担了日志仓储功能
- 未来如果需要导出日志、日志过滤、日志持久化，逻辑将分散在两个 store 之间

**修复建议**:
```javascript
// 方案 1（推荐）：移至 editor.js
// editor.js state 中添加：
logEntries: [],
addLogEntry(type, description) {
  const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  this.logEntries.unshift({ time, type, description })
  if (this.logEntries.length > 200) this.logEntries.pop()
}

// 方案 2：创建独立的 loggerStore.js（如果日志功能复杂化）
```

**优先级**: P0  
**预估工作量**: 2-3 小时（需修改 LogPanel.vue + editor.js）

---

### C2. `undoCount/redoCount` 冗余状态

**来源**: architecture-design-auditor  
**文件**: `frontend/src/stores/editor.js:35-36`

**问题描述**:  
`editor.js` 定义了 `undoCount` 和 `redoCount`，但 `useUndoRedo.js` 已通过 getter 提供了这两个值。

**根因分析**:
- `createUndoRedoManager` 返回的对象包含 `get undoCount()` 和 `get redoCount()`
- editor.js 为了 Vue 响应式，手动维护了冗余计数器
- 每次 pushUndo/undo/redo 后需手动同步（共 6 处同步点）

**当前同步点**:
```javascript
// pushUndo() - 第 80-81 行
this.undoCount = this._undoRedo.undoCount
this.redoCount = 0

// undo() - 第 88-89 行
this.undoCount = this._undoRedo.undoCount
this.redoCount = this._undoRedo.redoCount

// redo() - 第 96-97 行
this.undoCount = this._undoRedo.undoCount
this.redoCount = this._undoRedo.redoCount

// clearUndoStack() - 第 104-105 行
this.undoCount = 0
this.redoCount = 0
```

**影响**:
- 手动同步是脆弱的，一旦遗漏就会导致 UI 按钮状态错误
- 代码重复，维护成本高

**修复建议**:
```javascript
// 方案 1（推荐）：使用 computed getter 直接代理
getters: {
  undoCount: (state) => state._undoRedo?.undoCount ?? 0,
  redoCount: (state) => state._undoRedo?.redoCount ?? 0,
}
// 删除 state 中的 undoCount/redoCount，删除所有手动同步代码

// 方案 2：让 useUndoRedo 返回响应式对象（需要改造管理器）
```

**优先级**: P0  
**预估工作量**: 3-4 小时（需全面测试撤销/重做功能）

---

### C3. `initUndoRedo()` 延迟引用竞态风险

**来源**: architecture-design-auditor  
**文件**: `frontend/src/stores/editor.js:63-74`

**问题描述**:  
`initUndoRedo()` 采用懒加载模式，回调中使用 `useUiStore()` 获取实例。

**风险分析**:
```javascript
initUndoRedo() {
  if (this._undoRedo) return
  this._undoRedo = createUndoRedoManager({
    onToast: (text, isError) => useUiStore().showToast(text, isError),  // ← 延迟引用
    onLog: (type, description) => useUiStore().addLogEntry(type, description),
  })
}
```

- 如果 `pushUndo()` 在 `uiStore` 尚未初始化时被调用（极端场景：SSR 或测试环境），`useUiStore()` 可能返回未初始化的 store
- 回调中每次调用都执行 `useUiStore()`，虽然 Pinia 会缓存实例，但语义上不如在初始化时捕获引用清晰

**修复建议**:
```javascript
initUndoRedo() {
  if (this._undoRedo) return
  const ui = useUiStore()  // 在初始化时捕获引用
  this._undoRedo = createUndoRedoManager({
    onToast: (text, isError) => ui.showToast(text, isError),
    onLog: (type, description) => ui.addLogEntry(type, description),
  })
}
```

**优先级**: P0  
**预估工作量**: 30 分钟

---

### C4. `_scheduleModifiedCheck` 定时器泄漏

**来源**: frontend-state-sync-auditor  
**文件**: `frontend/src/stores/editor.js:199-203`, `frontend/src/utils/storeHelpers.js:14`

**问题描述**:  
`setTimeout` 在组件卸载或切换会话后仍会执行。

**触发条件**:  
用户在修改数据后立即切换会话（`loadHistorySession`）或关闭页面。

**潜在后果**:
- 定时器引用了旧的 store 实例上下文，在已切换的 session 上执行 `_checkModifiedStatus`
- 如果旧 session 已被删除，API 会返回 404，污染 console
- 快速操作场景下可能积累大量未清理的定时器

**修复建议**:
```javascript
// editor.js state 中增加
_modifiedTimer: null,

// actions 中修改
_scheduleModifiedCheck() {
  this.modified = true
  this.modifiedAt = Date.now()
  if (this._modifiedTimer) clearTimeout(this._modifiedTimer)
  this._modifiedTimer = setTimeout(() => {
    this._modifiedTimer = null
    this._checkModifiedStatus()
  }, 2000)
}
```

**优先级**: P0  
**预估工作量**: 1 小时

---

### C5. Toast 定时器被覆盖

**来源**: frontend-state-sync-auditor  
**文件**: `frontend/src/stores/uiStore.js:22-25`

**问题描述**:  
快速连续调用 `showToast` 时，前一个 Toast 的定时器会意外关闭后一个 Toast。

**触发条件**:  
两个操作几乎同时完成（如批量添加信号后紧跟撤销），`showToast` 被快速调用两次。

**潜在后果**:
- 第一次 Toast 还没消失就被第二次覆盖，但第一次的 `setTimeout` 仍在运行
- 2 秒后第一次的定时器触发，将 `visible` 设为 `false`，**此时显示的是第二次 Toast 的内容却被意外关闭**
- 用户看到 "信号已添加" 闪现后立即消失，误以为操作失败

**修复建议**:
```javascript
// uiStore.js state 中增加
_toastTimer: null,

// actions 中修改
showToast(text, isError = false) {
  if (this._toastTimer) clearTimeout(this._toastTimer)
  this.toast = { text, isError, visible: true }
  this._toastTimer = setTimeout(() => {
    this.toast.visible = false
    this._toastTimer = null
  }, 2000)
}
```

**优先级**: P0  
**预估工作量**: 30 分钟

---

## 🟡 Warning 问题（建议修复）

### W1. editor.js 职责过重（768 行）

**来源**: architecture-design-auditor

**问题**: editor.js 承担了 7 个职责（会话管理、数据 CRUD、信号操作、撤销/重做、剪贴板、视图状态、运行时状态）

**拆分建议**（未来迭代）:
```
editor.js (核心编排) ~200 行
├── sessionStore.js    - 会话管理 (~150 行)
├── messageStore.js    - 报文 CRUD (~200 行)  
├── signalStore.js     - 信号操作 (~200 行)
├── clipboardStore.js  - 剪贴板 (~80 行)
└── undoRedoStore.js   - 撤销重做 (~100 行)
```

**优先级**: P2  
**预估工作量**: 2-3 天

---

### W2. `layoutViewMode` 和 `selectedSignalUuid` 应归属 uiStore

**来源**: architecture-design-auditor  
**文件**: `frontend/src/stores/editor.js:27-28`

**问题**: 这两个是纯视图状态，不涉及业务数据

**修复建议**:
```javascript
// uiStore.js
signalLayoutMode: false,  // 替代 layoutViewMode
selectedLayoutSignal: null,  // 替代 selectedSignalUuid
```

**优先级**: P1  
**预估工作量**: 1-2 小时

---

### W3. 多标签页 session 冲突风险

**来源**: architecture-design-auditor

**问题**: 如果后端 `_post_new` 实现是"保存旧 session 再创建新 session"，多标签页场景下可能冲突

**建议**:
- 明确多标签页策略：独立 session vs 共享 session
- 如果支持多标签页，需要后端配合实现 session 隔离
- 或在 UI 层检测多标签页并警告用户

**优先级**: P2  
**预估工作量**: 需后端配合

---

### W4. `setLocale()` 整页刷新丢失状态

**来源**: architecture-design-auditor + frontend-state-sync-auditor  
**文件**: `frontend/src/stores/uiStore.js:53`

**问题**: `location.reload()` 导致所有未保存状态丢失

**修复建议**:
```javascript
setLocale(locale) {
  this.locale = locale
  localStorage.setItem('canmatrix_locale', locale)
  // 触发 i18n 响应式更新，而非 reload
  i18n.setLocale(locale)  // 需要 i18n.js 支持
}
```

**优先级**: P1  
**预估工作量**: 2-3 小时（需改造 i18n.js）

---

### W5. `modified` 状态检测时间窗口漏洞

**来源**: architecture-design-auditor + frontend-state-sync-auditor  
**文件**: `frontend/src/stores/editor.js:187-197`

**问题**: 1.5 秒内快速保存可能显示错误的 modified 状态

**修复建议**: 保存操作应直接设置 `modified = false`，而非依赖异步检查

**优先级**: P1  
**预估工作量**: 1-2 小时

---

### W6. TopBar.vue `fileName` 冗余 ref

**来源**: frontend-state-sync-auditor  
**文件**: `frontend/src/components/TopBar.vue:62, 92`

**问题**: 使用本地 ref 包装 store 状态，存在短暂不一致

**修复建议**: 直接使用 `store.currentFileName` 或使用 computed 双向绑定

**优先级**: P2  
**预估工作量**: 30 分钟

---

### W7. `selectedSigUuid` 双写同步漏洞

**来源**: frontend-state-sync-auditor  
**文件**: `frontend/src/components/SignalTable.vue:94, 97-100, 111-127`

**问题**: 组件本地 ref 与 store 状态双写，存在竞态条件

**修复建议**: 移除 `selectedSigUuid` ref，统一使用 `store.selectedSignalUuid` 作为单一数据源

**优先级**: P1  
**预估工作量**: 1 小时

---

### W8. `logEntries` 200 条限制可能不足

**来源**: frontend-state-sync-auditor  
**文件**: `frontend/src/stores/uiStore.js:65-67`

**问题**: 高频 undo/redo 操作会迅速填满日志

**建议**: 将限制提高到 500 或改为可配置

**优先级**: P2  
**预估工作量**: 10 分钟

---

### W9. BatchModal form 数据不重置

**来源**: frontend-state-sync-auditor  
**文件**: `frontend/src/components/BatchModal.vue:83-97`

**问题**: modal 关闭后保留了上次的参数，与用户预期不符

**修复建议**: 在 `close()` 中重置 form，或使用 `watch` 在 `visible` 变化时重置

**优先级**: P2  
**预估工作量**: 30 分钟

---

## ✨ 架构设计亮点

### 1. 乐观更新 + 回滚模式
所有 CRUD 操作采用"先更新 UI，再异步发送 API，失败时回滚"的模式。用户体验优秀，响应迅速。

### 2. 延迟引用模式避免循环依赖
`initUndoRedo()` 在 action 内部调用 `useUiStore()`，而非在模块顶层 import 后立即调用，有效避免了 Pinia store 之间的循环依赖。

### 3. 撤销/重做管理器解耦
`useUndoRedo.js` 是纯函数工厂，不依赖 Vue/Pinia，通过回调注入实现与 UI 层的解耦。设计干净，易于测试。

### 4. Client UUID 替换策略
`addSignal()` 使用前端生成的临时 UUID 乐观更新，API 成功后替换为后端真实 UUID。巧妙解决了"创建后立即展示"的 UX 需求。

### 5. 响应式计数器配合 getter
`canUndo` 和 `canRedo` 使用 computed getter 依赖 `undoCount/redoCount`，确保按钮状态自动更新。

### 6. 并发保护
`useUndoRedo.js` 的 `isExecuting` 标志防止快速连按导致的竞态条件。

### 7. sessionStorage 多标签页隔离
正确选择了 `sessionStorage`（而非 `localStorage`），每个标签页有独立的 session，避免多标签页共享同一个后端 session。

---

## 📊 总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| **职责分离** | ⚠️ 7/10 | UI/业务基本分离，但 logEntries 和 layoutViewMode 归属有误 |
| **可维护性** | ✅ 8/10 | 代码结构清晰，注释充分，但 editor.js 过长 |
| **性能** | ✅ 9/10 | 乐观更新 + messageCache 策略优秀 |
| **可扩展性** | ⚠️ 7/10 | 当前 2 个 Store 合理，但未来拆分路径不明确 |
| **测试友好度** | ✅ 8/10 | useUndoRedo 可独立测试，Store actions 纯逻辑易于 mock |
| **组件状态迁移** | 9/10 | 所有组件正确 import useUiStore，无遗留引用 |
| **跨 Store 调用** | 9/10 | 延迟引用模式正确，无循环依赖 |

### 🏁 评审结论：**有条件通过**

**必须修复后方可合并**（5 个 Critical）:
- [ ] C1: `logEntries` 移至 editor.js 或独立 loggerStore
- [ ] C2: 消除 `undoCount/redoCount` 冗余，使用 getter 代理
- [ ] C3: `initUndoRedo()` 中提前捕获 uiStore 引用
- [ ] C4: `_scheduleModifiedCheck` 定时器泄漏修复
- [ ] C5: Toast 定时器被覆盖修复

**建议后续迭代修复**（9 个 Warning）:
- [ ] W1: 评估 editor.js 拆分时机（建议阶段三）
- [ ] W2: `layoutViewMode` 移至 uiStore
- [ ] W3: 明确多标签页策略并补充防护
- [ ] W4: 消除 `setLocale()` 的整页刷新
- [ ] W5: 简化 `modified` 状态管理
- [ ] W6: TopBar.vue fileName 改为 computed
- [ ] W7: selectedSigUuid 统一为单一数据源
- [ ] W8: logEntries 限制提高到 500
- [ ] W9: BatchModal form 关闭时重置

---

## 📝 修复优先级建议

### P0（立即修复，当前阶段）
1. C5 - Toast 定时器（30 分钟，低风险）
2. C3 - initUndoRedo 引用（30 分钟，低风险）
3. C4 - 定时器泄漏（1 小时，低风险）

### P1（短期修复，本周末前）
4. C1 - logEntries 迁移（2-3 小时，中等风险）
5. C2 - undoCount/redoCount 重构（3-4 小时，需全面测试）
6. W2 - layoutViewMode 迁移（1-2 小时）
7. W4 - setLocale 改造（2-3 小时）
8. W5 - modified 状态优化（1-2 小时）
9. W7 - selectedSigUuid 统一（1 小时）

### P2（长期优化，未来迭代）
10. W1 - editor.js 拆分（2-3 天）
11. W3 - 多标签页策略（需后端配合）
12. W6 - fileName 优化（30 分钟）
13. W8 - logEntries 限制（10 分钟）
14. W9 - BatchModal 重置（30 分钟）

---

*文档版本：v1.0*  
*创建时间：2026-06-07*  
*评审 Agent：architecture-design-auditor, frontend-state-sync-auditor, CodeReview*

---

## 📝 修复记录

### 第一轮修复（P0 Critical）

**修复日期**: 2026-06-07  
**修复内容**: 3 个 P0 Critical 问题

| 编号 | 问题 | 文件 | 修复方式 | 验证结果 |
|------|------|------|---------|---------|
| C5 | Toast 定时器被覆盖 | uiStore.js | 添加 `_toastTimer` 状态，clearTimeout 后重建 | ✅ MCP 通过 |
| C3 | initUndoRedo 延迟引用竞态 | editor.js | 提前捕获 `const ui = useUiStore()` | ✅ MCP 通过 |
| C4 | _scheduleModifiedCheck 定时器泄漏 | editor.js | 添加 `_modifiedTimer` 状态，clearTimeout 后重建 | ✅ MCP 通过 |

**CodeReview 结论**: ✅ 通过（1 Warning + 2 Suggestions，均为非关键）

---

### 第二轮修复（P1 级别）

**修复日期**: 2026-06-07  
**修复内容**: 4 个 P1 问题 + 1 个 Info 修复

| 编号 | 问题 | 文件 | 修复方式 | 验证结果 |
|------|------|------|---------|---------|
| C2 | undoCount/redoCount 冗余状态 | editor.js | 最初尝试 getter 代理，发现 `_undoRedo` 是普通对象无法追踪；改为 `_syncUndoRedoCounts()` 统一封装方法 | ✅ MCP 通过 |
| C1 | logEntries 不应在 uiStore | editor.js/uiStore.js/LogPanel.vue | 迁移 logEntries/addLogEntry/clearLog 到 editor.js；LogPanel 改为同时引用 editor 和 ui | ✅ MCP 通过 |
| W2 | layoutViewMode/selectedSignalUuid 归属 | uiStore.js/editor.js/多组件 | 迁移到 uiStore，添加 toggleLayoutView/selectLayoutSignal actions；修改 5 个组件引用 | ✅ MCP 通过 |
| W7 | selectedSigUuid 双写 | SignalTable.vue | 移除本地 ref，使用 computed 代理 ui.selectedSignalUuid | ✅ MCP 通过 |
| Info | SignalLayoutVisualizer 直接赋值 | SignalLayoutVisualizer.vue | `@click="ui.layoutViewMode = false"` → `@click="ui.toggleLayoutView()"` | ✅ 已修复 |

**CodeReview 结论**: ✅ 通过（无 Critical，4 个 Info 建议，均已评估）

---

## 📊 修复后状态

### 已修复问题
- [x] C1: logEntries 迁移
- [x] C2: undoCount/redoCount 封装
- [x] C3: initUndoRedo 引用捕获
- [x] C4: _scheduleModifiedCheck 定时器泄漏
- [x] C5: Toast 定时器覆盖
- [x] W2: layoutViewMode/selectedSignalUuid 迁移
- [x] W7: selectedSigUuid 双写统一

### 遗留问题（P2 级别，建议后续迭代）
- [ ] W1: editor.js 拆分评估（2-3 天）
- [ ] W3: 多标签页 session 冲突策略（需后端配合）
- [ ] W4: setLocale() 整页刷新优化（2-3 小时）
- [ ] W5: modified 状态检测优化（1-2 小时）
- [ ] W6: TopBar.vue fileName 改为 computed（30 分钟）
- [ ] W8: logEntries 限制提高到 500（10 分钟）
- [ ] W9: BatchModal form 关闭时重置（30 分钟）

---

## 🎯 架构现状

### Store 职责划分（修复后）

```
uiStore.js（纯 UI 状态）
├── toast / _toastTimer
├── contextMenu
├── batchModalOpen / historyModalOpen / newConfirmOpen
├── theme / locale
├── showLogPanel
├── layoutViewMode / selectedSignalUuid
└── actions: showToast, toggleTheme, toggleLocale, toggleLayoutView, selectLayoutSignal, ...

editor.js（业务逻辑 + 运行时状态）
├── messages / selectedMsgId / messageCache
├── currentFileName / sessionHistory
├── isLoading / apiStatus / modified / modifiedAt / signalErrors / _modifiedTimer
├── logEntries
├── clipboard
├── _undoRedo / undoCount / redoCount
└── actions: 数据 CRUD, 会话管理, 撤销/重做, 剪贴板, 日志, ...
```

### 关键改进
1. **职责分离清晰**: UI 状态与业务数据完全分离
2. **单一数据源**: selectedSignalUuid 统一在 uiStore，无组件本地副本
3. **定时器管理**: _toastTimer 和 _modifiedTimer 都有清理逻辑
4. **撤销计数器**: _syncUndoRedoCounts() 统一封装，无分散同步
5. **日志归属**: logEntries 回归 editor.js，与业务逻辑一致

---

*文档版本：v2.0（已更新修复记录）*  
*更新时间：2026-06-07*
