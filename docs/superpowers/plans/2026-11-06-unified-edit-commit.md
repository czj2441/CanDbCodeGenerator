# 统一编辑提交机制实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有右侧属性面板的编辑只提交到“开始编辑时”的目标，并让所有选中项切换在修改选中前统一 flush 当前编辑。

**Architecture:** 新增模块级 `pendingEdit` 注册表：面板在 `focusin` 时快照目标，`blur` / `@change` 时取走快照提交；`uiStore` / `messages` 的选中 action 在改选中前调用 `flushPendingEdit()` 同步 blur。服务端删除走 cancel，重命名/改 id 走 remap。最后用源码扫描测试禁止组件直接写选中状态。

**Tech Stack:** Vue 3 `<script setup>`、Pinia、Node 内置 `node --test`（无组件测试框架）、Vite 构建。

**Spec:** `docs/superpowers/specs/2026-11-06-unified-edit-commit-design.md`

## Global Constraints

- 不修改后端协议。
- 不重构表格单元格编辑：`SignalEditorTab` / `MessageTab` / `ValueTableTab` 继续使用行作用域目标（`sig.name` / `m.id` / `name`）。
- 纯逻辑用 `node --test`；组件改动以 `npm run build` + 手动 smoke 验证，不引入组件测试框架。
- `frontend/src/composables/pendingEdit.js` 不得 import 任何 store。
- `flushPendingEdit()` 同步执行，不等待网络。
- 异步提交必须在第一个 `await` 前取得目标快照；`await` 后不得再读 `ui.selectedSignalName` / `ui.selectedVtName` / `editor.selectedMsgId`。
- `frontend/src/components/**/*.vue` 中不得直接赋值 `selectedSignalName` / `selectedVtName` / `selectedMsgId`。
- 每个 task 结束都执行：
  ```bash
  cd frontend
  node --test "src/**/__tests__/*.test.js"
  npm run build
  ```

## Review Focus

- 面板输入框有焦点时点击另一个选中项：编辑必须落到旧目标。
- 表格方向键导航：注册表为空时 `flushPendingEdit()` 不得 blur 当前单元格。
- 同一面板内两个输入框切换：`blur` 取走快照后，下一次 `focusin` 必须重新建立快照。
- 异步流程（新建值描述表、重命名、改 id）期间切换选中：完成后不得写回新目标。
- 服务端删除 / 重命名 / 改 id / undo / redo 期间存在未提交编辑：必须 cancel 或 remap。

---

## Task 1: pendingEdit 注册表

**Files:**
- Create: `frontend/src/composables/pendingEdit.js`
- Create: `frontend/src/composables/__tests__/pendingEdit.test.js`

**Interfaces:**
- Produces:
  ```js
  beginPendingEdit(owner, target, { cancel } = {})
  peekPendingEdit(owner)            // target | null
  takePendingEditTarget(owner)      // target | null
  clearPendingEdit(owner)
  cancelPendingEdit(owner, predicate?)  // predicate(target) === false 时保留
  remapPendingEditTarget(owner, mapper)
  flushPendingEdit()
  cancelAllPendingEdits()
  PENDING_EDIT_OWNERS // { signalPanel, messagePanel, valueTablePanel }
  usePanelEdit(owner, getTarget) // { begin, peek, take, snapshot, clear, cancel, commit }
  ```

- [ ] **Step 1: 写失败测试 `frontend/src/composables/__tests__/pendingEdit.test.js`**

```js
import { test, afterEach } from 'node:test'
import assert from 'node:assert'
import {
  beginPendingEdit, peekPendingEdit, takePendingEditTarget, clearPendingEdit,
  cancelPendingEdit, remapPendingEditTarget, flushPendingEdit,
  cancelAllPendingEdits, usePanelEdit,
} from '../pendingEdit.js'

const originalDocument = globalThis.document
afterEach(() => {
  cancelAllPendingEdits()
  if (originalDocument === undefined) delete globalThis.document
  else globalThis.document = originalDocument
})
const setActiveElement = (el) => { globalThis.document = { activeElement: el } }

test('begin / peek / take 返回并清除快照', () => {
  beginPendingEdit('a', { name: 'A' })
  assert.deepEqual(peekPendingEdit('a'), { name: 'A' })
  assert.deepEqual(takePendingEditTarget('a'), { name: 'A' })
  assert.equal(peekPendingEdit('a'), null)
})

test('clear 不调用 cancel；cancel 调用回调并清除', () => {
  let cancelled = 0
  beginPendingEdit('b', { name: 'B' }, { cancel: () => { cancelled += 1 } })
  clearPendingEdit('b')
  assert.equal(cancelled, 0)

  let received = null
  beginPendingEdit('c', { name: 'C' }, { cancel: (t) => { received = t.name } })
  cancelPendingEdit('c')
  assert.equal(received, 'C')
  assert.equal(peekPendingEdit('c'), null)
})

test('cancel 的 predicate 返回 false 时保留快照', () => {
  beginPendingEdit('d', { name: 'D' })
  cancelPendingEdit('d', () => false)
  assert.deepEqual(peekPendingEdit('d'), { name: 'D' })
})

test('remap 修改已有快照的目标', () => {
  beginPendingEdit('e', { msgId: 1, signalName: 'A' })
  remapPendingEditTarget('e', (t) => ({ ...t, signalName: 'B' }))
  assert.deepEqual(peekPendingEdit('e'), { msgId: 1, signalName: 'B' })
})

test('flush 在注册表为空时不会 blur（保护方向键焦点）', () => {
  let blurred = 0
  setActiveElement({ tagName: 'INPUT', blur: () => { blurred += 1 } })
  flushPendingEdit()
  assert.equal(blurred, 0)
})

test('flush 先 blur 再取消；blur 中能取到旧目标', () => {
  const committed = []
  const state = { selected: 'A' }
  setActiveElement({
    tagName: 'INPUT',
    blur() {
      const t = takePendingEditTarget('f')
      if (t) committed.push(t.signalName)
    },
  })
  beginPendingEdit('f', { signalName: state.selected })
  flushPendingEdit()
  state.selected = 'B'
  assert.deepEqual(committed, ['A'])
  assert.equal(peekPendingEdit('f'), null)
})

test('flush 会取消 blur 后仍未消费的快照', () => {
  let cancelled = 0
  setActiveElement({ tagName: 'INPUT', blur: () => {} })
  beginPendingEdit('g', { name: 'G' }, { cancel: () => { cancelled += 1 } })
  flushPendingEdit()
  assert.equal(cancelled, 1)
  assert.equal(peekPendingEdit('g'), null)
})

test('usePanelEdit.commit 使用快照；无快照时回退当前目标', () => {
  const edit = usePanelEdit('h', () => ({ signalName: 'current' }))
  beginPendingEdit('h', { signalName: 'snapshot' })
  let received = null
  edit.commit((t) => { received = t.signalName })
  assert.equal(received, 'snapshot')

  const fallback = usePanelEdit('i', () => ({ signalName: 'fallback' }))
  fallback.commit((t) => { received = t.signalName })
  assert.equal(received, 'fallback')
})

test('blur 取走快照后，下一次 begin 会建立新快照', () => {
  const edit = usePanelEdit('j', () => ({ signalName: 'B' }))
  beginPendingEdit('j', { signalName: 'A' })
  assert.deepEqual(edit.take(), { signalName: 'A' })
  edit.begin()
  let received = null
  edit.commit((t) => { received = t.signalName })
  assert.equal(received, 'B')
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && node --test src/composables/__tests__/pendingEdit.test.js`
Expected: FAIL，`Cannot find module '../pendingEdit.js'`

- [ ] **Step 3: 实现 `frontend/src/composables/pendingEdit.js`**

```js
const pendingEdits = new Map()
const EDITABLE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

export const PENDING_EDIT_OWNERS = Object.freeze({
  signalPanel: 'signal-panel',
  messagePanel: 'message-panel',
  valueTablePanel: 'value-table-panel',
})

export function beginPendingEdit(owner, target, { cancel } = {}) {
  pendingEdits.set(owner, { target, cancel })
}

export function peekPendingEdit(owner) {
  return pendingEdits.get(owner)?.target ?? null
}

export function takePendingEditTarget(owner) {
  const entry = pendingEdits.get(owner)
  if (!entry) return null
  pendingEdits.delete(owner)
  return entry.target
}

export function clearPendingEdit(owner) {
  pendingEdits.delete(owner)
}

export function cancelPendingEdit(owner, predicate) {
  const entry = pendingEdits.get(owner)
  if (!entry) return
  if (predicate && !predicate(entry.target)) return
  pendingEdits.delete(owner)
  try {
    entry.cancel?.(entry.target)
  } catch (e) {
    console.error('[pendingEdit] cancel callback failed', e)
  }
}

export function remapPendingEditTarget(owner, mapper) {
  const entry = pendingEdits.get(owner)
  if (!entry) return
  const next = mapper(entry.target)
  if (next != null) entry.target = next
}

export function cancelAllPendingEdits() {
  for (const owner of [...pendingEdits.keys()]) cancelPendingEdit(owner)
}

export function flushPendingEdit() {
  if (pendingEdits.size === 0) return
  const el = typeof document !== 'undefined' ? document.activeElement : null
  if (el && EDITABLE_TAGS.has(el.tagName) && typeof el.blur === 'function') {
    el.blur() // 同步触发 blur handler，此时选中项尚未变化
  }
  for (const owner of [...pendingEdits.keys()]) {
    cancelPendingEdit(owner)
    if (import.meta.env?.DEV) console.warn(`[pendingEdit] discarded un-flushed edit for ${owner}`)
  }
}

export function usePanelEdit(owner, getTarget) {
  return {
    begin() {
      const target = getTarget()
      if (target) beginPendingEdit(owner, target)
    },
    peek() { return peekPendingEdit(owner) },
    take() { return takePendingEditTarget(owner) },
    snapshot() { return takePendingEditTarget(owner) ?? (getTarget() || null) },
    clear() { clearPendingEdit(owner) },
    cancel() { cancelPendingEdit(owner) },
    commit(fn) {
      const target = takePendingEditTarget(owner) ?? getTarget()
      if (target == null) return undefined
      return fn(target)
    },
  }
}
```

`flushPendingEdit()` 在注册表为空时必须立即返回：表格方向键导航会在 `target.focus()` 后调用选中 action，无条件 blur 会夺走刚聚焦的单元格。

- [ ] **Step 4: 运行确认通过**

Run: `cd frontend && node --test src/composables/__tests__/pendingEdit.test.js`
Expected: PASS，9/9

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/pendingEdit.js frontend/src/composables/__tests__/pendingEdit.test.js
git commit -m "feat(edit): add pending edit registry with target snapshots"
```

---

## Task 2: 选中 actions

**Files:**
- Modify: `frontend/src/stores/uiStore.js`
- Modify: `frontend/src/stores/messages.js`

**Interfaces:**
- Consumes: Task 1 的 `flushPendingEdit`, `cancelPendingEdit`, `cancelAllPendingEdits`, `PENDING_EDIT_OWNERS`。
- Produces:
  ```js
  ui.selectSignal(name, { flush = true } = {})
  ui.clearSignalSelection({ discard = false } = {})
  ui.selectValueTable(name, { flush = true } = {})
  messages.selectMessage(id, { flush = true } = {})
  ```

- [ ] **Step 1: `uiStore.js` 顶部 import 并新增选中 action**

```js
import {
  flushPendingEdit, cancelPendingEdit, cancelAllPendingEdits, PENDING_EDIT_OWNERS,
} from '../composables/pendingEdit.js'
```

在 `actions` 中新增：

```js
selectSignal(name, { flush = true } = {}) {
  if (this.selectedSignalName === name) return
  if (flush) flushPendingEdit()
  this.selectedSignalName = name
},

clearSignalSelection({ discard = false } = {}) {
  if (discard) cancelPendingEdit(PENDING_EDIT_OWNERS.signalPanel)
  else flushPendingEdit()
  this.selectedSignalName = null
},

selectValueTable(name, { flush = true } = {}) {
  if (this.selectedVtName === name) return
  if (flush) flushPendingEdit()
  this.selectedVtName = name
},
```

- [ ] **Step 2: Tab / 布局 action**

- `toggleLayoutView`：toggle 和清空 `selectedSignalName` 之前调用 `flushPendingEdit()`。
- `switchCenterTab(tab)`：若 `this.activeTabId === tab` 直接返回；否则先 `flushPendingEdit()`，再执行原有 `_saveActiveTabState` 与赋值。
- `openMessageTab`：已存在时仍走 `activateMessageTab`；新建 tab 时在 `_saveActiveTabState()` 之前 `flushPendingEdit()`。
- `activateMessageTab`：找到 tab 后、`_saveActiveTabState()` 之前 `flushPendingEdit()`。
- `closeMessageTab(msgId, { discard = false } = {})`：仅当关闭的是活跃 tab 时，`discard ? cancelAllPendingEdits() : flushPendingEdit()`，其余逻辑不变。

action 内部的 `editor.selectedMsgId = ...` / `this.selectedSignalName = null` 保留；它们属于 action 层，不在源码扫描范围内。

- [ ] **Step 3: `messages.js`**

新增 `import { flushPendingEdit } from '../composables/pendingEdit.js'`，替换：

```js
selectMessage(id, { flush = true } = {}) {
  const editor = useCoreStore()
  if (editor.selectedMsgId === id) {
    if (editor.messageCache[id] == null) this.loadSelectedMessage()
    return
  }
  if (flush) flushPendingEdit()
  editor.selectedMsgId = id
  this.loadSelectedMessage()
},
```

`addMessage` 中 `editor.selectedMsgId = result.id` 之前插入 `flushPendingEdit()`。

- [ ] **Step 4: 测试与构建**

Run: `cd frontend && node --test "src/**/__tests__/*.test.js" && npm run build`
Expected: 全量测试通过，构建成功。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/uiStore.js frontend/src/stores/messages.js
git commit -m "feat(selection): route selection changes through flushing actions"
```

---

## Task 3: SignalPanel + 信号选中入口

**Files:**
- Modify: `frontend/src/components/SignalPanel.vue`
- Modify: `frontend/src/components/SignalEditorTab.vue`
- Modify: `frontend/src/components/SignalLayoutVisualizer.vue`
- Modify: `frontend/src/components/DataErrorList.vue`

**Interfaces:**
- Consumes: `ui.selectSignal`, `ui.clearSignalSelection`, `usePanelEdit`, `PENDING_EDIT_OWNERS.signalPanel`。

- [ ] **Step 1: SignalPanel 接入注册表**

根节点 `<div class="panel" ...>` 加 `@focusin="edit.begin"`，脚本新增：

```js
import { usePanelEdit } from '../composables/pendingEdit.js'

const edit = usePanelEdit('signal-panel', () => ({
  signalName: ui.selectedSignalName,
  msgId: msg.value?.id,
  valueTableName: localValueTableName.value,
}))
```

- [ ] **Step 2: 所有属性提交改用 `edit.commit`**

```js
function updateSignal(field, value) {
  edit.commit((t) => {
    if (!t.signalName) return
    signals.updateSignal(t.signalName, field, value, t.msgId).catch(() => {})
  })
}

function onValueTableRefChange() {
  if (localValueTableName.value === '__new__') return
  edit.commit((t) => {
    if (!t.signalName) return
    signals.updateSignal(t.signalName, 'value_table_name', localValueTableName.value, t.msgId)
      .catch(() => {})
  })
}
```

`modifyDisplayStartBit(displayValue)`：`edit.commit` 内用目标从 `store.messageCache[t.msgId].signals[t.signalName]` 取 `length` / `byte_order` / `start_bit` / `dlc` 计算，再提交 `start_bit`。不得读 `selectedSig`：

```js
function modifyDisplayStartBit(displayValue) {
  edit.commit((t) => {
    if (!t.signalName) return
    const targetMsg = store.messageCache[t.msgId]
    const sig = targetMsg?.signals?.[t.signalName]
    if (!sig) return
    const maxBit = (targetMsg.dlc || 8) * 8 - 1
    const msb = toStorageStartBit(displayValue, sig.length, sig.byte_order, maxBit, sig.start_bit)
    signals.updateSignal(t.signalName, 'start_bit', msb >= 0 ? msb : -1, t.msgId).catch(() => {})
  })
}
```

`handleByteOrderChange(e)`：`edit.commit` 内从目标取 `oldOrder` 并在失败时回滚；回滚前判断 `ui.selectedSignalName === t.signalName`，避免覆写已切换面板的 select。

- [ ] **Step 3: 内联条目与新建值描述表**

`inlineCommitEntries` 改在 `edit.commit((t) => { const name = t?.valueTableName; ... })` 内校验并调用 `valueTablesStore.updateValueTable(name, dict)`，保留 `_skipVtWatch = true`。

`confirmNewVt` 必须是“先快照、后 await”：

```js
let newVtInFlight = false

async function confirmNewVt() {
  if (newVtInFlight) return
  const target = edit.snapshot()
  if (!target?.signalName) { showNewVtInput.value = false; return }

  const name = newVtName.value.trim()
  if (!name) { localValueTableName.value = ''; showNewVtInput.value = false; return }
  if (store.valueTables[name]) {
    ui.showToast(t('valtable.duplicateName'), true)
    localValueTableName.value = ''
    showNewVtInput.value = false
    return
  }

  newVtInFlight = true
  try {
    await valueTablesStore.addValueTable(name, { '0': 'Default' })
    if (ui.selectedSignalName === target.signalName) {
      localValueTableName.value = name
      syncInlineEntries(name)
    }
    signals.updateSignal(target.signalName, 'value_table_name', name, target.msgId)
      .catch(() => {})
  } catch { /* toast already shown */ }
  finally {
    newVtInFlight = false
    showNewVtInput.value = false
    newVtName.value = ''
  }
}
```

- [ ] **Step 4: 信号选中入口改用 action**

`SignalEditorTab.vue`：
- 删除 `commitPendingEditOutside` 的 import 与调用。
- `selectedSigName` 改为只读 `computed(() => ui.selectedSignalName)`。
- `watch(effectiveMsgId, ...)` 中清空选中改为 `ui.clearSignalSelection({ discard: true })`。
- `handleRowMouseDown` 中：交互列选中用 `ui.selectSignal(sigName)`；普通行点击时，已选中 → `ui.clearSignalSelection()`，否则 `ui.selectSignal(sigName)` 后再 `multiSelect.handleRowClick`。
- 方向键 `onRowSelect` 用 `ui.selectSignal(sig.name)`。

`SignalLayoutVisualizer.vue`：`onCellClick` 用 `ui.selectSignal(cell.name)`；`onStageClick` 与 `watch(effectiveMsgId)` 用 `ui.clearSignalSelection()` / `ui.clearSignalSelection({ discard: true })`。

`DataErrorList.vue`：`ui.selectedSignalName = err.signal_name` 改为 `ui.selectSignal(err.signal_name)`。

- [ ] **Step 5: 测试与构建**

Run: `cd frontend && node --test "src/**/__tests__/*.test.js" && npm run build`
Expected: 全量测试通过，构建成功。

- [ ] **Step 6: 手动 smoke（信号）**

1. A 改 factor 后点击 B：A 变化，B 不变。
2. A 改 name 后点击 B：A 重命名。
3. Motorola A 改起始位后点击 B：使用 A 的 length/order。
4. A 新建值描述表输入名称后直接点击 B：引用落在 A。
5. 表格方向键上下移动：焦点不丢失。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/SignalPanel.vue frontend/src/components/SignalEditorTab.vue frontend/src/components/SignalLayoutVisualizer.vue frontend/src/components/DataErrorList.vue
git commit -m "fix(signal): commit panel edits to the signal being edited"
```

---

## Task 4: MessagePanel + MessageTab

**Files:**
- Modify: `frontend/src/components/MessagePanel.vue`
- Modify: `frontend/src/components/MessageTab.vue`

**Interfaces:**
- Consumes: `usePanelEdit`、`messages.selectMessage`。

- [ ] **Step 1: MessagePanel 接入注册表**

根节点加 `@focusin="edit.begin"`，脚本：

```js
import { usePanelEdit } from '../composables/pendingEdit.js'
const edit = usePanelEdit('message-panel', () => ({ msgId: msg.value?.id }))
```

- [ ] **Step 2: 提交函数改用快照**

```js
function update(field, value) {
  edit.commit((t) => {
    if (t.msgId == null) return
    messages.updateMessageField(field, value, t.msgId).catch(() => {})
  })
}

function updateDlc(value) { update('dlc', value) }

function toggleIsFd(newIsFd) {
  edit.commit((t) => {
    if (t.msgId == null) return
    messages.updateMessageField('is_fd', newIsFd, t.msgId).catch(() => {
      if (store.selectedMsgId !== t.msgId) return
      const actual = store.messageCache[t.msgId]?.is_fd
      localIsFd.value = actual ? 'true' : 'false'
      if (isFdEl.value) isFdEl.value.value = localIsFd.value
    })
  })
}
```

- [ ] **Step 3: MessageTab 删除旧 helper**

删除 `commitPendingEditOutside` 的 import 与调用；`messages.selectMessage(msgId)` 已自带 flush，其余不变。

- [ ] **Step 4: 测试与构建**

Run: `cd frontend && node --test "src/**/__tests__/*.test.js" && npm run build`
Expected: 全量测试通过，构建成功。

- [ ] **Step 5: 手动 smoke（报文）**

1. A 改 name 后点击 B：A 变化。
2. A 改 id 后点击 B：A 的 id 变化，B 不被修改。
3. A 切 CAN FD 失败回滚时已切到 B：B 的下拉框不被改错。
4. 报文列表方向键导航焦点不丢失。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MessagePanel.vue frontend/src/components/MessageTab.vue
git commit -m "fix(message): commit panel edits to the message being edited"
```

---

## Task 5: ValueTablePanel + ValueTableTab

**Files:**
- Modify: `frontend/src/components/ValueTablePanel.vue`
- Modify: `frontend/src/components/ValueTableTab.vue`

**Interfaces:**
- Consumes: `usePanelEdit`、`ui.selectValueTable`。

- [ ] **Step 1: ValueTablePanel 接入注册表**

根节点加 `@focusin="edit.begin"`，脚本：

```js
import { usePanelEdit } from '../composables/pendingEdit.js'
const edit = usePanelEdit('value-table-panel', () => ({ vtName: selectedName.value }))
```

- [ ] **Step 2: 重命名改用快照**

```js
async function commitRename() {
  const target = edit.snapshot()
  if (!target?.vtName) return
  const oldName = target.vtName
  const newName = editingName.value.trim()
  if (!newName) { editingName.value = oldName; ui.showToast(t('valtable.emptyName'), true); return }
  if (newName === oldName) return
  if (editor.valueTables[newName]) {
    editingName.value = oldName
    ui.showToast(t('valtable.duplicateName'), true)
    return
  }
  try {
    await valueTables.renameValueTable(oldName, newName)
    _skipVtWatch = true
    if (ui.selectedVtName === oldName) {
      ui.selectValueTable(newName, { flush: false })
      editingName.value = newName
    }
  } catch {
    if (ui.selectedVtName === oldName) editingName.value = oldName
  }
}
```

- [ ] **Step 3: 条目提交改用快照**

`commitEntries` 外层改为 `edit.commit((t) => { if (!t?.vtName) return; ...; valueTables.updateValueTable(t.vtName, dict) })`，校验逻辑不变。`addEntry` 不变，`removeEntry` 继续调用 `commitEntries()`。

- [ ] **Step 4: ValueTableTab 改用 action**

删除 `commitPendingEditOutside` 的 import 与调用。替换所有 `ui.selectedVtName = ...`：

- `commitRename` 成功后：`if (ui.selectedVtName === name) ui.selectValueTable(newName, { flush: false })`
- `handleRowMouseDown` 两个分支：先按原逻辑设置 `editingName`，再 `ui.selectValueTable(name)`
- 方向键 `onRowSelect`：`ui.selectValueTable(sortedFilteredNames.value[rowIdx])`
- `addNewTable` 成功后：`ui.selectValueTable(name)`
- `deleteTable` 成功后：`if (ui.selectedVtName === name) ui.selectValueTable(null, { flush: false })`
- `valueTableFocusName` watch：`ui.selectValueTable(name)`
- `onMounted` 自动选中：`ui.selectValueTable(sortedNames.value[0])`

- [ ] **Step 5: 测试与构建**

Run: `cd frontend && node --test "src/**/__tests__/*.test.js" && npm run build`
Expected: 全量测试通过，构建成功。

- [ ] **Step 6: 手动 smoke（值描述表）**

1. A 改条目后点击 B：A 变化，B 不变。
2. A 改 name 后点击 B：A 重命名。
3. 重命名 A 未完成时点击 B：完成后不抢回选中。
4. 表格方向键导航焦点不丢失。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ValueTablePanel.vue frontend/src/components/ValueTableTab.vue
git commit -m "fix(valtable): commit panel edits to the value table being edited"
```

---

## Task 6: 服务端事件、剪贴板、文件操作

**Files:**
- Modify: `frontend/src/stores/coreStore.js`
- Modify: `frontend/src/stores/clipboard.js`
- Modify: `frontend/src/stores/fileOperations.js`

**Interfaces:**
- Consumes: `cancelAllPendingEdits`, `cancelPendingEdit`, `remapPendingEditTarget`, `PENDING_EDIT_OWNERS`, `flushPendingEdit`。

- [ ] **Step 1: coreStore import 与全量替换前 cancel**

```js
import {
  cancelAllPendingEdits, cancelPendingEdit, remapPendingEditTarget, PENDING_EDIT_OWNERS,
} from '../composables/pendingEdit.js'
```

- `case 'full_sync':` 开头（`WsFrontendDiag.count('full_sync')` 后）调用 `cancelAllPendingEdits()`。
- `case 'undo_applied': case 'redo_applied':` 开头调用 `cancelAllPendingEdits()`。
- `full_sync` 中 `selectedMsgId` 因不存在被置空时，同时 `useUiStore().clearSignalSelection({ discard: true })`。
- `full_sync` / undo / redo 中关闭失效动态 tab 时传 `{ discard: true }`：
  `.forEach(t => useUiStore().closeMessageTab(t.msgId, { discard: true }))`。

- [ ] **Step 2: `signal_updated` 重命名**

在原有 cache 更新后：

```js
if (old_name && old_name !== signal.name) {
  const ui = useUiStore()
  if (this.selectedMsgId === msg_id && ui.selectedSignalName === old_name) {
    ui.selectSignal(signal.name, { flush: false })
  }
  remapPendingEditTarget(PENDING_EDIT_OWNERS.signalPanel, (t) =>
    t?.msgId === msg_id && t?.signalName === old_name
      ? { ...t, signalName: signal.name } : t
  )
}
```

- [ ] **Step 3: `signal_deleted` 取消**

```js
const ui = useUiStore()
cancelPendingEdit(PENDING_EDIT_OWNERS.signalPanel, (t) =>
  t?.msgId === msg_id && t?.signalName === signal_name
)
if (ui.selectedSignalName === signal_name) {
  ui.clearSignalSelection({ discard: true })
}
```

- [ ] **Step 4: `message_updated` 改 id 时 remap**

在 `if (this.selectedMsgId === oldId) this.selectedMsgId = m.id` 之后，对 `messagePanel` 与 `signalPanel` 都执行：

```js
remapPendingEditTarget(owner, (t) => t?.msgId === oldId ? { ...t, msgId: m.id } : t)
```

- [ ] **Step 5: `message_deleted` 取消**

```js
const ui = useUiStore()
cancelPendingEdit(PENDING_EDIT_OWNERS.messagePanel, (t) => t?.msgId === deletedId)
cancelPendingEdit(PENDING_EDIT_OWNERS.signalPanel, (t) => t?.msgId === deletedId)
if (this.selectedMsgId === deletedId) {
  this.selectedMsgId = null
  ui.clearSignalSelection({ discard: true })
}
delete this.messageCache[deletedId]
ui.closeMessageTab(deletedId, { discard: true })
```

- [ ] **Step 6: `value_table_renamed` / `value_table_deleted`**

重命名（保留原有 valueTables 搬移与 messageCache 级联）：

```js
const ui = useUiStore()
if (ui.selectedVtName === old_name) ui.selectValueTable(new_name, { flush: false })
remapPendingEditTarget(PENDING_EDIT_OWNERS.valueTablePanel, (t) =>
  t?.vtName === old_name ? { ...t, vtName: new_name } : t
)
remapPendingEditTarget(PENDING_EDIT_OWNERS.signalPanel, (t) =>
  t?.valueTableName === old_name ? { ...t, valueTableName: new_name } : t
)
```

删除：

```js
delete this.valueTables[name]
cancelPendingEdit(PENDING_EDIT_OWNERS.valueTablePanel, (t) => t?.vtName === name)
cancelPendingEdit(PENDING_EDIT_OWNERS.signalPanel, (t) => t?.valueTableName === name)
if (useUiStore().selectedVtName === name) {
  useUiStore().selectValueTable(null, { flush: false })
}
```

- [ ] **Step 7: clipboard 粘贴报文前 flush**

`pasteMessages()` 校验完剪贴板后、进入循环前调用 `flushPendingEdit()`（新增同名 import）。循环内 `editor.selectedMsgId = msg.id` 保留。

- [ ] **Step 8: fileOperations 重置前 cancel**

新增 `import { cancelAllPendingEdits } from '../composables/pendingEdit.js'`；在 `loadHistoryFile`、`importFile`、`newFile` 中 `editor.selectedMsgId = null` 之前调用 `cancelAllPendingEdits()`。

- [ ] **Step 9: 测试与构建**

Run: `cd frontend && node --test "src/**/__tests__/*.test.js" && npm run build`
Expected: 全量测试通过，构建成功。

- [ ] **Step 10: 手动 smoke（服务端事件）**

1. 编辑信号 A 时另一客户端删除 A：不写错目标，面板清空。
2. 编辑信号 A 时另一客户端重命名 A：选中跟随新名字。
3. 编辑报文 A 时另一客户端改 id：选中跟随新 id。
4. 编辑值描述表 A 时另一客户端重命名：选中跟随新表名。
5. 编辑中撤销/重做：不产生错目标提交。
6. 复制报文后粘贴：粘贴前的编辑已落到旧目标。

- [ ] **Step 11: Commit**

```bash
git add frontend/src/stores/coreStore.js frontend/src/stores/clipboard.js frontend/src/stores/fileOperations.js
git commit -m "fix(sync): cancel or remap pending edits on server events"
```

---

## Task 7: 删除旧 helper、约定文档、源码扫描测试

**Files:**
- Delete: `frontend/src/composables/commitPendingEdit.js`
- Delete: `frontend/src/composables/__tests__/commitPendingEdit.test.js`
- Create: `frontend/src/utils/__tests__/selectionMutations.test.js`
- Create: `docs/frontend-editing-conventions.md`

- [ ] **Step 1: 删除旧 helper 与测试**

```bash
git rm frontend/src/composables/commitPendingEdit.js frontend/src/composables/__tests__/commitPendingEdit.test.js
grep -rn "commitPendingEdit" frontend/src || true
```
Expected: grep 无输出。

- [ ] **Step 2: 源码扫描测试 `frontend/src/utils/__tests__/selectionMutations.test.js`**

```js
import { test } from 'node:test'
import assert from 'node:assert'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const componentDir = join(dirname(fileURLToPath(import.meta.url)), '../../components')
const files = readdirSync(componentDir).filter(f => f.endsWith('.vue'))

const FORBIDDEN = [
  { pattern: /\.selectedSignalName\s*=(?!=)/, hint: 'ui.selectSignal() 或 ui.clearSignalSelection()' },
  { pattern: /\.selectedVtName\s*=(?!=)/, hint: 'ui.selectValueTable()' },
  { pattern: /\.selectedMsgId\s*=(?!=)/, hint: 'messages.selectMessage()' },
]

test('组件不得直接赋值选中状态', () => {
  const offenders = []
  for (const file of files) {
    const source = readFileSync(join(componentDir, file), 'utf8')
    for (const { pattern, hint } of FORBIDDEN) {
      const match = source.match(pattern)
      if (match) offenders.push(`${file}: "${match[0]}" — 请使用 ${hint}`)
    }
  }
  assert.deepEqual(offenders, [])
})
```

- [ ] **Step 3: 约定文档 `docs/frontend-editing-conventions.md`**

内容必须覆盖：

- 提交只认开始编辑时的目标；禁止在 blur / 异步回调里读全局选中。
- 异步流程在第一个 `await` 前取快照，`await` 后只用快照。
- 选中变更必须走 `ui.selectSignal` / `ui.clearSignalSelection` / `ui.selectValueTable` / `messages.selectMessage`；Tab 与布局走对应 action。
- 服务端删除用 `cancelPendingEdit`，重命名/改 id 用 `remapPendingEditTarget`，全量同步 / undo / redo 用 `cancelAllPendingEdits`。
- 新增面板的三步接入：`usePanelEdit(owner, getTarget)`、根节点 `@focusin="edit.begin"`、提交时 `edit.commit((target) => ...)`。
- 源码扫描测试的位置与作用。

- [ ] **Step 4: 源码扫描测试**

Run: `cd frontend && node --test src/utils/__tests__/selectionMutations.test.js`
Expected: PASS

- [ ] **Step 5: 全量测试与构建**

Run: `cd frontend && node --test "src/**/__tests__/*.test.js" && npm run build`
Expected: 全量测试通过（含 pendingEdit 9 个、selectionMutations 1 个），构建成功。

- [ ] **Step 6: Commit**

```bash
git add docs/frontend-editing-conventions.md frontend/src/utils/__tests__/selectionMutations.test.js
git add -u frontend/src/composables/commitPendingEdit.js frontend/src/composables/__tests__/commitPendingEdit.test.js
git commit -m "chore(edit): document commit conventions and enforce selection actions"
```

---

## 最终验收

自动：

```bash
cd frontend
node --test "src/**/__tests__/*.test.js"
npm run build
```

手动：

1. 信号 A 改 factor 后点击 B：A 变化，B 不变。
2. 信号 A 改 name 后点击 B：A 重命名，B 不变。
3. Motorola A 改起始位后点击 B：转换使用 A 的 length/order。
4. 报文 A 改 name 后点击报文 B：A 变化。
5. 值描述表 A 改条目后点击表 B：A 变化。
6. 新建值描述表输入名称后点击另一个信号：引用落在原信号。
7. 编辑中被其他客户端删除当前信号：不写错目标。
8. 编辑中点 Tab/关闭 Tab：提交到原目标。
9. 编辑中撤销/重做：不产生错目标提交。
10. 三个列表方向键导航：焦点不丢失。