# CAN Matrix Editor 前端重构实施计划

> **方案来源**：ARCHITECTURE_REFACTOR_PLAN.md v2.1（渐进式重构）
> **总体策略**：低风险、分阶段、可回滚
> **预计总工期**：6-10 天

---

## 阶段一：工具函数提取与撤销计数器（预计 1-2 天）

**目标**：消除重复代码，修复撤销计数器响应式问题，不改变 Store 结构。

---

### 任务 1.1：创建 `storeHelpers.js`

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P0 |
| **涉及文件** | 新建 `frontend/src/utils/storeHelpers.js` |
| **依赖任务** | 无 |

**操作步骤**：
1. 新建 `utils/storeHelpers.js`
2. 提取 `markModified(store)` 函数（从 `editor.js` 第 205-208 行）
3. 提取 `withErrorHandling(actionFn, uiStore, successMsg)` 函数（可选）

**验收标准**：
- [ ] `storeHelpers.js` 可独立 import
- [ ] `markModified` 函数行为与原代码一致
- [ ] `npm run build` 通过

**风险点**：
- `withErrorHandling` 函数需要 `uiStore` 参数，但阶段一尚未提取 `uiStore`
- **缓解**：阶段一只提取 `markModified`，`withErrorHandling` 留到阶段二

---

### 任务 1.2：在 `editor.js` 中添加响应式撤销计数器

| 属性 | 内容 |
|------|------|
| **预估时间** | 1-2 小时 |
| **优先级** | P0 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 无 |

**操作步骤**：
1. 在 `state` 中添加 `undoCount: 0` 和 `redoCount: 0`
2. 修改 `getters`：
   ```javascript
   canUndo: (state) => state.undoCount > 0,
   canRedo: (state) => state.redoCount > 0,
   ```
3. 修改 `pushUndo` 方法：在入栈后同步计数器
4. 修改 `undo` 方法：在操作完成后同步计数器
5. 修改 `redo` 方法：在操作完成后同步计数器
6. 修改 `clearUndoStack` 方法：清空计数器

**验收标准**：
- [ ] `canUndo` / `canRedo` getter 返回布尔值（不是函数）
- [ ] 执行操作后 `undoCount` 正确增加
- [ ] 撤销后 `undoCount` 减少、`redoCount` 增加
- [ ] 重做后 `undoCount` 增加、`redoCount` 减少
- [ ] 新操作清空 redo 栈时 `redoCount` 归零
- [ ] `TopBar.vue` 按钮状态正确响应

**验证方式**：
```javascript
// MCP 测试脚本
const store = useEditorStore()
await store.updateSignal(sig.uuid, 'name', 'Test')
console.log(store.undoCount)  // 应为 1
console.log(store.canUndo)    // 应为 true
await store.undo()
console.log(store.undoCount)  // 应为 0
console.log(store.redoCount)  // 应为 1
console.log(store.canRedo)    // 应为 true
```

---

### 任务 1.3：在 `useUndoRedo.js` 中添加快照深拷贝

| 属性 | 内容 |
|------|------|
| **预估时间** | 1 小时 |
| **优先级** | P1 |
| **涉及文件** | `frontend/src/utils/useUndoRedo.js` |
| **依赖任务** | 无 |

**操作步骤**：
1. 在 `useUndoRedo.js` 中添加 `cloneSnapshot(snapshot)` 函数
2. 在 `pushUndo` 中调用 `cloneSnapshot` 代替直接 push

**验收标准**：
- [ ] `cloneSnapshot` 正确处理嵌套对象
- [ ] `cloneSnapshot` 失败时回退到浅拷贝并警告
- [ ] 撤销栈中的数据不被后续修改污染

---

### 任务 1.4：在关键 action 中试用 `markModified`

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P1 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 1.1 |

**操作步骤**：
1. 在 `updateSignal`、`addSignal`、`deleteSignal` 中替换 `markModified(this)`
2. 验证行为与原代码一致

**验收标准**：
- [ ] 替换后的 action 行为与原代码一致
- [ ] `modified` 和 `modifiedAt` 正确更新
- [ ] `_checkModifiedStatus` 定时器正确触发

---

### 任务 1.5：阶段一验证

| 属性 | 内容 |
|------|------|
| **预估时间** | 1-2 小时 |
| **优先级** | P0 |
| **涉及文件** | 全部阶段一修改的文件 |
| **依赖任务** | 1.1 ~ 1.4 |

**验证步骤**：

1. **构建验证**
   ```bash
   cd frontend && npm run build
   ```
   - [ ] 无编译错误
   - [ ] 无警告（或警告在预期范围内）

2. **撤销计数器响应式验证**
   - [ ] 修改信号属性后，`undoCount` 增加 1
   - [ ] `canUndo` 变为 `true`，撤销按钮启用
   - [ ] 执行撤销后，`undoCount` 减少 1，`redoCount` 增加 1
   - [ ] `canRedo` 变为 `true`，重做按钮启用
   - [ ] 执行重做后，`undoCount` 增加 1，`redoCount` 减少 1
   - [ ] 新操作（如再次修改信号）后，`redoCount` 归零，`canRedo` 变为 `false`

3. **`markModified` 验证**
   - [ ] 修改信号后，`modified` 状态变为 `true`
   - [ ] `modifiedAt` 正确更新时间戳
   - [ ] 2 秒后 `_checkModifiedStatus` 正确触发

4. **功能回归验证**
   - [ ] 添加报文正常
   - [ ] 删除报文正常
   - [ ] 修改信号属性正常
   - [ ] 撤销/重做正常

### 任务 1.6：阶段一评审（Sub-Agent）

| 属性 | 内容 |
|------|------|
| **预估时间** | 30 分钟（等待 sub-agent 完成） |
| **优先级** | P0 |
| **涉及文件** | `frontend/src/stores/editor.js`、`frontend/src/utils/storeHelpers.js`、`frontend/src/utils/useUndoRedo.js` |
| **依赖任务** | 1.5 |

**评审方式**：使用 `CodeReview` sub-agent

**评审指令**：
```
请对以下文件进行代码评审：
1. frontend/src/stores/editor.js（重点关注 undoCount/redoCount 响应式计数器的实现）
2. frontend/src/utils/storeHelpers.js（新提取的工具函数）
3. frontend/src/utils/useUndoRedo.js（cloneSnapshot 的实现）

评审重点：
- 响应式计数器是否正确同步（pushUndo/undo/redo/clear 后是否都更新了计数器）
- cloneSnapshot 是否处理了循环引用和不可序列化对象
- markModified 是否与原有行为一致
- 是否存在并发问题
- 代码风格和最佳实践
```

**评审产出**：
- [ ] CodeReview sub-agent 评审报告
- [ ] 评审发现的问题已修复
- [ ] 评审确认通过

### 阶段一检查点

- [ ] 任务 1.1 ~ 1.5 全部完成
- [ ] 任务 1.6 评审通过
- [ ] `npm run build` 通过
- [ ] 撤销/重做计数器响应式正常
- [ ] `markModified` 工具函数工作正常
- [ ] 无功能回归
- [ ] 已提交 git commit（便于阶段二回滚）

---

## 阶段二：提取 uiStore（预计 3-5 天）

**目标**：将 UI 状态从 `editor.js` 迁移到独立的 `uiStore.js`，减少 `editor.js` 约 150 行。

**重要原则**：
- 每次修改 1-2 个组件，立即测试
- `editor.js` 中的 action 通过延迟引用调用 `uiStore`
- 保留 `editor.js` 直到所有引用迁移完成

---

### 任务 2.1：创建 `uiStore.js`

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P0 |
| **涉及文件** | 新建 `frontend/src/stores/uiStore.js` |
| **依赖任务** | 无 |

**操作步骤**：
1. 新建 `stores/uiStore.js`
2. 从 `editor.js` 迁移以下 state：
   - `toast`
   - `contextMenu`
   - `batchModalOpen`
   - `historyModalOpen`
   - `newConfirmOpen`
   - `theme`
   - `locale`
   - `showLogPanel`
   - `logEntries`
3. 迁移相关 actions：`showToast`、`hideToast`、`showContextMenu`、`hideContextMenu`、`setTheme`、`toggleTheme`、`setLocale`、`toggleLocale`、`addLogEntry`、`clearLog`
4. **不迁移** `canUndo` / `canRedo`（按方案设计，这些在 `editor.js` 中）

**验收标准**：
- [ ] `uiStore.js` 可独立 import
- [ ] `uiStore` 可独立实例化
- [ ] `npm run build` 通过

---

### 任务 2.2：修改全局组件

| 属性 | 内容 |
|------|------|
| **预估时间** | 3-4 小时 |
| **优先级** | P0 |
| **涉及文件** | `App.vue`、`TopBar.vue`、`Toast.vue` |
| **依赖任务** | 2.1 |

#### App.vue 修改点
```
store.toast → uiStore.toast
store.contextMenu → uiStore.contextMenu
store.theme → uiStore.theme
```

#### TopBar.vue 修改点
```
store.toggleLocale → uiStore.toggleLocale
store.toggleTheme → uiStore.toggleTheme
store.locale → uiStore.locale
store.theme → uiStore.theme
store.showLogPanel → uiStore.showLogPanel
store.undoCount / redoCount → 保持 editor.undoCount / editor.redoCount（已在阶段一修复）
```

#### Toast.vue 修改点
```
store.toast → uiStore.toast
```

**验收标准**：
- [ ] 主题切换正常
- [ ] 语言切换正常
- [ ] Toast 显示正常
- [ ] 右键菜单正常

---

### 任务 2.3：修改模态框组件

| 属性 | 内容 |
|------|------|
| **预估时间** | 2 小时 |
| **优先级** | P1 |
| **涉及文件** | `BatchModal.vue`、`HistoryModal.vue` |
| **依赖任务** | 2.1 |

#### BatchModal.vue 修改点
```
v-model:visible="store.batchModalOpen" → v-model:visible="uiStore.batchModalOpen"
```

#### HistoryModal.vue 修改点
```
store.historyModalOpen → uiStore.historyModalOpen
```

**验收标准**：
- [ ] 批量添加模态框正常打开/关闭
- [ ] 历史会话模态框正常打开/关闭

---

### 任务 2.4：修改交互组件

| 属性 | 内容 |
|------|------|
| **预估时间** | 2 小时 |
| **优先级** | P1 |
| **涉及文件** | `ContextMenu.vue`、`MessageList.vue` |
| **依赖任务** | 2.1 |

#### ContextMenu.vue 修改点
```
store.contextMenu → uiStore.contextMenu
```

#### MessageList.vue 修改点
```
store.contextMenu → uiStore.contextMenu
```

**验收标准**：
- [ ] 右键菜单正常显示
- [ ] 菜单项点击正常

---

### 任务 2.5：修改信号相关组件

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P1 |
| **涉及文件** | `SignalTable.vue`、`MessagePanel.vue`、`SignalLayoutVisualizer.vue` |
| **依赖任务** | 2.1 |

#### SignalTable.vue 修改点
```
store.batchModalOpen → uiStore.batchModalOpen
```

#### MessagePanel.vue 修改点
```
store.batchModalOpen → uiStore.batchModalOpen
```

#### SignalLayoutVisualizer.vue 修改点
```
store.batchModalOpen → uiStore.batchModalOpen
```

**验收标准**：
- [ ] 批量添加按钮正常打开模态框

---

### 任务 2.6：修改日志面板

| 属性 | 内容 |
|------|------|
| **预估时间** | 1-2 小时 |
| **优先级** | P1 |
| **涉及文件** | `LogPanel.vue` |
| **依赖任务** | 2.1 |

#### LogPanel.vue 修改点
```
store.showLogPanel → uiStore.showLogPanel
store.logEntries → uiStore.logEntries
store.clearLog() → uiStore.clearLog()
```

**验收标准**：
- [ ] 日志面板显示/隐藏正常
- [ ] 日志条目正常显示
- [ ] 清空日志按钮正常

---

### 任务 2.7：清理 `editor.js` 中的 UI 代码

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P0 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 2.2 ~ 2.6（所有组件迁移完成后） |

**操作步骤**：
1. 从 `editor.js` 删除 UI 相关 state（toast、contextMenu、batchModalOpen 等）
2. 从 `editor.js` 删除 UI 相关 actions（showToast、setTheme 等）
3. 在需要显示 Toast 的 action 中添加 `useUiStore()` 延迟引用
4. 在需要添加日志的 action 中添加 `useUiStore().addLogEntry()` 调用

**关键修改示例**：
```javascript
// 修改前
async updateSignal(sigUuid, field, value) {
  // ...
  this.showToast('更新成功')
}

// 修改后
async updateSignal(sigUuid, field, value) {
  // ...
  const uiStore = useUiStore()
  uiStore.showToast('更新成功')
}
```

**验收标准**：
- [ ] `editor.js` 行数减少 ~150 行
- [ ] 所有 Toast 提示正常显示
- [ ] 所有日志记录正常
- [ ] `npm run build` 通过

---

### 任务 2.8：阶段二验证

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P0 |
| **涉及文件** | 全部阶段二修改的文件 |
| **依赖任务** | 2.1 ~ 2.7 |

**验证步骤**：

1. **构建验证**
   ```bash
   cd frontend && npm run build
   ```
   - [ ] 无编译错误
   - [ ] 无未使用的 import 警告

2. **UI 状态隔离验证**
   - [ ] `editor.js` 中无 `toast`、`contextMenu`、`batchModalOpen` 等 UI state
   - [ ] `editor.js` 中无 `showToast`、`setTheme` 等 UI action
   - [ ] `uiStore.js` 可独立 import 和实例化

3. **组件功能验证**（逐项检查）

   | 功能 | 验证方式 | 状态 |
   |------|---------|------|
   | Toast 提示 | 添加信号后查看提示 | [ ] |
   | 主题切换 | 点击主题按钮切换 dark/light | [ ] |
   | 语言切换 | 点击语言按钮切换 zh/en | [ ] |
   | 右键菜单 | 在报文列表右键点击 | [ ] |
   | 批量添加模态框 | 点击"批量+"按钮 | [ ] |
   | 历史会话模态框 | 点击"历史"按钮 | [ ] |
   | 日志面板显示/隐藏 | 点击 📋/📄 按钮 | [ ] |
   | 日志条目记录 | 执行撤销后查看日志 | [ ] |
   | 日志清空 | 点击"清空"按钮 | [ ] |

4. **跨 Store 调用验证**
   - [ ] `editor.js` action 调用 `useUiStore().showToast()` 正常
   - [ ] `editor.js` action 调用 `useUiStore().addLogEntry()` 正常
   - [ ] 无循环依赖报错

5. **功能回归验证**
   - [ ] 添加报文正常
   - [ ] 删除报文正常
   - [ ] 修改信号属性正常
   - [ ] 撤销/重做正常
   - [ ] 批量添加信号正常

### 任务 2.9：阶段二评审（Sub-Agent）

| 属性 | 内容 |
|------|------|
| **预估时间** | 30-45 分钟（等待 sub-agent 完成） |
| **优先级** | P0 |
| **涉及文件** | `frontend/src/stores/uiStore.js`、`frontend/src/stores/editor.js`、所有修改的组件 |
| **依赖任务** | 2.8 |

**评审方式**：使用多个 sub-agent 并行评审

**评审 1：架构设计评审（architecture-design-auditor）**
```
请评审以下架构设计：
1. uiStore.js 的职责边界是否清晰
2. editor.js 与 uiStore.js 的交互方式是否合理（延迟引用 vs 回调注入）
3. 是否存在循环依赖风险
4. 未来进一步拆分（如 dataStore/sessionStore）的可行性

涉及文件：
- frontend/src/stores/uiStore.js
- frontend/src/stores/editor.js
```

**评审 2：前端状态同步评审（frontend-state-sync-auditor）**
```
请评审以下前端状态同步问题：
1. 13 个组件从 editor.js 迁移到 uiStore.js 后，状态同步是否正确
2. 是否存在 Stale Data 问题（组件引用旧 store 数据）
3. 多个组件同时修改 uiStore 状态时的冲突问题
4. 响应式计数器（undoCount/redoCount）在多组件中的同步

涉及文件：
- frontend/src/App.vue
- frontend/src/components/TopBar.vue
- frontend/src/components/LogPanel.vue
- frontend/src/components/Toast.vue
- frontend/src/components/ContextMenu.vue
```

**评审 3：代码评审（CodeReview）**
```
请对以下文件进行代码评审：
1. frontend/src/stores/uiStore.js（新文件）
2. frontend/src/stores/editor.js（删除 UI 代码后的版本）
3. frontend/src/App.vue（UI 引用迁移）
4. frontend/src/components/TopBar.vue（UI 引用迁移）

评审重点：
- uiStore 是否正确管理所有 UI 状态
- editor.js 中是否还有遗漏的 UI 代码
- 组件中的 store 引用是否正确迁移
- 是否存在内存泄漏（未清理的引用）
```

**评审产出**：
- [ ] architecture-design-auditor 评审报告
- [ ] frontend-state-sync-auditor 评审报告
- [ ] CodeReview 评审报告
- [ ] 评审发现的问题已修复
- [ ] 评审确认通过

### 阶段二检查点

- [ ] 任务 2.1 ~ 2.8 全部完成
- [ ] 任务 2.9 评审通过
- [ ] 13 个组件全部迁移完成
- [ ] `editor.js` 中无 UI 相关 state 和 action
- [ ] Toast、主题、语言、日志全部功能正常
- [ ] 模态框打开/关闭正常
- [ ] `npm run build` 通过
- [ ] 无功能回归
- [ ] 已提交 git commit（便于阶段三回滚）

---

## 阶段三：内部代码组织（预计 2-3 天）

**目标**：`editor.js` 按区域组织代码，提升可读性，不改变逻辑。

---

### 任务 3.1：添加区域注释和分隔线

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P1 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 阶段二完成 |

**区域划分**：
```javascript
// ═══════════════════════════════════════════
// 区域 A：数据操作（Data Operations）
// ═══════════════════════════════════════════
// - loadMessages, selectMessage, loadSelectedMessage
// - addMessage, deleteMessage, updateMessageField
// - addSignal, updateSignal, deleteSignal, batchAddSignals
// - autoFixSignal, moveSignalByLayout, resizeSignalByLayout

// ═══════════════════════════════════════════
// 区域 B：会话管理（Session Management）
// ═══════════════════════════════════════════
// - initSession, createDemoSession
// - loadHistorySession, deleteHistorySession
// - renameSession, createNewSession
// - checkApiHealth

// ═══════════════════════════════════════════
// 区域 C：撤销/重做（Undo/Redo）
// ═══════════════════════════════════════════
// - initUndoRedo, pushUndo, undo, redo, clearUndoStack

// ═══════════════════════════════════════════
// 区域 D：剪贴板（Clipboard）
// ═══════════════════════════════════════════
// - copySignal, cutSignal, pasteSignal
// - copyMessage, pasteMessage, duplicateMessage
```

**验收标准**：
- [ ] 每个区域有清晰的注释标题
- [ ] 区域之间有分隔线
- [ ] 区域顺序一致（建议：数据 → 会话 → 撤销 → 剪贴板）

---

### 任务 3.2：重新排列 actions 顺序

| 属性 | 内容 |
|------|------|
| **预估时间** | 2-3 小时 |
| **优先级** | P1 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 3.1 |

**操作步骤**：
1. 按区域顺序重新排列所有 actions
2. 确保 getters 也在合理位置（建议在 actions 之前或之后统一放置）

**当前顺序 vs 目标顺序**：

| 当前顺序（混乱） | 目标顺序（按区域） |
|-----------------|-------------------|
| showToast | loadMessages |
| addLogEntry | selectMessage |
| setTheme | addMessage |
| initUndoRedo | ...（数据操作） |
| loadMessages | initSession |
| selectMessage | createDemoSession |
| addMessage | ...（会话管理） |
| ... | initUndoRedo |
| | pushUndo |
| | ...（撤销/重做） |
| | copySignal |
| | ...（剪贴板） |

**验收标准**：
- [ ] actions 按区域分组排列
- [ ] 无逻辑变化（纯移动代码）

---

### 任务 3.3：添加 JSDoc 注释

| 属性 | 内容 |
|------|------|
| **预估时间** | 3-4 小时 |
| **优先级** | P2 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 3.2 |

**操作步骤**：
1. 为每个 action 添加 JSDoc 注释（参数、返回值、功能说明）
2. 为关键 getter 添加注释
3. 为复杂逻辑添加行内注释

**重点注释的函数**：
- `updateSignal`（乐观更新逻辑复杂）
- `batchAddSignals`（批量操作逻辑复杂）
- `addSignal`（clientUuid → 真实 UUID 的替换逻辑）
- `initUndoRedo`（撤销管理器初始化）

**验收标准**：
- [ ] 所有 action 有 JSDoc 注释
- [ ] 复杂逻辑有行内注释
- [ ] 注释与代码一致

---

### 任务 3.4：清理无用代码

| 属性 | 内容 |
|------|------|
| **预估时间** | 1-2 小时 |
| **优先级** | P2 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 3.2 |

**操作步骤**：
1. 删除未使用的 import
2. 删除未使用的 state
3. 删除遗留的调试 console.log（或统一管理）
4. 删除已注释掉的代码

**注意**：保留有意义的性能计时 log（如 `[STORE] loadMessages() API DONE`），这些对调试有用。

**验收标准**：
- [ ] 无未使用的 import
- [ ] 无未使用的 state
- [ ] 无遗留的注释代码
- [ ] `npm run build` 通过且无警告

---

### 任务 3.5：阶段三验证

| 属性 | 内容 |
|------|------|
| **预估时间** | 1-2 小时 |
| **优先级** | P0 |
| **涉及文件** | `frontend/src/stores/editor.js` |
| **依赖任务** | 3.1 ~ 3.4 |

**验证步骤**：

1. **构建验证**
   ```bash
   cd frontend && npm run build
   ```
   - [ ] 无编译错误
   - [ ] 无未使用的变量/函数警告

2. **代码结构验证**
   - [ ] `editor.js` 按 4 个区域组织（数据/会话/撤销/剪贴板）
   - [ ] 每个区域有清晰的注释标题和分隔线
   - [ ] 区域顺序一致（建议：数据 → 会话 → 撤销 → 剪贴板）
   - [ ] 新开发者能在 30 秒内定位到目标代码

3. **注释验证**
   - [ ] 所有 action 有 JSDoc 注释（@param、@returns、功能说明）
   - [ ] 复杂逻辑（如乐观更新、回滚）有行内注释
   - [ ] 注释与代码一致（无过时注释）

4. **清理验证**
   - [ ] 无未使用的 import
   - [ ] 无未使用的 state/getters/actions
   - [ ] 无遗留的注释代码
   - [ ] 有意义的 console.log 保留（如性能计时），无意义的已删除

5. **功能回归验证**
   - [ ] 添加报文正常
   - [ ] 删除报文正常
   - [ ] 修改信号属性正常
   - [ ] 撤销/重做正常
   - [ ] 批量添加信号正常
   - [ ] 主题切换正常
   - [ ] 日志面板正常

### 任务 3.6：阶段三评审（Sub-Agent）

| 属性 | 内容 |
|------|------|
| **预估时间** | 30 分钟（等待 sub-agent 完成） |
| **优先级** | P0 |
| **涉及文件** | `frontend/src/stores/editor.js`、`frontend/src/stores/uiStore.js`、`frontend/src/utils/storeHelpers.js`、`frontend/src/utils/useUndoRedo.js` |
| **依赖任务** | 3.5 |

**评审方式**：使用 `CodeReview` sub-agent

**评审指令**：
```
请对重构后的代码进行最终评审：

1. frontend/src/stores/editor.js（重构后版本）
   - 代码是否按 4 个区域清晰组织
   - 区域注释是否足够清晰
   - JSDoc 注释是否完整
   - 是否还有可进一步提取的重复逻辑
   - 代码风格是否一致

2. frontend/src/stores/uiStore.js
   - 职责边界是否清晰
   - 是否有遗漏的 UI 状态

3. frontend/src/utils/storeHelpers.js
   - 工具函数是否通用且可复用

4. frontend/src/utils/useUndoRedo.js
   - 撤销/重做逻辑是否健壮
   - cloneSnapshot 是否安全

最终评审标准：
- 代码是否比重构前更易维护
- 新开发者能否快速上手
- 是否还有明显的技术债务
```

**评审产出**：
- [ ] CodeReview 评审报告
- [ ] 评审发现的问题已修复
- [ ] 评审确认通过

### 任务 3.7：最终验收

| 属性 | 内容 |
|------|------|
| **预估时间** | 1 小时 |
| **优先级** | P0 |
| **涉及文件** | 全部重构涉及的文件 |
| **依赖任务** | 3.6 |

**验收步骤**：

1. **全量构建**
   ```bash
   cd frontend && npm run build
   ```
   - [ ] 构建成功
   - [ ] 输出文件大小无异常增长

2. **全量功能测试**（使用 MCP Chrome DevTools 自动化）
   - [ ] 创建 Demo 会话
   - [ ] 添加报文 + 撤销 + 重做
   - [ ] 删除报文 + 撤销
   - [ ] 修改信号属性 + 撤销 + 重做
   - [ ] 批量添加信号 + 撤销
   - [ ] 主题切换
   - [ ] 语言切换
   - [ ] 日志面板显示/隐藏
   - [ ] 模态框打开/关闭

3. **代码统计**
   - [ ] `editor.js` 行数 < 650 行（目标）
   - [ ] `uiStore.js` 行数 ~120 行
   - [ ] `storeHelpers.js` 行数 ~40 行
   - [ ] 总计比重构前减少 15-20%

4. **git 提交**
   - [ ] 所有修改已提交 git
   - [ ] 提交信息清晰（分阶段提交）

### 阶段三检查点

- [ ] 任务 3.1 ~ 3.7 全部完成
- [ ] `editor.js` 按 4 个区域组织
- [ ] 代码结构清晰，新开发者能快速定位
- [ ] JSDoc 注释完整
- [ ] 无无用代码
- [ ] `npm run build` 通过
- [ ] 全量功能测试通过
- [ ] 代码行数达到预期目标
- [ ] 最终评审通过
- [ ] 已提交最终 git commit

---

## 附录 A：完整文件变更清单

### 新建文件

| 文件 | 大小预估 | 说明 |
|------|---------|------|
| `frontend/src/stores/uiStore.js` | ~120 行 | UI 状态管理 |
| `frontend/src/utils/storeHelpers.js` | ~40 行 | 工具函数（markModified 等） |

### 修改文件

| 文件 | 修改内容 | 预估行数变化 |
|------|---------|-------------|
| `frontend/src/stores/editor.js` | 删除 UI 状态/action、添加区域注释、添加 undoCount/redoCount | -150 行 |
| `frontend/src/utils/useUndoRedo.js` | 添加 cloneSnapshot | +20 行 |
| `frontend/src/App.vue` | UI 状态引用迁移 | ~5 处修改 |
| `frontend/src/components/TopBar.vue` | UI 状态引用迁移 | ~8 处修改 |
| `frontend/src/components/Toast.vue` | UI 状态引用迁移 | ~1 处修改 |
| `frontend/src/components/ContextMenu.vue` | UI 状态引用迁移 | ~2 处修改 |
| `frontend/src/components/MessageList.vue` | UI 状态引用迁移 | ~2 处修改 |
| `frontend/src/components/BatchModal.vue` | UI 状态引用迁移 | ~1 处修改 |
| `frontend/src/components/HistoryModal.vue` | UI 状态引用迁移 | ~1 处修改 |
| `frontend/src/components/SignalTable.vue` | UI 状态引用迁移 | ~1 处修改 |
| `frontend/src/components/MessagePanel.vue` | UI 状态引用迁移 | ~1 处修改 |
| `frontend/src/components/SignalLayoutVisualizer.vue` | UI 状态引用迁移 | ~1 处修改 |
| `frontend/src/components/LogPanel.vue` | UI 状态引用迁移 | ~3 处修改 |

---

## 附录 B：风险与缓解措施

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| `editor.js` action 调用 `uiStore` 导致循环依赖 | 运行时错误 | 使用延迟引用（在 action 内部 `const ui = useUiStore()`） |
| 组件迁移遗漏 | 功能异常 | 按附录 A 清单逐组件检查，每修改一个即测试 |
| `undoCount` 同步遗漏 | 按钮状态不更新 | 统一封装 `_syncUndoCounts()` 方法，所有操作栈变更都调用 |
| 阶段二工作量超预期 | 进度延期 | 阶段二可拆分为多个小迭代（每次 2-3 个组件） |
| 构建失败 | 功能不可用 | 每个任务完成后都执行 `npm run build` |

---

## 附录 C：回滚策略

每个阶段完成后，如果出现问题，可按以下方式回滚：

| 阶段 | 回滚方式 |
|------|---------|
| 阶段一 | 删除 `storeHelpers.js`，恢复 `editor.js` 中的 `markModified` 内联代码，删除 `undoCount`/`redoCount` |
| 阶段二 | 恢复 `editor.js` 中的 UI state/action，将组件引用改回 `store.xxx`，删除 `uiStore.js` |
| 阶段三 | 恢复 `editor.js` 的代码顺序（git 回滚），删除区域注释 |

**建议**：每个阶段完成后提交一次 git commit，便于回滚。

---

*文档版本：v1.0*  
*创建时间：2026-06-06*  
*对应方案：ARCHITECTURE_REFACTOR_PLAN.md v2.1*
