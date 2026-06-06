# 撤销/重做功能分析与规划

> 生成时间: 2026-06-06
> 文件: `frontend/src/stores/editor.js`

---

## 📊 当前实现状态

### ✅ 已支持撤销的操作

| 操作类型 | 触发场景 | 撤销方式 |
|---------|---------|---------|
| **删除报文** | 右键菜单 → 删除报文 | 恢复整个报文（包含所有信号） |
| **删除信号** | 右键菜单 → 删除信号 | 恢复单个信号 |

### ⚠️ 已定义但未使用的撤销类型

代码中已定义 `undo()` 处理逻辑，但 **从未调用 `pushUndo`**：

| 类型 | 预期用途 | 当前状态 |
|------|---------|---------|
| `message_update` | 撤销报文属性修改 | ❌ 未入栈 |
| `signal_update` | 撤销信号属性修改 | ❌ 未入栈 |

### 🔍 当前问题

1. **报文/信号修改未入栈**：用户编辑属性后无法撤销，只能手动改回
2. **添加操作未入栈**：误添加报文/信号后只能删除，无法一键撤销
3. **快捷键未绑定**：仅顶部按钮可触发撤销，未绑定 `Ctrl+Z`
4. **重做功能缺失**：有 `undoStack` 但无 `redoStack`，撤销后无法重做

---

## 📋 应规划支持的撤销操作

### 高优先级（核心编辑操作）

| 操作 | 触发方式 | 实现方式 |
|------|---------|---------|
| **修改报文属性** | 报文属性面板中修改名称、ID、长度等 | 每次 `@blur` 时入栈 |
| **修改信号属性** | 信号列表/属性面板中修改名称、起始位、长度等 | 每次 `@blur` 时入栈 |
| **添加报文** | 报文列表末尾 "+" 按钮 | 入栈并记录 msgUuid |
| **添加信号** | 信号列表末尾 "+" 按钮 | 入栈并记录 sigUuid |

### 中优先级（批量/布局操作）

| 操作 | 触发方式 | 实现方式 |
|------|---------|---------|
| **批量添加信号** | 批量模态框确认 | 入栈并记录 sigUuids 数组 |
| **调整信号布局** | 拖拽调整字节位置 | 入栈并记录 prev 布局 |
| **复制/粘贴** | 快捷键 Ctrl+C/V | 入栈并记录粘贴的信号 |
| **移动信号** | 拖拽调整信号顺序 | 入栈并记录 fromIdx/toIdx |

### 低优先级（辅助操作）

| 操作 | 触发方式 | 备注 |
|------|---------|------|
| **修改字节序** | 下拉菜单切换 | 可归入 signal_update |
| **修改单位/注释** | 输入框编辑 | 可归入 signal_update |
| **清空画布** | 右键菜单 → 清空 | 入栈并备份 prevMessages |

---

## 🎯 建议实施路径

| 阶段 | 内容 | 预期工作量 |
|------|------|-----------|
| **Phase 1** | 为报文/信号修改、添加操作入栈 | 1-2 小时 |
| **Phase 2** | 绑定 `Ctrl+Z` 快捷键 | 15 分钟 |
| **Phase 3** | 添加 `redoStack` 和 `redo()` 功能 | 1 小时 |
| **Phase 4** | 为布局/批量操作入栈 | 2-3 小时 |

---

## 💡 技术实现参考

### 当前 undo() 逻辑（已实现）

```javascript
async undo() {
  if (this.undoStack.length === 0) {
    this.showToast(t('toast.undoEmpty'))
    return
  }
  const snap = this.undoStack.pop()
  try {
    if (snap.type === 'message_delete') {
      await api('POST', '/api/messages', snap.data)
    } else if (snap.type === 'signal_delete') {
      await api('POST', `/api/messages/${snap.msgId}/signals`, snap.data)
    } else if (snap.type === 'message_update') {
      await api('PUT', `/api/messages/${snap.msgId}`, snap.prev)
    } else if (snap.type === 'signal_update') {
      await api('PUT', `/api/messages/${snap.msgId}/signals/${snap.sigIdx}`, snap.prev)
    }
    await this.loadMessages()
    if (this.selectedMsgId != null) await this.loadSelectedMessage()
    this.showToast(t('toast.undoSuccess'))
  } catch (e) {
    this.showToast(e.message, true)
  }
}
```

### 示例：修改信号属性时入栈

```javascript
// SignalTable.vue 中 @blur 触发时
async function update(uuid, field, value) {
  const sig = msg.signals.find(s => s.uuid === uuid)
  if (!sig) return

  // 1. 保存修改前的状态
  store.pushUndo({
    type: 'signal_update',
    msgId: store.selectedMsgId,
    sigUuid: uuid,
    prev: { ...sig }  // 深拷贝旧值
  })

  // 2. 发送 API 更新
  await api('PUT', `/api/messages/${store.selectedMsgId}/signals/${uuid}`, {
    ...sig,
    [field]: value
  })

  // 3. 刷新消息
  await store.loadSelectedMessage()
}
```

### 示例：添加报文时入栈

```javascript
async function addMessage() {
  const newMsg = {
    id: nextMsgId(),
    name: 'NewMessage',
    length: 8,
    signals: [],
    comment: ''
  }

  // 1. 入栈（用于撤销删除）
  store.pushUndo({
    type: 'message_add',
    msgUuid: newMsg.uuid
  })

  // 2. 发送 API
  await api('POST', '/api/messages', newMsg)
  await store.loadMessages()
}
```

---

## 📝 注意事项

1. **深拷贝**：入栈时必须使用 `JSON.parse(JSON.stringify(obj))` 或 `structuredClone()` 深拷贝，避免引用污染
2. **撤销栈大小**：当前限制 50 步（`undoStack.length > 50` 时 shift），可保持或调整
3. **乐观更新**：前端应立即更新 UI，撤销时再回滚，保持用户体验流畅
4. **会话隔离**：撤销栈绑定当前会话，切换会话时自动清空

---

## 🔧 代码评审发现的问题

### 🔴 Critical Issues (MUST FIX)

#### 1. 快捷键冲突 - 在输入框中也会触发撤销/重做

**文件**: `frontend/src/components/TopBar.vue#L56-L66`

**问题**: `handleKeydown` 函数没有检查事件目标是否为输入元素。当用户在报文名称、信号属性等输入框中编辑时，按下 `Ctrl+Z` 会同时触发浏览器原生的撤销（撤销输入框文本）和应用的撤销操作，导致双重撤销和数据不一致。

**修复方案**:
```javascript
function handleKeydown(event) {
  const isInput = event.target.tagName === 'INPUT' || 
                  event.target.tagName === 'TEXTAREA' || 
                  event.target.isContentEditable
  if (isInput) return  // 在输入框中不拦截快捷键
  
  if (event.ctrlKey || event.metaKey) {
    if (event.key === 'z' || event.key === 'Z') {
      event.preventDefault()
      store.undo()
    } else if (event.key === 'y' || event.key === 'Y') {
      event.preventDefault()
      store.redo()
    }
  }
}
```

#### 2. signal_update 和 message_update 操作从未入栈

**文件**: `frontend/src/stores/editor.js#L314-L339`

**问题**: `updateMessageField` 和 `updateSignal` 方法执行属性修改时，**没有调用 `pushUndo`**。虽然在 `useUndoRedo.js` 中定义了 `message_update` 和 `signal_update` 的处理器，但实际从未使用。用户修改报文/信号属性后无法撤销。

**修复方案** - 在 `updateMessageField` 中添加：
```javascript
async updateMessageField(field, value) {
  if (this.selectedMsgId == null) return
  
  const msg = this.messageCache[this.selectedMsgId]
  if (!msg) return
  
  // 入栈：记录修改前的状态
  this.pushUndo({
    type: 'message_update',
    msgId: this.selectedMsgId,
    prev: { [field]: msg[field] },
    next: { [field]: value }
  })
  
  // ... 后续乐观更新逻辑不变
```

在 `updateSignal` 中添加类似逻辑。

#### 3. 并发撤销操作可能导致状态不一致

**文件**: `frontend/src/utils/useUndoRedo.js#L90-L121`

**问题**: `undo()` 和 `redo()` 是 async 函数，但没有任何并发控制。如果用户快速连续按 `Ctrl+Z`，前一个撤销操作还在执行 API 调用时，第二个撤销已经开始，可能导致：
- undoStack 被意外修改
- redoStack 状态混乱
- UI 刷新顺序错乱

**修复方案**: 添加执行中标志
```javascript
export function createUndoRedoManager({ maxSize = 50, onReload, onToast } = {}) {
  const undoStack = []
  const redoStack = []
  let isExecuting = false  // 防止并发执行

  async function undo() {
    if (isExecuting) return  // 忽略重复调用
    if (undoStack.length === 0) {
      if (onToast) onToast('无操作可撤销', false)
      return
    }

    isExecuting = true
    try {
      const snap = undoStack.pop()
      // ... 执行撤销逻辑
    } finally {
      isExecuting = false
    }
  }
  
  // redo() 同样处理
```

### 🟡 Warnings (SHOULD FIX)

#### 4. 撤销按钮未根据栈状态禁用

**文件**: `frontend/src/components/TopBar.vue#L6`

**问题**: 撤销按钮没有 `:disabled` 属性，而重做按钮有（L7）。当撤销栈为空时，按钮仍然可点击，虽然会显示提示，但用户体验不一致且浪费 API 调用。

**修复方案**:
```vue
<button class="btn" @click="store.undo()" 
        title="撤销 (Ctrl+Z)" 
        :disabled="!store._undoRedo || store._undoRedo.undoCount === 0">
  {{ t('topbar.undo') }}
</button>
```

#### 5. 国际化文本未完全使用

**文件**: `frontend/src/utils/useUndoRedo.js` 和 `frontend/src/i18n.js`

**问题**: i18n.js 中定义了 `toast.undoSuccess` 和 `toast.undoEmpty`，但 `useUndoRedo.js` 中硬编码了中文字符串 `'无操作可撤销'`、`'撤销成功'` 等。这会导致切换语言时提示信息仍然是中文。

**修复方案**: 在 `createUndoRedoManager` 中接受 `t` 函数作为参数，或在回调中处理国际化。

#### 6. addMessage 和 addSignal 操作未入栈

**文件**: `frontend/src/stores/editor.js#L251-L287`

**问题**: 添加报文和添加信号操作没有调用 `pushUndo`，用户误添加后只能手动删除，无法一键撤销。

**修复方向**: 
- 在 `addMessage` 的 API 成功后入栈 `message_add` 类型
- 在 `addSignal` 的 API 成功后入栈 `signal_add` 类型
- 在 `UNDO_HANDLERS` 中添加对应的删除操作
- 在 `REDO_HANDLERS` 中添加对应的添加操作

#### 7. batchAddSignals 操作未入栈

**文件**: `frontend/src/stores/editor.js#L469-L525`

**问题**: 批量添加信号是高风险操作（一次添加多个信号），但没有撤销支持。如果批量添加出错，用户无法快速回滚。

**修复方向**: 在 `finally` 块或成功后调用 `pushUndo`，记录所有添加的信号 UUID，撤销时批量删除。

### 💡 Suggestions (CONSIDER)

#### 8. 撤销操作缺少操作描述

**问题**: 当前 toast 只显示"撤销成功"，没有说明撤销了什么操作（如"已撤销：删除报文"）。用户不清楚自己撤销了什么。

**修复方案**: 在 snapshot 中添加 `description` 字段，撤销时显示具体描述。

#### 9. 快捷键重复注册风险

**问题**: TopBar.vue 和 SignalTable.vue 都注册了 `Ctrl+Z` 快捷键监听。如果两个组件同时存在（通常是这样），同一按键会触发两次 `store.undo()`，虽然有并发保护，但这是设计缺陷。

**修复方案**: 建议将快捷键统一管理，放在 App.vue 或单独的快捷键管理模块中。
