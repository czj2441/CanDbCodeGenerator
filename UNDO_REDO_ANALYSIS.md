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
