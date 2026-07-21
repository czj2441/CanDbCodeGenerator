<template>
  <div class="layout-area">
    <div class="center-header">
      <div class="center-title">
        <template v-if="msg">
          <strong>{{ msg.name || t('msglist.unnamed') }}</strong>
          &mdash; {{ toHex(msg.id) }} &middot; {{ msg.signals.length }} signals
        </template>
      </div>
      <div class="toolbar">
        <button class="btn" @click="ui.toggleLayoutView()">{{ t('layout.backToTable') }}</button>
      </div>
    </div>

    <div class="layout-canvas-wrap" ref="canvasWrap">
      <template v-if="msg">
        <v-stage ref="stageRef" :config="stageConfig" @mouseup="onStageMouseUp">
          <!-- 网格背景层：表头背景、DLC 遮罩、bit 编号 -->
          <v-layer ref="gridBgLayer">
            <!-- 列头背景 -->
            <v-rect :config="{
              x: labelWidth, y: 0, width: cols * cellSize, height: headerH,
              fill: gridHeaderFill, stroke: gridStroke, strokeWidth: 1, listening: false,
            }" />
            <!-- 列头标签：bit 7..0 -->
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
            <!-- 单元格 bit 编号 -->
            <template v-for="r in rowIndices" :key="'bnr-' + r">
              <v-text
                v-for="c in colIndices" :key="'bn-' + r + '-' + c"
                :config="{
                  x: labelWidth + c * cellSize + 2,
                  y: headerH + r * cellSize + cellSize - 12,
                  text: String(r * 8 + (7 - c)),
                  fontSize: Math.max(6, Math.min(9, cellSize - 10)), fill: textDim, fontStyle: 'bold',
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
                opacity: cell.isPreview ? 0.4 : 1,
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
                fontSize: Math.max(8, Math.min(12, cellSize - 6)),
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
            <!-- 拖拽预览虚线框 -->
            <v-rect
              v-for="cell in previewCells" :key="'pre-' + cell.bit"
              :config="{
                x: labelWidth + cell.col * cellSize,
                y: headerH + cell.row * cellSize,
                width: cellSize, height: cellSize,
                fill: 'transparent',
                stroke: cell.color,
                strokeWidth: 2,
                dash: [4, 3],
                listening: false,
              }"
            />
          </v-layer>

          <!-- 网格线层（最顶层，始终可见） -->
          <v-layer ref="gridLineLayer">
            <v-line
              v-for="r in gridLineRowIndices" :key="'h-' + r"
              :config="{
                points: [labelWidth, headerH + r * cellSize, labelWidth + cols * cellSize, headerH + r * cellSize],
                stroke: gridLineStroke, strokeWidth: 1, listening: false,
              }"
            />
            <v-line
              v-for="c in gridLineColIndices" :key="'v-' + c"
              :config="{
                points: [labelWidth + c * cellSize, headerH, labelWidth + c * cellSize, headerH + rows * cellSize],
                stroke: gridLineStroke, strokeWidth: 1, listening: false,
              }"
            />
          </v-layer>
        </v-stage>
      </template>
      <div v-else class="placeholder">{{ t('signal.selectMessage') }}</div>
    </div>

    <!-- Error panel -->
    <div v-if="msg && store.signalErrors.length > 0" class="error-panel">
      <div class="error-header">{{ t('signal.errorsTitle') }}</div>
      <div
        v-for="err in store.signalErrors" :key="err.signal_uuid + (err.conflicts_uuid || '')"
        class="error-item"
      >
        <template v-if="err.type === 'out_of_bounds'">
          {{ t('signal.errorOutOfBounds', { name: err.signal_name, bits: err.out_of_bounds_bits?.join(',') || '', max: msg.dlc * 8 - 1 }) }}
        </template>
        <template v-else-if="err.type === 'overlap'">
          {{ t('signal.errorOverlap', { name: err.signal_name, other: err.conflicts_name, bits: err.overlapping_bits?.join(',') || '' }) }}
        </template>
        <button
          v-if="err.suggestion?.action === 'move_start_bit'"
          class="btn btn-xs"
          @click="signals.autoFixSignal(err.signal_uuid, err.suggestion.recommended_start_bit)"
        >{{ t('signal.fixBtn') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useSignalsStore } from '../stores/signals.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'
import { getSignalBits, bitToGridCell, gridCellToBit, pixelToGridCell, clampStartBit, getSignalColor, motorolaBitAtPosition, motorolaFindMsbByPosition } from '../utils/signalLayout.js'
import { toHex } from '../utils/format.js'

const store = useEditorStore()
const signals = useSignalsStore()
const ui = useUiStore()

// ── Stage config ──
const msg = computed(() => store.selectedMessage)
const dlcBytes = computed(() => msg.value?.dlc || 0)
const stageRef = ref(null)

// ── Dynamic layout (rows 跟随 DLC，cellSize 由容器宽度决定，纵向自由滚动) ──
const headerH = 32
const labelWidth = 44
const cols = 8
const MIN_CELL_SIZE = 12

const containerWidth = ref(600)

const rows = computed(() => dlcBytes.value || 1)

const cellSize = computed(() => {
  const cw = containerWidth.value
  if (cw <= 0) return 36
  const ideal = Math.floor((cw - labelWidth - 1) / cols)
  return Math.max(MIN_CELL_SIZE, ideal)
})

const baseW = computed(() => labelWidth + cols * cellSize.value + 1)
const baseH = computed(() => headerH + rows.value * cellSize.value + 1)

// 0-based 索引数组
const colIndices = Array.from({ length: cols }, (_, i) => i)
const rowIndices = computed(() => Array.from({ length: rows.value }, (_, i) => i))
const gridLineRowIndices = computed(() => Array.from({ length: rows.value + 1 }, (_, i) => i))
const gridLineColIndices = Array.from({ length: cols + 1 }, (_, i) => i)

// ── Theme colors from CSS vars ──
function getCssVar(name, fallback) {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}
const textPrimary = computed(() => getCssVar('--text', 'oklch(0.90 0.01 260)'))
const textDim = computed(() => getCssVar('--text-dim', 'oklch(0.55 0.01 260)'))
const gridStroke = computed(() => getCssVar('--layout-grid', 'oklch(0.35 0.005 260)'))
const gridLineStroke = computed(() => getCssVar('--border-light', 'oklch(0.28 0.005 260)'))
const gridHeaderFill = computed(() => getCssVar('--bg-panel', 'oklch(0.22 0.005 260)'))

const canvasWrap = ref(null)
let resizeObserver = null

onMounted(() => {
  if (!canvasWrap.value) return
  resizeObserver = new ResizeObserver(([entry]) => {
    const { width } = entry.contentRect
    containerWidth.value = width - 16
  })
  resizeObserver.observe(canvasWrap.value)
  
  // 全局监听 mousemove/mouseup，防止鼠标拖出 canvas 后不触发
  window.addEventListener('mousemove', handleGlobalMouseMove, true)
  window.addEventListener('mouseup', handleGlobalMouseUp, true)
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  window.removeEventListener('mousemove', handleGlobalMouseMove, true)
  window.removeEventListener('mouseup', handleGlobalMouseUp, true)
})

const stageConfig = computed(() => ({
  width: baseW.value,
  height: baseH.value,
}))

// ── 拖拽状态 ref（需在 cellMap 之前声明）──
const dragState = ref(null)
const previewStartBit = ref(null)  // 拖拽预览用的临时 start_bit

// ── cellMap: bit → { uuid, name, color, hasError, row, col, byteOrder, isStartBit, startBit, length, isPreview } ──
const cellMap = computed(() => {
  const map = {}
  if (!msg.value) return map
  const dlc = dlcBytes.value
  const maxBit = dlc * 8 - 1
  const errUuids = new Set(
    store.signalErrors.flatMap(e => [e.signal_uuid, e.conflicts_uuid].filter(Boolean))
  )

  msg.value.signals.forEach((sig, idx) => {
    const color = getSignalColor(idx)
    const hasError = errUuids.has(sig.uuid)
    // 拖拽预览：用预览的 start_bit 计算占位
    const effectiveStartBit = (dragState.value?.uuid === sig.uuid && previewStartBit.value != null)
      ? previewStartBit.value
      : sig.start_bit
    const bits = getSignalBits(effectiveStartBit, sig.length, sig.byte_order)

    const isPreview = dragState.value?.uuid === sig.uuid && previewStartBit.value != null

    for (const bit of bits) {
      if (bit < 0 || bit > maxBit) continue
      const { row, col } = bitToGridCell(bit)
      map[bit] = {
        bit, row, col,
        uuid: sig.uuid,
        name: sig.name,
        color,
        hasError,
        isPreview,
        isStartBit: bit === effectiveStartBit,
        byteOrder: sig.byte_order,
        startBit: effectiveStartBit,
        length: sig.length,
      }
    }
  })
  return map
})

const coloredCells = computed(() => Object.values(cellMap.value))

// signalLabels: 每个信号一个标签，放在 start_bit 方格上
const signalLabels = computed(() => {
  const map = cellMap.value
  const keys = Object.keys(map)
  if (keys.length === 0) return []

  const byUuid = {}
  for (const cell of Object.values(map)) {
    if (!byUuid[cell.uuid]) byUuid[cell.uuid] = []
    byUuid[cell.uuid].push(cell)
  }

  const labels = []
  for (const [uuid, cells] of Object.entries(byUuid)) {
    const startCell = cells.find(c => c.isStartBit) || cells[0]
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

// selectedCells: 选中信号的所有方格
const selectedCells = computed(() => {
  if (!ui.selectedSignalUuid) return []
  return coloredCells.value.filter(c => c.uuid === ui.selectedSignalUuid)
})

// previewCells: 拖拽预览的虚线边框方格
const previewCells = computed(() => {
  if (!dragState.value || previewStartBit.value == null) return []
  return coloredCells.value.filter(c => c.isPreview)
})

// ── 拖拽交互 ──
//
// Intel: dropBit − grabBit = bitDelta → newMsb = oldMsb + bitDelta
//
// Motorola (锯齿布局): 无法用 grid 位移直接算 newMsb
//   改用"遍历位置匹配": 记录 grab bit 在遍历中的序号 grabPos
//   搜索哪个 MSB 使得 motorolaBitAtPosition(msb, grabPos) = dropBit
//
//   例: MSB=7 len=8, grab bit=0 → grabPos=7 (LSB)
//       拖到 dropBit=10: motorolaFindMsbByPosition(7,8,10,63,7) → MSB=1
//       验证: motorolaBitAtPosition(1,7) = 1→0→15→14→13→12→11→10 ✓
//
const isProcessingDrop = ref(false)
const hasMoved = ref(false)

/** 坐标 → 网格位置 */
function clientToGrid(clientX, clientY) {
  const stage = stageRef.value?.getStage()
  if (!stage) return null
  const container = stage.container()
  const rect = container.getBoundingClientRect()
  const stageX = clientX - rect.left
  const stageY = clientY - rect.top
  const raw = pixelToGridCell(stageX, stageY, { labelWidth, headerH, cellSize: cellSize.value })
  const r = Math.max(0, Math.min(rows.value - 1, raw.row))
  const c = Math.max(0, Math.min(cols - 1, raw.col))
  return { row: r, col: c, bit: gridCellToBit(r, c) }
}

function onCellMouseDown(cell, konvaEvent) {
  if (konvaEvent?.evt?.button !== 0) return
  konvaEvent?.evt?.preventDefault?.()

  const { row: msbRow, col: msbCol } = bitToGridCell(cell.startBit)
  const { row: grabRow, col: grabCol } = bitToGridCell(cell.bit)
  const offsetRow = grabRow - msbRow
  const offsetCol = grabCol - msbCol

  // 记录 grab bit 在遍历中的位置
  let grabPos = 0
  if (cell.byteOrder === 'motorola') {
    for (let p = 0; p < cell.length; p++) {
      if (motorolaBitAtPosition(cell.startBit, p) === cell.bit) { grabPos = p; break }
    }
  } else {
    grabPos = cell.bit - cell.startBit  // Intel: 线性
  }

  dragState.value = {
    uuid: cell.uuid,
    sigStartBit: cell.startBit,
    sigLength: cell.length,
    sigByteOrder: cell.byteOrder,
    offsetRow, offsetCol,
    grabBit: cell.bit,
    grabPos,
  }
  previewStartBit.value = null
  hasMoved.value = false

  store.addLogEntry('drag', `${cell.name}: mousedown bit=${cell.bit} (row=${grabRow},col=${grabCol}) offset=(${offsetRow},${offsetCol})`)
  ui.selectLayoutSignal(cell.uuid)
}

function onCellClick(cell) {
  if (hasMoved.value) return
  ui.selectLayoutSignal(cell.uuid)
}

function handleGlobalMouseMove(e) {
  if (!dragState.value) return
  const ds = dragState.value
  const grid = clientToGrid(e.clientX, e.clientY)
  if (!grid) return

  const maxBit = dlcBytes.value * 8 - 1
  let newStartBit

  if (ds.sigByteOrder === 'intel') {
    newStartBit = ds.sigStartBit + (grid.bit - ds.grabBit)
  } else {
    newStartBit = motorolaFindMsbByPosition(ds.grabPos, ds.sigLength, grid.bit, maxBit, ds.sigStartBit)
  }

  if (newStartBit >= 0) {
    const clamped = clampStartBit(newStartBit, ds.sigLength, ds.sigByteOrder, dlcBytes.value)
    if (clamped >= 0 && clamped <= maxBit) {
      if (clamped !== ds.sigStartBit) hasMoved.value = true
      previewStartBit.value = clamped
    }
  }
}

function processDrop(clientX, clientY) {
  if (!dragState.value || isProcessingDrop.value) return
  isProcessingDrop.value = true

  const ds = dragState.value
  dragState.value = null
  previewStartBit.value = null

  try {
    const grid = clientToGrid(clientX, clientY)
    if (!grid) return

    const maxBit = dlcBytes.value * 8 - 1
    let newStartBit
    let calcDetail = ''

    if (ds.sigByteOrder === 'intel') {
      newStartBit = ds.sigStartBit + (grid.bit - ds.grabBit)
      calcDetail = `drop=${grid.bit} − grab=${ds.grabBit} + msb=${ds.sigStartBit}`
    } else {
      newStartBit = motorolaFindMsbByPosition(ds.grabPos, ds.sigLength, grid.bit, maxBit, ds.sigStartBit)
      calcDetail = `grabPos=${ds.grabPos} drop=${grid.bit} → MSB=${newStartBit}`
    }

    if (newStartBit == null || newStartBit < 0) {
      store.addLogEntry('drag', `松开(${grid.row},${grid.col}) bit=${grid.bit} 超出范围`)
      return
    }

    const clamped = clampStartBit(newStartBit, ds.sigLength, ds.sigByteOrder, maxBit)
    const sig = store.selectedMessage?.signals?.find(s => s.uuid === ds.uuid)
    const sigName = sig?.name || ds.uuid.slice(0, 8)

    if (clamped < 0 || clamped > maxBit || clamped === ds.sigStartBit) {
      store.addLogEntry('drag', `${sigName}: 松开(${grid.row},${grid.col}) bit=${grid.bit} → ${ds.sigStartBit} 未变 (${calcDetail})`)
      return
    }

    store.addLogEntry('layout', [
      `${sigName}: startBit ${ds.sigStartBit} → ${clamped}`,
      `  松开(${grid.row},${grid.col}) bit=${grid.bit}  ${calcDetail}`,
      `  clamp(${ds.sigByteOrder}, len=${ds.sigLength}) → ${clamped}`,
    ].join('\n'))
    signals.moveSignalByLayout(ds.uuid, clamped)
  } finally {
    isProcessingDrop.value = false
  }
}

function handleGlobalMouseUp(e) {
  if (!dragState.value) return
  if (e.button !== 0) return
  e.preventDefault()
  processDrop(e.clientX, e.clientY)
}

function onStageMouseUp(konvaEvent) {
  if (!dragState.value) return
  const evt = konvaEvent?.evt
  if (!evt) return
  if (evt.button !== 0) return
  processDrop(evt.clientX, evt.clientY)
}

// ── Watch selectedMsgId → clear selection ──
watch(() => store.selectedMsgId, () => {
  ui.selectedSignalUuid = null
})
</script>

<style scoped>
.layout-area {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
}

.center-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  height: 40px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  flex-shrink: 0;
}

.center-title {
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  transition: background var(--transition), border-color var(--transition);
}
.btn:hover {
  background: var(--bg-hover);
}

.layout-canvas-wrap {
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  padding: 8px;
  background: var(--bg);
}

.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 200px;
  color: var(--text-muted);
  font-size: 14px;
  text-align: center;
  line-height: 1.8;
}

/* ── Error panel ── */
.error-panel {
  border-top: 1px solid var(--border);
  background: oklch(0.22 0.05 25 / 0.15);
  padding: 8px 12px;
  max-height: 140px;
  overflow-y: auto;
  flex-shrink: 0;
  font-size: 12px;
}

[data-theme="light"] .error-panel {
  background: oklch(0.92 0.05 25 / 0.3);
}

.error-header {
  font-weight: 600;
  color: var(--danger);
  margin-bottom: 4px;
}

.error-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--danger);
  padding: 2px 0;
  font-size: 11px;
}

.btn-xs {
  padding: 1px 6px;
  font-size: 10px;
  border-color: var(--danger);
  color: var(--danger);
  flex-shrink: 0;
}
</style>
