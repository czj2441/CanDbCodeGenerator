# 架构研讨：信号最小绘制对象 → 1-bit 单元格

## 核心原则

```
只有报文框架（网格）才做坐标计算
信号只关心 bit 编号，不关心像素
```

---

## 一、当前代码中坐标计算的分布

### A. 报文框架坐标（保留，正确）

这些是网格自身的坐标计算，属于"报文框架"层：

```
cellToPixel(row, col) → { x: labelWidth + col * cellSize, y: headerH + row * cellSize }
```

出现在：
| 位置 | 计算内容 | 性质 |
|------|---------|------|
| 列头 `v-text` | `x: labelWidth + (cols-1-c) * cellSize` | 框架 |
| 行头 `v-text` | `y: headerH + r * cellSize` | 框架 |
| 网格线 `v-line` | `points` 中行列坐标转像素 | 框架 |
| bit 编号 `v-text` | 同上 | 框架 |
| DLC 边界 `v-rect` | `y: headerH + dlcBytes * cellSize` | 框架 |
| `stageConfig` | `baseW/baseH * scale` | 框架 |
| ResizeObserver | `containerWidth/Height` | 框架 |

### B. 信号层坐标计算（全部需要删除）

这些是"以信号为单位"的坐标计算，违反方格原则：

| 位置 | 代码 | 问题 |
|------|------|------|
| `signalToRenderData()` L318 | `groupX = labelWidth + minCol * cellSize` | 为信号计算包围盒左上角像素 |
| `signalToRenderData()` L319 | `groupY = headerH + minRow * cellSize` | 同上 |
| `signalToRenderData()` L321-329 | `rect.x = (colStart - minCol) * cellSize` | 为信号内部 rect 计算相对坐标 |
| `signalToRenderData()` L332-337 | `label.x = -labelWidth` | 标签相对 group 的偏移 |
| 模板 L113 | `x: dragOverrides[sg.uuid]?.x ?? sg.groupX` | 信号 Group 的像素位置 |
| 模板 L114 | `y: dragOverrides[sg.uuid]?.y ?? sg.groupY` | 同上 |
| 模板 L124 | `x: rect.x` | 信号 rect 相对坐标 |
| 模板 L125 | `y: rect.y` | 同上 |
| 模板 L126 | `width: rect.width` | 同上 |
| 模板 L136-142 | `sg.label.x/y/width` | 标签相对坐标 |

### C. 拖拽层坐标计算（全部需要删除/重写）

| 位置 | 代码 | 问题 |
|------|------|------|
| `snapDragBound()` L333 | `snapDragBound` 为信号 group 计算吸附像素位置 | 信号不应有像素位置 |
| `snapDragBound()` L337-338 | `dragOverrides[sg.uuid] = snapped` | 存储信号像素偏移 |
| `computeNewBit()` L323 | `pixelToGridCell(posX, posY)` | 从信号 group 坐标反推 bit |
| `computeNewBit()` L324-325 | `_meta.minCol/startCell` 偏移计算 | 信号包围盒偏移 |
| `bindDragBounds()` | watch + nextTick + getNode + dragBoundFunc | Konva 拖拽绑定 |

---

## 二、目标架构

### 分层

```
┌──────────────────────────────────────────────┐
│  报文框架层 (Grid Framework)                   │
│  职责: 网格绘制、缩放、像素↔网格转换            │
│                                               │
│  cellPixel(row, col) → {x, y}                │
│  pixelCell(x, y) → {row, col}                │
│  bitAtCell(row, col) → bit                   │
│  cellAtBit(bit) → {row, col}                 │
│                                               │
│  这层是唯一做坐标计算的地方                      │
└──────────────────────────────────────────────┘
          ▲ 提供坐标              ▲ 提供转换
          │                      │
┌─────────┴──────────────────────┴──────────────┐
│  信号着色层 (Signal Shading)                    │
│  职责: 决定每个方格的颜色和标签                   │
│                                               │
│  cellMap: Map<bit, {uuid, name, color}>       │
│  coloredCells: [{row, col, color, ...}]       │
│  signalLabels: [{row, col, span, text}]       │
│                                               │
│  这层不做坐标计算，只产出"哪个格子→什么样式"       │
│  像素坐标由模板层通过 cellPixel() 查表获得        │
└──────────────────────────────────────────────┘
          ▲
          │ 读写
          │
┌─────────┴──────────────────────────────────────┐
│  交互层 (Interaction)                           │
│  职责: 拖拽 = 从哪个bit → 到哪个bit              │
│                                               │
│  onMouseDown → pixelCell → bit → cellMap[bit] │
│  onMouseUp   → pixelCell → bit → computeNew   │
│              → store.moveSignalByLayout        │
│                                               │
│  只在入口处调用一次 pixelCell()，                  │
│  其余全是 bit 层面的运算                          │
└──────────────────────────────────────────────┘
```

### 信号数据流（关键变化）

```
旧: signal → signalToRenderData → {groupX, groupY, rects[{x,y,w,h}], label{x,y}}
     ↓
    模板直接用这些像素坐标渲染 Group+Rect

新: signal → getSignalBits → Set<bit>
     ↓
    cellMap: bit → {row, col, color, name}   ← 只有网格坐标，没有像素
     ↓
    模板: v-for cell in coloredCells
           x = labelWidth + cell.col * cellSize   ← 像素计算在这里，一行公式
           y = headerH + cell.row * cellSize
```

### 拖拽数据流（网格坐标偏移, 适用于 Intel 和 Motorola）

```
旧: mousedown → Konva dragstart → snapDragBound(每像素调用) → 计算信号 group 吸附像素
                                              ↓
    mouseup   → computeNewBit(从 group 像素反推) → _meta 偏移修正 → store

新: mousedown → stage.getPointerPosition() → pixelCell(mouse) → (row, col) → bit
              → bitToGridCell(sig.startBit) → (startRow, startCol)
              → offsetRow = grabRow - startRow
              → offsetCol = grabCol - startCol
              → dragState = { uuid, sigStartBit, sigLength, sigByteOrder, offsetRow, offsetCol }

    mouseup   → stage.getPointerPosition() → pixelCell(mouse) → (dropRow, dropCol)
              → targetStartRow = dropRow - offsetRow
              → targetStartCol = dropCol - offsetCol
              → targetStartBit = gridCellToBit(targetStartRow, targetStartCol)
              → newStartBit = clampStartBit(targetStartBit, sigLength, sigByteOrder, maxBit)
              → store.moveSignalByLayout(uuid, newStartBit)
              → cellMap 自动更新（computed 重新计算）
```

关键：Intel 信号 bits 是线性的所以 `grabBit - startBit` 碰巧等于网格偏移，但 Motorola 的 zigzag 排列中 bit 编号不规则。统一使用网格坐标偏移 `(offsetRow, offsetCol)` 对两种字节序都正确。

---

## 三、完整实施代码

### 3.0 导入变更

```js
// 旧
import { getSignalColor, gridCellToBit, clampStartBit, signalToRenderData, pixelToGridCell } from '../utils/signalLayout.js'

// 新（删除 signalToRenderData）
import { getSignalBits, bitToGridCell, gridCellToBit, pixelToGridCell, clampStartBit, getSignalColor } from '../utils/signalLayout.js'
```

### 3.1 布局常量（新增 `rowIndices`、`colIndices`）

```js
// ── Layout constants ──
const cellSize = 36
const headerH = 32
const labelWidth = 44
const cols = 8
const rows = 8  // CAN 最大字节数

const baseW = labelWidth + cols * cellSize + 1
const baseH = headerH + rows * cellSize + 1

// 0-based 索引数组（修复 v-for="n in N" 的 1-index 陷阱）
const colIndices = Array.from({ length: cols }, (_, i) => i)    // [0,1,2,3,4,5,6,7]
const rowIndices = Array.from({ length: rows }, (_, i) => i)    // [0,1,2,3,4,5,6,7]
```

### 3.2 模板 — gridLayer（修复 v-for 1-index + 拆分为两层）

```html
<v-stage ref="stage" :config="stageConfig" @mouseup="onStageMouseUp">
  <!-- 网格背景层：表头背景、DLC 遮罩、bit 编号 -->
  <v-layer ref="gridBgLayer">
    <!-- 列头背景 -->
    <v-rect :config="{
      x: labelWidth, y: 0, width: cols * cellSize, height: headerH,
      fill: gridHeaderFill, stroke: gridStroke, strokeWidth: 1, listening: false,
    }" />
    <!-- 列头标签：bit 7..0（0-based: i=0→显示7, x在col=0位置） -->
    <v-text
      v-for="i in colIndices" :key="'ch-' + i"
      :config="{
        x: labelWidth + i * cellSize, y: 0,
        width: cellSize, height: headerH,
        text: String(7 - i),
        align: 'center', verticalAlign: 'middle',
        fill: textDim, fontSize: 11, fontStyle: 'bold', listening: false,
      }"
    />
    <!-- 行头背景 -->
    <v-rect :config="{
      x: 0, y: headerH, width: labelWidth, height: rows * cellSize,
      fill: gridHeaderFill, stroke: gridStroke, strokeWidth: 1, listening: false,
    }" />
    <!-- 行头标签：byte 0..N -->
    <v-text
      v-for="r in rowIndices" :key="'rl-' + r"
      :config="{
        x: 0, y: headerH + r * cellSize,
        width: labelWidth - 4, height: cellSize,
        text: String(r),
        align: 'right', verticalAlign: 'middle',
        fill: textDim, fontSize: 11, listening: false,
      }"
    />
    <!-- DLC 边界 -->
    <v-rect
      v-if="dlcBytes < rows"
      :config="{
        x: labelWidth, y: headerH + dlcBytes * cellSize,
        width: cols * cellSize, height: (rows - dlcBytes) * cellSize,
        fill: oobFill, listening: false,
      }"
    />
    <!-- 单元格 bit 编号 -->
    <template v-for="r in rowIndices" :key="'bnr-' + r">
      <v-text
        v-for="c in colIndices" :key="'bn-' + r + '-' + c"
        :config="{
          x: labelWidth + c * cellSize + 2,
          y: headerH + r * cellSize + cellSize - 12,
          text: String(r * 8 + (7 - c)),
          fontSize: 9, fill: textDim, fontStyle: 'bold',
          align: 'left', verticalAlign: 'bottom', listening: false,
        }"
      />
    </template>
  </v-layer>

  <!-- 信号着色层 -->
  <v-layer ref="signalLayer">
    <!-- 着色方格 -->
    <v-rect
      v-for="cell in coloredCells" :key="'c-' + cell.bit"
      :config="{
        x: labelWidth + cell.col * cellSize,
        y: headerH + cell.row * cellSize,
        width: cellSize, height: cellSize,
        fill: cell.color,
        stroke: cell.hasError ? 'oklch(0.60 0.20 25)' : cell.color,
        strokeWidth: cell.hasError ? 2 : 1,
        cornerRadius: 2,
      }"
      @mousedown="(e) => onCellMouseDown(cell, e)"
      @click="() => onCellClick(cell)"
    />
    <!-- 信号名标签 -->
    <v-text
      v-for="lbl in signalLabels" :key="'lbl-' + lbl.uuid"
      :config="{
        x: labelWidth + lbl.col * cellSize,
        y: headerH + lbl.row * cellSize,
        text: lbl.text,
        width: lbl.span * cellSize,
        height: cellSize,
        fontSize: Math.min(12, cellSize - 10),
        fill: textPrimary, fontStyle: 'bold',
        align: 'center', verticalAlign: 'middle', listening: false,
      }"
    />
    <!-- 选中信号高亮边框 -->
    <v-rect
      v-for="cell in selectedCells" :key="'sel-' + cell.bit"
      :config="{
        x: labelWidth + cell.col * cellSize,
        y: headerH + cell.row * cellSize,
        width: cellSize, height: cellSize,
        fill: 'transparent',
        stroke: 'oklch(0.60 0.18 260)',
        strokeWidth: 2,
        listening: false,
      }"
    />
  </v-layer>

  <!-- 网格线层（最顶层，始终可见） -->
  <v-layer ref="gridLineLayer">
    <v-line
      v-for="r in Array.from({ length: rows + 1 }, (_, i) => i)" :key="'h-' + r"
      :config="{
        points: [labelWidth, headerH + r * cellSize, labelWidth + cols * cellSize, headerH + r * cellSize],
        stroke: gridLineStroke, strokeWidth: 1, listening: false,
      }"
    />
    <v-line
      v-for="c in Array.from({ length: cols + 1 }, (_, i) => i)" :key="'v-' + c"
      :config="{
        points: [labelWidth + c * cellSize, headerH, labelWidth + c * cellSize, headerH + rows * cellSize],
        stroke: gridLineStroke, strokeWidth: 1, listening: false,
      }"
    />
  </v-layer>
</v-stage>
```

### 3.3 脚本 — computed（完整实现）

```js
// ── 删除以下全部： ──
// const layoutSignals = computed(...)     — 替换为 cellMap 系列
// const dragOverrides = reactive({})       — 不再需要
// const groupRefs = {}; function setGroupRef(...) — 不再需要
// function bindDragBounds()                — 不再需要
// watch(layoutSignals, () => nextTick(...)) — 不再需要
// function snapDragBound(...)              — 不再需要
// function computeNewBit(...)              — 重写
// function onDragStart(...) / onDragEnd(...) — 重写
// function selectSignal(...)               — 简化为 onCellClick
// const transformer = ref(null)            — 不再需要
// const signalLayer = ref(null)            — 保留（可能有其他用途）或删除
// watch store.selectedMsgId → clear        — 保留

// ── 新增 4 个 computed ──

// cellMap: bit → { uuid, name, color, hasError, row, col, byteOrder, isStartBit }
// 遍历所有信号的 getSignalBits，构建 bit 到信号信息的映射
const cellMap = computed(() => {
  const map = {}  // key: bit number (string or number), value: cell info
  if (!msg.value) return map
  const dlc = dlcBytes.value
  const maxBit = dlc * 8 - 1
  const errUuids = new Set(
    store.signalErrors.flatMap(e => [e.signal_uuid, e.conflicts_uuid].filter(Boolean))
  )

  msg.value.signals.forEach((sig, idx) => {
    const color = getSignalColor(idx)
    const hasError = errUuids.has(sig.uuid)
    const bits = getSignalBits(sig.start_bit, sig.length, sig.byte_order)

    for (const bit of bits) {
      if (bit < 0 || bit > maxBit) continue
      const { row, col } = bitToGridCell(bit)
      // 后面遍历的信号覆盖前面的（重叠时最后画的那个在上面）
      map[bit] = {
        bit, row, col,
        uuid: sig.uuid,
        name: sig.name,
        color,
        hasError,
        isStartBit: bit === sig.start_bit,
        byteOrder: sig.byte_order,
        startBit: sig.start_bit,
        length: sig.length,
      }
    }
  })
  return map
})

// coloredCells: 所有被信号占用的方格
const coloredCells = computed(() => Object.values(cellMap.value))

// signalLabels: 每个信号一个标签，放在 start_bit 方格上
// span = 同行中连续同信号格子数（从 start_bit 列向右扩展）
const signalLabels = computed(() => {
  const map = cellMap.value
  if (Object.keys(map).length === 0) return []

  // 按 uuid 分组
  const byUuid = {}
  for (const cell of Object.values(map)) {
    if (!byUuid[cell.uuid]) byUuid[cell.uuid] = []
    byUuid[cell.uuid].push(cell)
  }

  const labels = []
  for (const [uuid, cells] of Object.entries(byUuid)) {
    // 找到 start_bit 方格
    const startCell = cells.find(c => c.isStartBit) || cells[0]
    // 计算同行中连续同信号格子的 span
    const sameRow = cells
      .filter(c => c.row === startCell.row && c.col >= startCell.col)
      .map(c => c.col)
      .sort((a, b) => a - b)

    let span = 1
    for (let c = startCell.col + 1; sameRow.includes(c); c++) {
      span++
    }
    labels.push({
      uuid,
      row: startCell.row,
      col: startCell.col,
      span,
      text: cells[0].name,
    })
  }
  return labels
})

// selectedCells: 选中信号的所有方格（高亮边框）
const selectedCells = computed(() => {
  if (!store.selectedSignalUuid) return []
  return coloredCells.value.filter(c => c.uuid === store.selectedSignalUuid)
})
```

### 3.4 脚本 — 拖拽交互（完整实现）

#### Motorola 拖拽偏移的关键问题

Intel 信号：`getSignalBits(start, len, 'little_endian')` 返回 `{start, start+1, ..., start+len-1}`
- 线性关系：`grabBit - sigStartBit` 能正确表示"拖拽点相对信号起点的偏移"

Motorola 信号：`getSignalBits(start, len, 'big_endian')` 返回 zigzag 排列
- **`grabBit - sigStartBit` 作为偏移是错误的** — bit 编号不连续
- 必须在**网格坐标**下计算偏移：`(grabRow - startRow, grabCol - startCol)`
- 然后在目标位置应用相同网格偏移，反推新 start_bit

```js
// 拖拽状态（纯数据，不涉及像素坐标）
const dragState = ref(null)

// 鼠标按下：记录拖拽起点，选中信号
function onCellMouseDown(cell, konvaEvent) {
  // 阻止 Konva 默认行为
  konvaEvent?.evt?.preventDefault?.()

  const { row: startRow, col: startCol } = bitToGridCell(cell.startBit)
  const { row: grabRow, col: grabCol } = bitToGridCell(cell.bit)

  dragState.value = {
    uuid: cell.uuid,
    sigStartBit: cell.startBit,
    sigLength: cell.length,
    sigByteOrder: cell.byteOrder,
    // 网格坐标偏移：拖拽点相对信号 start_bit 的可视偏移
    offsetRow: grabRow - startRow,
    offsetCol: grabCol - startCol,
  }

  // 选中该信号
  store.selectLayoutSignal(cell.uuid)
}

// 单击：切换选中
function onCellClick(cell) {
  if (dragState.value) return  // 拖拽中，忽略 click
  store.selectLayoutSignal(cell.uuid)
}

// 鼠标松开：计算新 start_bit 并更新
function onStageMouseUp() {
  if (!dragState.value) return

  const stage = stageRef.value?.getNode()
  if (!stage) { dragState.value = null; return }

  const pos = stage.getPointerPosition()
  // getPointerPosition() 返回逻辑坐标（已含 scale 变换）
  const { row: dropRow, col: dropCol } = pixelToGridCell(pos.x, pos.y, {
    labelWidth, headerH, cellSize,
  })

  const ds = dragState.value
  dragState.value = null

  // 在网格坐标下计算目标 start_bit
  const targetStartRow = dropRow - ds.offsetRow
  const targetStartCol = dropCol - ds.offsetCol
  const targetStartBit = gridCellToBit(
    Math.max(0, targetStartRow),
    Math.max(0, Math.min(cols - 1, targetStartCol))
  )

  const maxBit = dlcBytes.value * 8 - 1
  const newStartBit = clampStartBit(targetStartBit, ds.sigLength, ds.sigByteOrder, maxBit)

  if (newStartBit < 0 || newStartBit === ds.sigStartBit) return

  store.moveSignalByLayout(ds.uuid, newStartBit)
}
```

**为什么网格坐标偏移适用于 Intel 和 Motorola：**

Intel 信号 start_bit=16, length=8 → bits=[16,17,18,19,20,21,22,23]
- startCell = bitToGridCell(16) = {row:2, col:7}
- 用户抓取 bit 20 → grabCell = {row:2, col:3}
- offset = (0, -4)
- 松在 (row:3, col:2) → targetStart = (3-0, 2-(-4)) = (3, 6) → bit 30
- newStartBit = clampStartBit(30, 8, 'little_endian', 63) = 30 ✓

Motorola 信号 start_bit=7, length=16 → bits=[7,6,5,4,3,2,1,0,15,14,13,12,11,10,9,8]
- startCell = bitToGridCell(7) = {row:0, col:0}（最右列）
- 用户抓取 bit 0 → grabCell = {row:0, col:7}（最左列）
- offset = (0, 7)
- 松在 (row:2, col:0) → targetStart = (2-0, 0-7) = (2, -7) → clamp → gridCellToBit(2, 0) = bit 23
- clampStartBit(23, 16, 'big_endian', 63) = 23 ✓

### 3.5 脚本 — 选中状态管理（保留/修改）

```js
// 删除: transformer ref, selectSignal()（旧的 Transformer 方式）
// 删除: watch(store.selectedMsgId, ...) 中 transformer 相关代码

// 保留: watch selectedMsgId → 清除 selectedSignalUuid
watch(() => store.selectedMsgId, () => {
  store.selectedSignalUuid = null
})
```

### 3.6 脚本 — 删除的响应式绑定

```js
// 删除整个 onMounted 中的 nextTick(bindDragBounds)
// 删除整个 watch(layoutSignals, ...)
//
// onMounted 现在只需要 ResizeObserver
onMounted(() => {
  if (!canvasWrap.value) return
  resizeObserver = new ResizeObserver(([entry]) => {
    const { width, height } = entry.contentRect
    containerWidth.value = width - 16
    containerHeight.value = height - 16
  })
  resizeObserver.observe(canvasWrap.value)
})
```

### 3.7 `signalLayout.js` — 不修改

所有现有函数保留（测试仍在用）。测试中引用的 `signalToRenderData` 仍然可用，只是组件不再调用它。

### 3.8 `editor.js` — 不修改

`moveSignalByLayout(uuid, newStartBit)` 和 `selectLayoutSignal(uuid)` 保持原样。

---

## 四、网格框架 Bug：Vue 3 `v-for="n in N"` 1-index 陷阱

### 问题根源

Vue 3 中 `v-for="c in cols"`（`cols=8`）迭代的是 `c = 1, 2, ..., 8`，**不是** `0, 1, ..., 7`。

所有使用 `v-for="x in N"` 的网格元素都存在这个系统性偏移。

### 逐项排查

#### 4.1 列头比特号 (bit 7..0)

```html
<v-text v-for="c in cols" :config="{ text: String(c), x: labelWidth + (cols - 1 - c) * cellSize }" />
```

| c | 显示文本 | x 对应的格子 | 应该显示 |
|---|---------|-------------|---------|
| 1 | "1" | col=6 (bit 1) | "7" |
| 2 | "2" | col=5 (bit 2) | "6" |
| 7 | "7" | col=0 (bit 7) | "1" |
| 8 | "8" | col=-1 (**超出画布**) | "0" |

**bit 0 列没有标签，bit 标签全部错位，且第 8 个标签溢出画布。**

#### 4.2 单元格内比特编号

```html
<v-text v-for="c in cols" :config="{ text: String(r * 8 + c), x: labelWidth + (cols - 1 - c) * cellSize }" />
```

r=0 行：
- c=1: 显示 "1" → 实际 bit 0 位置 → **应该是 "0"**
- c=8: 显示 "8" → 实际 bit 7 位置 → **应该是 "7"**

r=1 行：
- c=1: 显示 "9" → 实际 bit 8 位置 → **应该是 "8"**

所有单元格比特编号整体 +1 偏移。

#### 4.3 行头字节号 (byte 0..N)

```html
<v-text v-for="r in rows" :config="{ text: String(r), y: headerH + r * cellSize }" />
```

| r | 显示 | y 位置 | 实际对应行 |
|---|------|--------|----------|
| 1 | "1" | headerH + 36 | byte 0 (第1行) |
| 8 | "8" | headerH + 288 | byte 7 (第8行) |

行标签整体下移一行。**byte 0 没有标签，byte 7 的标签在正确位置但显示为 "8"。**

#### 4.4 网格线

```html
<v-line v-for="r in rows + 1" :config="{ points: [labelWidth, headerH + r * cellSize, ...] }" />
```

| r | y = headerH + r*cellSize | 期望 |
|---|--------------------------|------|
| 0 | **未生成** | 网格顶部边框 |
| 1 | headerH + 36 | 字节 0/1 分隔 |
| ... | ... | ... |
| 8 | headerH + 288 | 网格底部边框 |
| 9 | headerH + 324 | **多余一条** |

**顶部边框缺失，底部多余一条越界横线。**

#### 4.5 为什么 bug 之前被掩盖

`signalToRenderData` 调用 `bitToGridCell(bit)` 返回正确的 0-based `{row, col}`：

```js
// signalLayout.js - 这个是 0-based，正确的
export function bitToGridCell(bit) {
  return { row: Math.floor(bit / 8), col: 7 - (bit % 8) }
}
```

而 gridLayer 的 v-for 使用的 c 是 1-based。

结果：信号着色块位置"看起来"对（因为用正确坐标），但网格标签全是错的。两套坐标系统不一致，只是因为用户注意力在信号块上，才没注意到网格框架标记已经偏了。

更危险的是：**列头 `cols - 1 - c` 在 c=8 时产生 `cols - 9 = -1`**，即 `x = labelWidth - cellSize`，这个标签溢出到画布左侧，可能被 label 区域遮挡或在极端情况引发视觉异常。

### 4.6 修复方案

将 `v-for="x in N"` 改为 `v-for="(_, x) in Array(N)"`（`_` 是数组元素值，`x` 是 0-based index）：

```html
<!-- 旧：c = 1..8 -->
<v-text v-for="c in cols" :config="{ text: String(c), x: labelWidth + (cols - 1 - c) * cellSize }" />

<!-- 新：使用 Array(N) → 元素为 undefined, 索引 i = 0..7 -->
<v-text v-for="(_, i) in Array(cols)" :key="'ch-' + i"
  :config="{
    x: labelWidth + (cols - 1 - i) * cellSize,
    text: String(7 - i),
    ...
  }"
/>
```

更清晰的写法 — 用 computed 生成索引数组：

```js
const colIndices = computed(() => Array.from({ length: cols }, (_, i) => i))
const rowIndices = computed(() => Array.from({ length: rows }, (_, i) => i))
```

完整修复映射表：

| 元素 | 变更为 |
|------|--------|
| 列头 bit 标签 | `v-for="(_, c) in Array(cols)"` → text: `String(7 - c)` |
| 行头 byte 标签 | `v-for="r in rowIndices"` → 保持 0-based |
| 单元格 bit 编号 | `v-for="(_, c) in Array(cols)"` → text: `String(r * 8 + (7 - c))` |
| 水平网格线 | `v-for="(_, r) in Array(rows + 1)"` → r=0..8 (8条线 = 8+1) |
| 垂直网格线 | `v-for="(_, c) in Array(cols + 1)"` → c=0..8 |
| stage 高度 | 用 `baseH = headerH + rows * cellSize` 不变，但 rows=8 正确 |

### 4.7 网格线覆盖问题

在旧架构中，网格线在 `gridLayer`，信号着色块在 `signalLayer`。`signalLayer` 渲染在 `gridLayer` 之上，所以着色块会遮盖网格线。

dbcUtility 的做法：先画信号着色块，最后在所有内容之上重绘一层网格线。

新架构需要在三层 Konva Layer：

```
v-stage
  ├── v-layer ref="gridBgLayer"      // 列头背景、行头背景、DLC 边界（不透明）
  ├── v-layer ref="signalLayer"      // 信号着色方格、标签、选中高亮
  └── v-layer ref="gridLineLayer"    // 网格线（始终在最顶层可见）
```

或者更简单：不拆分，gridLayer 中的网格线移除，在 signalLayer 之后单独一个 layer 画网格线。

### 4.8 其他实施注意事项

**stage 事件绑定**：拖拽必须监听 stage 级别的 `mouseup`，不能在单个 cell 上。因为拖拽时鼠标可能移出起始 cell，cell 级别的事件不会触发。

```html
<v-stage ref="stage" :config="stageConfig" @mouseup="onStageMouseUp">
```

`mousedown` 则绑定在 cell 上（判断用户点的是哪个信号）。

**信号名标签位置**：标签放在 `start_bit` 对应的方格上。对于 Motorola 信号，`start_bit` = MSB（通常在最右列），这个位置是符合直觉的。

**cellMap 重叠处理**：两个信号可能重叠（后端检测为 error）。cellMap 构建时不处理冲突——后面的信号覆盖前面的。错误通过 `store.signalErrors` + `hasError` 标记显示红色边框。

**`rows` 常量 vs DLC**：`rows = 8` 是 CAN 最大字节数，DLC < 8 时通过 DLC 边界半透明层遮盖未使用行。新架构中 coloredCells 只会为 `bit < dlc * 8` 的格子生成数据，超出的行只有半透明遮罩。

**`stage.getPointerPosition()` 与 scale**：此方法返回的是逻辑坐标（已包含 scale 变换），与 `pixelToGridCell` 预期的逻辑坐标一致，无需手动除以 scale。

---

## 五、关键结论

| 维度 | 旧架构 | 新架构 |
|------|--------|--------|
| 信号有像素坐标吗？ | 是 (`groupX/Y`, `rect.x/y`) | 否（信号只有 bit 集合） |
| `signalToRenderData` 做什么？ | 计算包围盒+rect 像素坐标 | 不再使用 |
| 拖拽移动的是什么？ | Konva Group 的像素位置 | bit 编号（纯整数运算） |
| 拖拽回调频率 | 每像素移动（snapDragBound） | 只需 mousedown/up 两次 |
| 坐标计算分布 | 散落在 renderData、模板、拖拽三处 | 只在模板的 `labelWidth + col * cellSize` |
