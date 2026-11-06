# 统一编辑提交机制（Pending Edit + Selection Actions）设计

- 日期：2026-11-06
- 状态：已确认，待实施
- 相关背景：修复“右侧面板编辑后切换左侧选中项，值被写到新选中项”的一类问题

## 1. 背景与意图

### 1.1 问题现象

在信号列表选中信号 A，在右侧属性面板修改字段后，直接左键点击信号 B：

- 新值被写到 B 上；
- A 不变；
- 其他信号不受影响。

报文属性面板、值描述表面板存在同类问题。

### 1.2 根因

提交发生在 `blur` 或异步回调中，提交时才解析“当前选中项”：

```text
mousedown（列表 handler 先把 selectedSignalName 改为 B）
  → 浏览器移动焦点
  → 面板输入框 blur
  → blur handler 读取 selectedSignalName，得到 B
  → edit_signal { sig_name: "B", field, value }
```

`v-lazy-value` 在输入框聚焦时不回写 DOM，因此用户输入的内容仍然保留，随后被提交给新选中项。

### 1.3 已有临时加固

已新增 `frontend/src/composables/commitPendingEdit.js`，在三个列表的 `handleRowMouseDown` 中于切换选中前主动 blur 侧栏输入框。

它解决了同步 `mousedown` 路径，但：

- 不覆盖异步提交（`SignalPanel.confirmNewVt()` 在 `await` 之后才读选中项）；
- 依赖每个列表手动调用；
- 无法约束以后新增的面板。

### 1.4 本次目标

采用方案 B：**中心 pending-edit 注册表 + 选中动作统一入口**。

把两个责任分开：

- 选中动作：任何切换前统一 flush 当前编辑；
- 编辑目标：面板在开始编辑时快照目标，提交只认快照，不再读全局选中。

即使以后某个面板忘了使用目标快照，只要它的选中切换走统一 action，同步 blur 提交仍会落到旧目标上。

## 2. 目标与非目标

### 目标

- 信号、报文、值描述表、Tab/布局切换，全部通过统一 action 修改选中。
- 所有面板的 blur/异步提交使用显式目标快照。
- 服务端删除/重命名事件有明确的 cancel 或 remap 策略。
- 新增面板有固定接入方式，并有测试约束。
- 修复现有三类面板的全部同类提交路径。

### 非目标

- 不修改后端协议。
- 不重构表格单元格编辑；它们已经使用行作用域目标（`sig.name` / `m.id` / 表名）。
- 不引入组件测试框架。
- 不改变现有 UI 交互。

## 3. 核心组件

### 3.1 `frontend/src/composables/pendingEdit.js`

模块级单例注册表，不依赖 Pinia，避免 store 循环依赖。

建议 API：

```js
beginPendingEdit(owner, target, { cancel } = {})
peekPendingEdit(owner)           // 读取当前编辑目标
takePendingEditTarget(owner)     // 取走并清除
clearPendingEdit(owner)
cancelPendingEdit(owner)
remapPendingEditTarget(owner, mapper)
flushPendingEdit()
usePanelEdit(owner, getTarget)   // 面板接入封装
```

`flushPendingEdit()` 语义：

1. 同步 blur `document.activeElement`（如果是 input/textarea/select）；
2. blur 处理器通过 `takePendingEditTarget` 拿到快照并提交，此时选中项尚未变化；
3. 若 blur 后注册表仍有残留，`cancelPendingEdit` 并仅在 DEV 下 `console.warn`；
4. 不等待网络请求：目标与输入值在选中变化前已经捕获。

`usePanelEdit(owner, getTarget)` 建议返回：

```js
{
  begin(),      // focusin 时快照 getTarget()
  peek(),       // 读当前 active 目标
  take(),       // 取走 active 目标
  clear(),
  cancel(),
  commit(fn),   // take + 调用 fn(target, value)
}
```

面板内“添加/删除条目”这类直接点击立即提交，可以使用 `peek()` 或面板自己的 `current` 目标；blur 与异步流程只使用 `take()` 得到的快照。

### 3.2 选中动作

新增/改造：

```js
// uiStore
selectSignal(name, { flush = true } = {})
selectValueTable(name, { flush = true } = {})
clearSignalSelection({ discard = false } = {})

// messages store
selectMessage(id, { flush = true } = {})
```

所有选中变更前先 flush，再赋值。

Tab/布局相关动作同样处理：

- `switchCenterTab`
- `openMessageTab`
- `activateMessageTab`
- `closeMessageTab`（删除场景传 `discard: true`）
- `toggleLayoutView`

### 3.3 策略矩阵

| 场景 | 行为 |
|---|---|
| 用户点击/键盘切换选中 | flush，再切换 |
| 选中项没变 | 直接返回 |
| 服务端删除当前目标 | cancel，再清空选中 |
| 服务端重命名/改 id | remap 快照 + 更新选中，不 flush |
| undo/redo 状态替换 | cancel 快照，再清理失效选中 |
| 新建报文后自动选中 | flush，再切换 |
| 打开文件/重置会话 | cancel |
| 剪贴板粘贴后切换报文 | flush |

### 3.4 面板接入

每个面板根部 `@focusin="edit.begin"`：

```js
const edit = usePanelEdit('signal-panel', () => ({
  signalName: ui.selectedSignalName,
  msgId: msg.value?.id,
  valueTableName: localValueTableName.value,
}))
```

提交方式：

```js
function updateSignal(field, value) {
  edit.commit((t) => {
    signals.updateSignal(t.signalName, field, value, t.msgId).catch(() => {})
  })
}
```

- `blur`：`take` 快照。
- `@change`（字节序、值描述引用、is_fd）：`peek` + 提交后 `clear`。
- `confirmNewVt`：进入函数先取快照，`await` 之后只用快照；增加重复提交保护，避免 Enter 与 blur 各触发一次。
- 起始位转换：用快照中的 `msgId + signalName` 从 `messageCache` 取原信号的 `length/byte_order`，不再读 `selectedSig`。
- 内联值描述条目：用快照中的 `valueTableName`。
- 表格单元格：保持行作用域目标，不改。

## 4. 现有面板修复清单

### 4.1 `SignalPanel`

- name / start_bit / length / byte_order / factor / offset / min / max / unit / comment；
- 起始位 Motorola 转换；
- 值描述表引用；
- 内联条目；
- `confirmNewVt` 异步提交；
- 信号重命名后让 `selectedSignalName` 跟随新名字，并 remap pending target。

### 4.2 `MessagePanel`

- id / name / dlc / cycle_time / sender / comment；
- is_fd 及其失败回滚；
- 报文 id 变更后 remap pending target。

### 4.3 `ValueTablePanel`

- 重命名；
- 条目编辑；
- 重命名成功后的选中同步；
- 重命名/删除后 remap 或 cancel pending target。

### 4.4 选中入口

- `SignalEditorTab`：mousedown、方向键、清除；
- `SignalLayoutVisualizer`：单元格点击；
- `DataErrorList`：跳转；
- `MessageTab`：选中报文；
- `ValueTableTab`：行选中、新增、删除、方向键；
- `uiStore`：Tab/布局切换；
- `clipboard`：粘贴报文后切换；
- `fileOperations`：重置；
- `coreStore` WS：
  - `signal_updated`（重命名）
  - `signal_deleted`
  - `message_updated`（id 变更）
  - `message_deleted`
  - `value_table_renamed`
  - `value_table_deleted`
  - `undo_applied` / `redo_applied`

### 4.5 清理

删除 `frontend/src/composables/commitPendingEdit.js` 及 `__tests__/commitPendingEdit.test.js`，由 `pendingEdit.js` 和统一选中动作取代。

## 5. 防止以后新增面板再犯

1. 新增 `docs/frontend-editing-conventions.md`，写明：
   - 禁止在 blur/异步提交中读取 `ui.selected*` / `editor.selectedMsgId`；
   - 面板必须用 `usePanelEdit`；
   - 选中变更必须走 `selectSignal / selectMessage / selectValueTable`。
2. 增加源码扫描测试：`src/components/**/*.vue` 中禁止直接赋值
   - `ui.selectedSignalName`
   - `ui.selectedVtName`
   - `store.selectedMsgId`
   - `editor.selectedMsgId`
3. `pendingEdit` 单元测试覆盖：快照、take、cancel、remap、flush 顺序。

## 6. 迁移顺序

1. 新增 `pendingEdit.js` + 单元测试 + 源码扫描测试。
2. `uiStore` / `messages` 增加选中 action，保留旧赋值暂时可用。
3. `SignalPanel` + `SignalEditorTab`。
4. `MessagePanel` + `MessageTab`。
5. `ValueTablePanel` + `ValueTableTab`。
6. `coreStore` WS 事件、剪贴板、文件操作、Tab 切换。
7. 删除旧 helper，补约定文档，跑全量测试和构建。

每一步都执行：

```bash
cd frontend
node --test "src/**/__tests__/*.test.js"
npm run build
```

并做对应面板的手动 smoke。

## 7. 测试与验收

### 自动测试

- `pendingEdit` 单测；
- 组件直接选中赋值扫描测试；
- 现有全量 `node --test`；
- 生产构建。

### 手动验收场景

1. 信号 A 改 factor 后点击 B：A 变化，B 不变。
2. 信号 A 改 name 后点击 B：A 重命名，B 不变。
3. Motorola A 改起始位后点击 B：转换使用 A 的 length/order。
4. 报文 A 改 name 后点击报文 B：A 变化。
5. 值描述表 A 改条目后点击表 B：A 变化。
6. 新建值描述表输入名称后点击另一个信号：引用落在原信号。
7. 编辑中被其他客户端删除当前信号：取消提交，不写错目标。
8. 编辑中点 Tab/关闭 Tab：提交到原目标。
9. 编辑中撤销/重做：不产生错目标提交。

## 8. 默认决定

- `flush` 同步执行，不等待网络；
- 服务端删除走 cancel，用户切换走 flush；
- 表格单元格编辑不变；
- 移除旧 `commitPendingEditOutside`；
- 增加源码扫描测试作为“以后新面板不能绕过”的硬约束。

## 9. 风险与注意事项

- `flushPendingEdit` 会 blur 当前可编辑元素，等价于“用户点击了别处”；选择动作本身都是用户意图，因此可接受。
- 服务端删除/全量同步必须 cancel，否则会把编辑提交到已失效目标。
- 异步提交必须在 `await` 前拿到快照，不能依赖注册表在 await 后仍存在。
- `selectedMsgId` 在 `coreStore`，`selectedSignalName` / `selectedVtName` 在 `uiStore`；`pendingEdit.js` 不能 import 这些 store，避免循环依赖。
- 表格自身的 `commitAndExitEdit` 与统一 flush 可能先后触发，需保证幂等。
- 当前仓库没有组件测试框架，组件接线依赖手动 smoke；纯逻辑用 `node --test`。

## 10. 涉及文件（预估）

新增：

- `frontend/src/composables/pendingEdit.js`
- `frontend/src/composables/__tests__/pendingEdit.test.js`
- `frontend/src/utils/__tests__/selectionMutations.test.js`（源码扫描）
- `docs/frontend-editing-conventions.md`

修改：

- `frontend/src/stores/uiStore.js`
- `frontend/src/stores/messages.js`
- `frontend/src/stores/coreStore.js`
- `frontend/src/stores/clipboard.js`
- `frontend/src/stores/fileOperations.js`
- `frontend/src/stores/undoRedo.js`（如需要）
- `frontend/src/components/SignalPanel.vue`
- `frontend/src/components/MessagePanel.vue`
- `frontend/src/components/ValueTablePanel.vue`
- `frontend/src/components/SignalEditorTab.vue`
- `frontend/src/components/MessageTab.vue`
- `frontend/src/components/ValueTableTab.vue`
- `frontend/src/components/SignalLayoutVisualizer.vue`
- `frontend/src/components/DataErrorList.vue`

删除：

- `frontend/src/composables/commitPendingEdit.js`
- `frontend/src/composables/__tests__/commitPendingEdit.test.js`