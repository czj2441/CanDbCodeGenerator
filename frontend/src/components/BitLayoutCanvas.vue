<template>
  <div class="bit-layout-canvas-wrap" ref="canvasWrap">
    <v-stage ref="stageRef" :config="stageConfig" @mouseup="onStageMouseUp" @click="onStageClick">
      <!-- 网格背景层：表头背景、DLC 遮罩、bit 编号 -->
      <v-layer>
        <!-- 列头背景 -->
        <v-rect :config="{
          x: labelWidth, y: 0, width: cols * cellSizeComputed, height: headerH,
          fill: gridHeaderFill, stroke: gridStroke, strokeWidth: 1, listening: false,
        }" />
        <!-- 列头标签：bit 7..0 -->
        <v-text
          v-for="i in colIndices" :key="'ch-' + i"
          :config="{
            x: labelWidth + i * cellSizeComputed, y: 0,
            width: cellSizeComputed, height: headerH,
            text: String(7 - i),
            align: 'center', verticalAlign: 'middle',
            fill: textDim, fontSize: 11, fontStyle: 'bold', listening: false,
          }"
        />
        <!-- 行头背景 -->
        <v-rect :config="{
          x: 0, y: headerH, width: labelWidth, height: totalRows * cellSizeComputed,
          fill: gridHeaderFill, stroke: gridStroke, strokeWidth: 1, listening: false,
        }" />
        <!-- 行头标签：byte 0..N -->
        <v-text
          v-for="r in rowIndices" :key="'rl-' + r"
          :config="{
            x: 0, y: headerH + r * cellSizeComputed,
            width: labelWidth - 4, height: cellSizeComputed,
            text: String(r),
            align: 'right', verticalAlign: 'middle',
            fill: textDim, fontSize: 11, listening: false,
            opacity: r >= rows ? 0.4 : 1,
          }"
        />
        <!-- 单元格 bit 编号（cellSize <= 16 时隐藏） -->
        <template v-if="cellSizeComputed > 16" v-for="r in rowIndices" :key="'bnr-' + r">
          <v-text
            v-for="c in colIndices" :key="'bn-' + r + '-' + c"
            :config="{
              x: labelWidth + c * cellSizeComputed + 2,
              y: headerH + r * cellSizeComputed + cellSizeComputed - 12,
              text: String(r * 8 + (7 - c)),
              fontSize: Math.max(6, Math.min(9, cellSizeComputed - 10)), fill: textDim, fontStyle: 'bold',
              align: 'left', verticalAlign: 'bottom', listening: false,
              opacity: r >= rows ? 0.35 : 1,
            }"
          />
        </template>
        <!-- 溢出区域背景斜线 -->
        <template v-if="overflowRows > 0">
          <v-group
            v-for="r in rowIndices.filter(r => r >= rows)" :key="'ofbg-' + r"
            :config="{ listening: false }"
          >
            <v-group
              v-for="c in colIndices" :key="c"
              :config="{
                x: labelWidth + c * cellSizeComputed,
                y: headerH + r * cellSizeComputed,
                listening: false,
              }"
            >
              <v-line
                v-for="(seg, si) in reverseHatchSegments" :key="si"
                :config="{
                  points: [seg.x1, seg.y1, seg.x2, seg.y2],
                  stroke: 'oklch(0.45 0.02 260)',
                  strokeWidth: 1,
                  opacity: 0.35,
                  listening: false,
                }"
              />
            </v-group>
          </v-group>
        </template>
      </v-layer>

      <!-- 信号着色层 -->
      <v-layer>
        <!-- 着色方格 -->
        <v-rect
          v-for="cell in coloredCells" :key="'c-' + cell.name + '-' + cell.bit"
          :config="{
            x: labelWidth + cell.col * cellSizeComputed,
            y: headerH + cell.row * cellSizeComputed,
            width: cellSizeComputed, height: cellSizeComputed,
            fill: cell.color,
            stroke: cell.color,
            strokeWidth: 1,
            cornerRadius: 2,
            opacity: cell.isPreview ? 0.4 : 1,
          }"
          @mousedown="(e) => interactive && $emit('cell-mousedown', cell, e.evt)"
          @click="() => interactive && $emit('cell-click', cell)"
        />
        <!-- 重叠斜线 -->
        <v-group
          v-for="cell in overlapCells" :key="'ov-' + cell.bit"
          :config="{
            x: labelWidth + cell.col * cellSizeComputed,
            y: headerH + cell.row * cellSizeComputed,
            listening: false,
          }"
        >
          <v-rect :config="{
            x: 0, y: 0, width: cellSizeComputed, height: cellSizeComputed,
            fill: 'oklch(0.45 0.12 25)', opacity: 0.2, cornerRadius: 2,
          }" />
          <v-line
            v-for="(seg, si) in hatchSegments" :key="si"
            :config="{
              points: [seg.x1, seg.y1, seg.x2, seg.y2],
              stroke: 'oklch(0.55 0.18 25)',
              strokeWidth: 1.5,
              listening: false,
            }"
          />
        </v-group>
        <!-- 信号名标签 -->
        <v-text
          v-for="lbl in signalLabels" :key="'lbl-' + lbl.name"
          :config="{
            x: labelWidth + lbl.col * cellSizeComputed,
            y: headerH + lbl.row * cellSizeComputed,
            text: lbl.text,
            width: lbl.span * cellSizeComputed,
            height: cellSizeComputed,
            fontSize: Math.max(8, Math.min(12, cellSizeComputed - 6)),
            fill: textPrimary, fontStyle: 'bold',
            align: 'center', verticalAlign: 'middle', listening: false,
          }"
        />
        <!-- 选中信号高亮边框 -->
        <v-rect
          v-for="cell in selectedCells" :key="'sel-' + cell.bit"
          :config="{
            x: labelWidth + cell.col * cellSizeComputed,
            y: headerH + cell.row * cellSizeComputed,
            width: cellSizeComputed, height: cellSizeComputed,
            fill: 'transparent',
            stroke: 'oklch(0.60 0.18 260)',
            strokeWidth: 2,
            listening: false,
          }"
        />
      </v-layer>

      <!-- 网格线层（最顶层，始终可见） -->
      <v-layer>
        <v-line
          v-for="r in gridLineRowIndices" :key="'h-' + r"
          :config="{
            points: [labelWidth, headerH + r * cellSizeComputed, labelWidth + cols * cellSizeComputed, headerH + r * cellSizeComputed],
            stroke: gridLineStroke, strokeWidth: 1, listening: false,
            dash: r > rows ? [4, 3] : [],
            opacity: r > rows ? 0.4 : 1,
          }"
        />
        <v-line v-if="overflowRows > 0" :config="{
          points: [labelWidth, headerH + rows * cellSizeComputed, labelWidth + cols * cellSizeComputed, headerH + rows * cellSizeComputed],
          stroke: 'oklch(0.60 0.18 25)',
          strokeWidth: 2,
          listening: false,
        }" />
        <v-line
          v-for="c in gridLineColIndices" :key="'v-' + c"
          :config="{
            points: [labelWidth + c * cellSizeComputed, headerH, labelWidth + c * cellSizeComputed, headerH + totalRows * cellSizeComputed],
            stroke: gridLineStroke, strokeWidth: 1, listening: false,
          }"
        />
      </v-layer>
    </v-stage>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { computeCellMap, bitToGridCell } from '../utils/signalLayout.js'

const props = defineProps({
  signals: {
    type: Array,
    default: () => [],
  },
  dlc: {
    type: Number,
    default: 8,
  },
  cellSize: {
    type: Number,
    default: null,  // null = auto from container width
  },
  interactive: {
    type: Boolean,
    default: false,
  },
  highlightNames: {
    type: [Set, null],
    default: null,
  },
  startBitOverrides: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['cell-mousedown', 'cell-click', 'stage-mouseup', 'stage-click'])

// ── Layout constants ──
const headerH = 32
const labelWidth = 44
const cols = 8
const MIN_CELL_SIZE = 12

const canvasWrap = ref(null)
const stageRef = ref(null)
const containerWidth = ref(600)
let resizeObserver = null

// Expose stage node for parent coordinate conversion
defineExpose({
  get stageNode() { return stageRef.value?.getStage() },
})

onMounted(() => {
  if (!canvasWrap.value) return
  resizeObserver = new ResizeObserver(([entry]) => {
    const { width } = entry.contentRect
    containerWidth.value = width - 16
  })
  resizeObserver.observe(canvasWrap.value)
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
})

// ── Cell size ──
const cellSizeComputed = computed(() => {
  if (props.cellSize != null) return props.cellSize
  const cw = containerWidth.value
  if (cw <= 0) return 36
  const ideal = Math.floor((cw - labelWidth - 1) / cols)
  return Math.max(MIN_CELL_SIZE, ideal)
})

// ── Rows ──
const rows = computed(() => props.dlc || 1)

const cellMapResult = computed(() =>
  computeCellMap(props.signals, props.startBitOverrides)
)

const coloredCells = computed(() => cellMapResult.value.cells)

const maxUsedRow = computed(() => {
  const cells = coloredCells.value
  if (cells.length === 0) return rows.value - 1
  let maxR = 0
  for (const cell of cells) {
    if (cell.row > maxR) maxR = cell.row
  }
  return maxR
})

const overflowRows = computed(() => {
  const dlcLastRow = rows.value - 1
  const overflow = maxUsedRow.value - dlcLastRow
  return overflow > 0 ? overflow + 1 : 0
})

const totalRows = computed(() => rows.value + overflowRows.value)

const baseW = computed(() => labelWidth + cols * cellSizeComputed.value + 1)
const baseH = computed(() => headerH + totalRows.value * cellSizeComputed.value + 1)

const stageConfig = computed(() => ({
  width: baseW.value,
  height: baseH.value,
}))

// ── Indices ──
const colIndices = Array.from({ length: cols }, (_, i) => i)
const rowIndices = computed(() => Array.from({ length: totalRows.value }, (_, i) => i))
const gridLineRowIndices = computed(() => Array.from({ length: totalRows.value + 1 }, (_, i) => i))
const gridLineColIndices = Array.from({ length: cols + 1 }, (_, i) => i)

// ── Theme colors ──
function getCssVar(name, fallback) {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}
const textPrimary = computed(() => getCssVar('--text', 'oklch(0.90 0.01 260)'))
const textDim = computed(() => getCssVar('--text-dim', 'oklch(0.55 0.01 260)'))
const gridStroke = computed(() => getCssVar('--layout-grid', 'oklch(0.35 0.005 260)'))
const gridLineStroke = computed(() => getCssVar('--border-light', 'oklch(0.28 0.005 260)'))
const gridHeaderFill = computed(() => getCssVar('--bg-panel', 'oklch(0.22 0.005 260)'))

// ── Hatch segments ──
function computeHatchSegments(size, gap) {
  const segs = []
  for (let off = -size; off <= size * 2; off += gap) {
    const x1 = Math.max(0, off)
    const y1 = Math.max(0, -off)
    const x2 = Math.min(size, size + off)
    const y2 = Math.min(size, size - off)
    if (x1 <= size && y1 <= size && x2 >= 0 && y2 >= 0 && (x1 !== x2 || y1 !== y2)) {
      segs.push({ x1, y1, x2, y2 })
    }
  }
  return segs
}

const hatchGap = computed(() => Math.max(4, Math.round(cellSizeComputed.value / 5)))
const hatchSegments = computed(() => computeHatchSegments(cellSizeComputed.value, hatchGap.value))
const reverseHatchSegments = computed(() => {
  const s = cellSizeComputed.value
  return hatchSegments.value.map(seg => ({ x1: s - seg.x1, y1: seg.y1, x2: s - seg.x2, y2: seg.y2 }))
})

// ── Overlap cells ──
const overlapCells = computed(() => {
  const bits = cellMapResult.value.overlapBits
  const result = []
  for (const bit of bits) {
    const { row, col } = bitToGridCell(bit)
    result.push({ bit, row, col })
  }
  return result
})

// ── Signal labels ──
const signalLabels = computed(() => {
  const cells = coloredCells.value
  if (cells.length === 0) return []
  const byName = {}
  for (const cell of cells) {
    if (!byName[cell.name]) byName[cell.name] = []
    byName[cell.name].push(cell)
  }
  const labels = []
  for (const [name, sigCells] of Object.entries(byName)) {
    const startCell = sigCells.find(c => c.isStartBit) || sigCells[0]
    const sameRow = sigCells
      .filter(c => c.row === startCell.row && c.col >= startCell.col)
      .map(c => c.col)
      .sort((a, b) => a - b)
    let span = 1
    for (let c = startCell.col + 1; sameRow.includes(c); c++) {
      span++
    }
    labels.push({ name, row: startCell.row, col: startCell.col, span, text: name })
  }
  return labels
})

// ── Selected cells (highlight) ──
const selectedCells = computed(() => {
  if (!props.highlightNames || props.highlightNames.size === 0) return []
  return coloredCells.value.filter(c => props.highlightNames.has(c.name))
})

// ── Stage events → re-emit to parent ──
function onStageMouseUp(konvaEvent) {
  const evt = konvaEvent?.evt
  if (!evt) return
  emit('stage-mouseup', evt)
}
function onStageClick(konvaEvent) {
  const target = konvaEvent?.target
  const stage = stageRef.value?.getStage()
  if (target && stage && target === stage) {
    emit('stage-click')
  }
}
</script>

<style scoped>
.bit-layout-canvas-wrap {
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  padding: 8px;
}
</style>
