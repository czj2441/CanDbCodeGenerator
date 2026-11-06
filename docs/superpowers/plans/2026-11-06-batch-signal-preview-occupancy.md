# 批量信号预览显示已有信号占用层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让批量创建信号模态框的位布局预览把「当前报文已有信号」渲染为灰色占用底图，使新信号与已有信号的重叠和空闲位在创建前可见。

**Architecture:** 全部纯布局逻辑放进 `signalLayout.js`（可被 `node --test` 单测），组件只做薄接线：`BitLayoutCanvas` 新增 `occupiedBits` prop 渲染灰底并复用现有红斜线标重叠；`BatchModal` 把 `editor.selectedMessage.signals` 换算成占用 bit 传进去。已有信号不分色、不标名。

**Tech Stack:** Vue 3 (`<script setup>`)、vue-konva、Node 内置 `node --test`（无组件测试框架）。

**Spec:** `docs/superpowers/specs/2026-11-06-batch-signal-preview-occupancy-design.md`

## Global Constraints

- 已有信号仅作为灰色半透明占用底图，不参与 `signalLabels`、不分色、不标名。
- 重叠检测需覆盖「新建信号 cell ∩ 已有占用 bit」，沿用现有红斜线（`overlapCells`）渲染。
- 前端无组件测试框架；纯函数用 `node --test`，组件改动用 `npm run build` + 手动 smoke 验证。
- `computeCellMap` 现有两个调用方（`SignalLayoutVisualizer.vue:88`、`BitLayoutCanvas.vue:260`）必须不回归：新增第 3 参默认 `null`。
- 不改 `computeBatchSignals`、不改后端、不改预览下方表格。

## Review Focus

1. Motorola 已有信号的占用 bit 必须走锯齿遍历（`getSignalBits`），不能按线性算 → Task 1 test「computeOccupiedBits: motorola 跨字节」。
2. 已有信号 bit 越界（超出 DLC）→ 灰格裁剪到 `row < dlc`，不崩溃 → Task 1 test「occupiedBitsToCells 裁剪越界」。
3. 新信号与已有信号仅重叠 1 bit → 该 bit 进入 `overlapBits` 画红斜线 → Task 1 test「computeCellMap 计入 occupiedBits 重叠」。
4. 空 `occupiedBits`（报文无已有信号）→ 无灰格、无多余重叠 → Task 1 test「空 occupiedBits」。
5. `occupiedBits` 未传（`SignalLayoutVisualizer` 等既有路径）→ 行为与改前一致 → Task 2 的 build + 手动回归（无组件测试框架，无自动化）。

---

### Task 1: 占用位纯函数 + 重叠扩展（signalLayout.js）

**Files:**
- Modify: `frontend/src/utils/signalLayout.js`（`computeCellMap` 扩展 + 新增两个导出）
- Test: `frontend/src/utils/__tests__/occupiedBits.test.js`

**Interfaces:**
- Produces:
  - `computeOccupiedBits(signals: Array<{start_bit:number,length:number,byte_order:string}>) -> Set<number>`
  - `occupiedBitsToCells(occupiedBits: Set<number>, dlc: number) -> Array<{bit:number,row:number,col:number}>`
  - `computeCellMap(signals, overrides = {}, occupiedBits = null) -> { cells, overlapBits }`（`overlapBits` 现额外包含与 `occupiedBits` 相交的 cell bit）

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/utils/__tests__/occupiedBits.test.js`：

```js
import { describe, it } from 'node:test'
import assert from 'node:assert'
import { computeOccupiedBits, occupiedBitsToCells, computeCellMap } from '../signalLayout.js'

describe('computeOccupiedBits', () => {
  it('intel 线性占用 0..7', () => {
    const s = computeOccupiedBits([{ start_bit: 0, length: 8, byte_order: 'intel' }])
    assert.deepStrictEqual([...s].sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6, 7])
  })

  it('motorola 跨字节锯齿占用 8..23', () => {
    const s = computeOccupiedBits([{ start_bit: 15, length: 16, byte_order: 'motorola' }])
    const want = Array.from({ length: 16 }, (_, i) => 8 + i)
    assert.deepStrictEqual([...s].sort((a, b) => a - b), want)
  })

  it('多信号取并集', () => {
    const s = computeOccupiedBits([
      { start_bit: 0, length: 4, byte_order: 'intel' },
      { start_bit: 8, length: 4, byte_order: 'intel' },
    ])
    assert.strictEqual(s.size, 8)
  })
})

describe('occupiedBitsToCells', () => {
  it('裁剪 row >= dlc 的越界 bit', () => {
    const cells = occupiedBitsToCells(new Set([0, 8, 64]), 1)
    assert.strictEqual(cells.length, 1)
    assert.strictEqual(cells[0].bit, 0)
  })
})

describe('computeCellMap 与 occupiedBits 重叠', () => {
  it('新信号 cell 与 occupiedBits 相交 → 进入 overlapBits', () => {
    const occupied = new Set([4])
    const { cells, overlapBits } = computeCellMap(
      [{ name: 'A', start_bit: 0, length: 8, byte_order: 'intel' }],
      {},
      occupied,
    )
    assert.strictEqual(cells.length, 8)
    assert.deepStrictEqual([...overlapBits], [4])
  })

  it('空 occupiedBits → 无重叠、正常 cells', () => {
    const { cells, overlapBits } = computeCellMap(
      [{ name: 'A', start_bit: 0, length: 8, byte_order: 'intel' }],
      {},
      new Set(),
    )
    assert.strictEqual(cells.length, 8)
    assert.strictEqual(overlapBits.size, 0)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/` 下）: `node --test src/utils/__tests__/occupiedBits.test.js`
Expected: FAIL（`computeOccupiedBits` / `occupiedBitsToCells` 未定义，`computeCellMap` 不认第 3 参）

- [ ] **Step 3: 实现三个函数于 `frontend/src/utils/signalLayout.js`**

- `computeOccupiedBits(signals)`：对每个 signal 调 `getSignalBits(start_bit, length, byte_order)`，把结果并入一个 `Set` 返回。
- `occupiedBitsToCells(occupiedBits, dlc)`：遍历 `occupiedBits`，`bitToGridCell(bit)` 后仅保留 `row < dlc && bit <= 511 && bit >= 0` 的 `{bit,row,col}`。
- 扩展 `computeCellMap(signals, overrides = {}, occupiedBits = null)`：在现有 `bitOwner` 重叠判定之外，`for (const cell of allCells)` 若 `occupiedBits?.has(cell.bit)` 则 `overlapBits.add(cell.bit)`。不把 occupied bit 写入 `cells`（灰底由组件单独渲染）。

- [ ] **Step 4: 运行测试确认通过**

Run: `node --test src/utils/__tests__/occupiedBits.test.js`
Expected: PASS（同时跑 `node --test src/utils/__tests__/batchBoundary.test.js` 确保无回归）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/signalLayout.js frontend/src/utils/__tests__/occupiedBits.test.js
git commit -m "feat(signalLayout): add occupied-bits helpers and overlap-with-occupied"
```

---

### Task 2: BitLayoutCanvas 渲染灰色占用层

**Files:**
- Modify: `frontend/src/components/BitLayoutCanvas.vue`

**Interfaces:**
- Consumes: `computeCellMap`（第 3 参 `occupiedBits`）、`occupiedBitsToCells`（Task 1）
- Produces: 新 prop `occupiedBits: [Set, null]`（default `null`）

- [ ] **Step 1: 加 prop**

在 `defineProps` 增加：

```js
occupiedBits: { type: [Set, null], default: null },
```

- [ ] **Step 2: 加 occupiedCells computed 并接入 computeCellMap**

- `import { computeCellMap, bitToGridCell, occupiedBitsToCells } from '../utils/signalLayout.js'`
- `cellMapResult` 改为 `computeCellMap(props.signals, props.startBitOverrides, props.occupiedBits)`。
- 新增 `const occupiedCells = computed(() => props.occupiedBits ? occupiedBitsToCells(props.occupiedBits, rows.value) : [])`。

- [ ] **Step 3: 在信号层最底部渲染灰格**

在 `<v-layer :config="{ listening: !dragging }">` 内、`v-for="cell in coloredCells"` 之前，插入：

```html
<v-rect
  v-for="cell in occupiedCells" :key="'occ-' + cell.bit"
  :config="{
    x: labelWidth + cell.col * cellSizeComputed,
    y: headerH + cell.row * cellSizeComputed,
    width: cellSizeComputed, height: cellSizeComputed,
    fill: 'oklch(0.55 0.01 260)',
    opacity: 0.3,
    cornerRadius: 2,
    listening: false,
  }"
/>
```

（灰格不设 stroke、无 label；新信号彩色格与红斜线重叠层绘制在其后，自然覆盖。）

- [ ] **Step 4: 构建验证**

Run（在 `frontend/` 下）: `npm run build`
Expected: 构建成功，无语法/引用错误。

- [ ] **Step 5: 手动回归（无组件测试框架）**

- 打开布局视图（`SignalLayoutVisualizer` 路径，未传 `occupiedBits`）：确认与改前一致，无灰格、无额外重叠。
- 在 `BatchModal` 尚接入前，本组件默认 `occupiedBits=null`，预览无灰格（行为不变）。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BitLayoutCanvas.vue
git commit -m "feat(BitLayoutCanvas): render occupiedBits as gray background layer"
```

---

### Task 3: BatchModal 传入已有信号占用位

**Files:**
- Modify: `frontend/src/components/BatchModal.vue`

**Interfaces:**
- Consumes: `computeOccupiedBits`（Task 1）、`BitLayoutCanvas` 新 prop `occupiedBits`（Task 2）
- Produces: （无新对外接口）

- [ ] **Step 1: 计算已有信号占用位**

在 `<script setup>` 中新增导入与 computed：

```js
import { computeBatchSignals, computeOccupiedBits } from '../utils/signalLayout.js'

const existingSignals = computed(() => {
  const msg = editor.selectedMessage
  return msg ? Object.values(msg.signals || {}) : []
})

const existingOccupiedBits = computed(() =>
  existingSignals.value.length
    ? computeOccupiedBits(existingSignals.value)
    : new Set()
)
```

- [ ] **Step 2: 传给 BitLayoutCanvas**

```html
<BitLayoutCanvas
  :signals="canvasSignals"
  :dlc="currentMsgDlc"
  :occupied-bits="existingOccupiedBits"
/>
```

（`canvasSignals` 已过滤 invalid，保持不变；预览表格不变。）

- [ ] **Step 3: 构建验证**

Run（在 `frontend/` 下）: `npm run build`
Expected: 构建成功。

- [ ] **Step 4: 手动 smoke**

- 选中一个已有信号的报文，打开批量创建：灰底显示已有信号占用，新信号彩色，重叠处红斜线，空闲位空白。
- 切换到无已有信号的报文：无灰格，其余正常。
- 修改 startBit/length/count，灰底保持稳定（只随已有信号变化），新信号随表单实时变化。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BatchModal.vue
git commit -m "feat(BatchModal): pass existing-signal occupancy into preview"
```
