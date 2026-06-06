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
        <button class="btn" @click="store.layoutViewMode = false">{{ t('layout.backToTable') }}</button>
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

    <!-- Debug 拖拽信息（悬浮覆盖，不影响 canvas 布局） -->
    <div v-if="debugInfo" class="debug-overlay">
      <div class="debug-row"><span class="debug-label">按下网格位置</span><span class="debug-val">{{ debugInfo.mousedownGrid }}</span></div>
      <div class="debug-row"><span class="debug-label">按下信号名</span><span class="debug-val">{{ debugInfo.signalName }}</span></div>
      <div class="debug-row"><span class="debug-label">按下偏移</span><span class="debug-val">{{ debugInfo.offset }}</span></div>
      <div class="debug-row"><span class="debug-label">松开网格位置</span><span class="debug-val">{{ debugInfo.mouseupGrid || '—' }}</span></div>
      <div class="debug-row"><span class="debug-label">新起始位</span><span class="debug-val">{{ debugInfo.newStartBit || '—' }}</span></div>
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
          @click="store.autoFixSignal(err.signal_uuid, err.suggestion.recommended_start_bit)"
        >{{ t('signal.fixBtn') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { t } from '../i18n.js'
import { getSignalBits, bitToGridCell, gridCellToBit, pixelToGridCell, clampStartBit, getSignalColor } from '../utils/signalLayout.js'
import { toHex } from '../utils/format.js'

const store = useEditorStore()

// ── Layout constants ──
const cellSize = 36
const headerH = 32
const labelWidth = 44
const cols = 8
const rows = 8

const baseW = labelWidth + cols * cellSize + 1
const baseH = headerH + rows * cellSize + 1

// 0-based 索引数组（修复 v-for="n in N" 的 1-index 陷阱）
const colIndices = Array.from({ length: cols }, (_, i) => i)
const rowIndices = Array.from({ length: rows }, (_, i) => i)
const gridLineRowIndices = Array.from({ length: rows + 1 }, (_, i) => i)
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
const oobFill = computed(() => getCssVar('--layout-oob', 'oklch(0.25 0.08 25 / 0.3)'))

const containerWidth = ref(baseW)
const containerHeight = ref(baseH)
const canvasWrap = ref(null)
let resizeObserver = null

const scale = computed(() => {
  const s = Math.min(containerWidth.value / baseW, containerHeight.value / baseH)
  return Math.max(0.7, s)
})

onMounted(() => {
  if (!canvasWrap.value) return
  resizeObserver = new ResizeObserver(([entry]) => {
    const { width, height } = entry.contentRect
    containerWidth.value = width - 16
    containerHeight.value = height - 16
  })
  resizeObserver.observe(canvasWrap.value)
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
})

// ── Stage config ──
const msg = computed(() => store.selectedMessage)
const dlcBytes = computed(() => msg.value?.dlc || 0)
const stageRef = ref(null)

const stageConfig = computed(() => ({
  width: baseW * scale.value,
  height: baseH * scale.value,
  scaleX: scale.value,
  scaleY: scale.value,
}))

// ── cellMap: bit → { uuid, name, color, hasError, row, col, byteOrder, isStartBit, startBit, length } ──
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
    const bits = getSignalBits(sig.start_bit, sig.length, sig.byte_order)

    for (const bit of bits) {
      if (bit < 0 || bit > maxBit) continue
      const { row, col } = bitToGridCell(bit)
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
  if (!store.selectedSignalUuid) return []
  return coloredCells.value.filter(c => c.uuid === store.selectedSignalUuid)
})

// ── 拖拽交互 ──
const dragState = ref(null)
const debugInfo = ref(null)

function onCellMouseDown(cell, konvaEvent) {
  konvaEvent?.evt?.preventDefault?.()

  const { row: startRow, col: startCol } = bitToGridCell(cell.startBit)
  const { row: grabRow, col: grabCol } = bitToGridCell(cell.bit)

  const offsetRow = grabRow - startRow
  const offsetCol = grabCol - startCol

  dragState.value = {
    uuid: cell.uuid,
    sigStartBit: cell.startBit,
    sigLength: cell.length,
    sigByteOrder: cell.byteOrder,
    offsetRow,
    offsetCol,
  }

  debugInfo.value = {
    mousedownGrid: `(row=${grabRow}, col=${grabCol})  bit=${cell.bit}`,
    signalName: cell.name,
    offset: `(dRow=${offsetRow}, dCol=${offsetCol})`,
    mouseupGrid: '',
    mouseupBit: '',
  }

  store.selectLayoutSignal(cell.uuid)
}

function onCellClick(cell) {
  if (dragState.value) return
  store.selectLayoutSignal(cell.uuid)
}

function onStageMouseUp(konvaEvent) {
  if (!dragState.value) return

  const s = scale.value
  const evt = konvaEvent?.evt
  const nx = (evt?.offsetX ?? 0) / s
  const ny = (evt?.offsetY ?? 0) / s
  const { row: dropRow, col: dropCol } = pixelToGridCell(nx, ny, {
    labelWidth, headerH, cellSize,
  })

  const clampedRow = Math.max(0, Math.min(rows - 1, dropRow))
  const clampedCol = Math.max(0, Math.min(cols - 1, dropCol))
  const dropBit = gridCellToBit(clampedRow, clampedCol)

  if (debugInfo.value) {
    debugInfo.value.mouseupGrid = `(row=${clampedRow}, col=${clampedCol})  bit=${dropBit}`
  }

  const ds = dragState.value
  dragState.value = null

  const targetStartRow = clampedRow - ds.offsetRow
  const targetStartCol = clampedCol - ds.offsetCol
  const targetStartBit = gridCellToBit(
    Math.max(0, targetStartRow),
    Math.max(0, Math.min(cols - 1, targetStartCol))
  )

  const maxBit = dlcBytes.value * 8 - 1
  const newStartBit = clampStartBit(targetStartBit, ds.sigLength, ds.sigByteOrder, maxBit)

  if (debugInfo.value) {
    debugInfo.value.newStartBit = `newStartBit=${newStartBit}`
  }

  if (newStartBit < 0 || newStartBit === ds.sigStartBit) return

  store.moveSignalByLayout(ds.uuid, newStartBit)
}

// ── Watch selectedMsgId → clear selection ──
watch(() => store.selectedMsgId, () => {
  store.selectedSignalUuid = null
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
  overflow: auto;
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

/* ── Debug overlay ── */
.debug-overlay {
  position: fixed;
  bottom: 8px;
  right: 8px;
  z-index: 9999;
  background: oklch(0.18 0.02 260 / 0.92);
  border: 1px solid oklch(0.35 0.01 260);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  font-size: 11px;
  font-family: 'Consolas', 'Courier New', monospace;
  pointer-events: none;
}

[data-theme="light"] .debug-overlay {
  background: oklch(0.96 0.01 260 / 0.92);
  border-color: oklch(0.7 0.01 260);
}

.debug-row {
  display: flex;
  gap: 8px;
  padding: 1px 0;
}

.debug-label {
  color: var(--text-dim);
  min-width: 80px;
  flex-shrink: 0;
}

.debug-val {
  color: oklch(0.72 0.14 40);
  font-weight: bold;
}

[data-theme="light"] .debug-val {
  color: oklch(0.55 0.16 25);
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
