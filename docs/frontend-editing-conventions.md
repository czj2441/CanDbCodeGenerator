# 前端编辑提交约定

## 核心规则

1. **提交只认开始编辑时的目标。**
   面板在 `focusin` 时快照目标，`blur` / `@change` 时取走快照提交。
   不要在 blur 处理器或异步回调里读取 `ui.selectedSignalName`、
   `ui.selectedVtName`、`editor.selectedMsgId`。

2. **异步流程必须在第一个 `await` 前取得目标。**
   新建值描述表、重命名、改 id 等操作，`await` 之后只使用快照。

3. **选中变更必须走统一 action。**
   - 信号：`ui.selectSignal(name)` / `ui.clearSignalSelection()`
   - 值描述表：`ui.selectValueTable(name)`
   - 报文：`messages.selectMessage(id)`
   - Tab / 布局：`switchCenterTab` / `openMessageTab` / `activateMessageTab` /
     `closeMessageTab` / `toggleLayoutView`

4. **服务端事件的处理策略。**
   - 删除当前目标：`cancelPendingEdit(...)`，再清空选中。
   - 重命名 / 改 id：`remapPendingEditTarget(...)`，不 flush。
   - 全量同步 / undo / redo：`cancelAllPendingEdits()`。

## 新增面板接入方式

```js
import { usePanelEdit } from '../composables/pendingEdit.js'

const edit = usePanelEdit('my-panel', () => ({
  // 只放定位目标需要的字段
  msgId: msg.value?.id,
  name: ui.selectedSignalName,
}))

function update(field, value) {
  edit.commit((target) => {
    // 只使用 target，不读全局选中
    store.update(target, field, value)
  })
}
```

模板根节点加 `@focusin="edit.begin"`。

## 硬约束

`frontend/src/utils/__tests__/selectionMutations.test.js` 会扫描
`frontend/src/components/**/*.vue`，禁止直接赋值 `selectedSignalName` /
`selectedVtName` / `selectedMsgId`。绕过统一 action 会导致测试失败。