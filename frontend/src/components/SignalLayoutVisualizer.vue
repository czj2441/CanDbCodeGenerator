<template>
  <div class="layout-area">
    <div class="center-header">
      <div class="center-title">
        <template v-if="msg">
          <strong>{{ msg.name || t('msglist.unnamed') }}</strong>
          &mdash; {{ toHex(msg.id) }} &middot; {{ Object.keys(msg.signals).length }} signals
        </template>
      </div>
      <div class="toolbar">
        <button class="btn" @click="ui.toggleLayoutView()">{{ t('layout.backToTable') }}</button>
      </div>
    </div>

    <div class="layout-canvas-wrap" ref="canvasWrap">
      <template v-if="msg">
        <BitLayoutCanvas
          ref="layoutCanvasRef"
          :signals="msgSignals"
          :dlc="dlcBytes"
          :start-bit-overrides="dragOverrides"
          :highlight-names="selectedSignalSet"
          interactive
          @cell-mousedown="onCellMouseDown"
          @cell-click="onCellClick"
          @stage-mouseup="onStageMouseUp"
          @stage-click="onStageClick"
        />
      </template>
      <div v-else class="placeholder">{{ t('signal.selectMessage') }}</div>
    </div>

  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useSignalsStore } from '../stores/signals.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'
import { bitToGridCell, pixelToGridCell, motorolaBitAtPosition, motorolaFindMsbByPosition, computeCellMap } from '../utils/signalLayout.js'
import { toHex } from '../utils/format.js'
import BitLayoutCanvas from './BitLayoutCanvas.vue'

const store = useEditorStore()
const signals = useSignalsStore()
const ui = useUiStore()

// ── Computed data ──
const msg = computed(() => store.selectedMessage)
const dlcBytes = computed(() => msg.value?.dlc || 0)
const msgSignals = computed(() => msg.value ? Object.values(msg.value.signals) : [])

const layoutCanvasRef = ref(null)
const headerH = 32
const labelWidth = 44
const cols = 8
const MIN_CELL_SIZE = 12

const containerWidth = ref(600)

const canvasWrap = ref(null)
let resizeObserver = null

const cellSize = computed(() => {
  const cw = containerWidth.value
  if (cw <= 0) return 36
  const ideal = Math.floor((cw - labelWidth - 1) / cols)
  return Math.max(MIN_CELL_SIZE, ideal)
})

const rows = computed(() => dlcBytes.value || 1)

// 计算信号占用的最大行号，用于检测溢出
const overflowRows = computed(() => {
  const result = computeCellMap(msgSignals.value)
  let maxR = rows.value - 1
  for (const cell of result.cells) {
    if (cell.row > maxR) maxR = cell.row
  }
  const overflow = maxR - (rows.value - 1)
  return overflow > 0 ? overflow + 1 : 0
})

const dragExtraRows = ref(0)
const totalRows = computed(() => rows.value + Math.max(overflowRows.value, dragExtraRows.value))

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

// ── 拖拽 overrides → BitLayoutCanvas props ──
const dragOverrides = computed(() => {
  if (!dragState.value || previewStartBit.value == null) return {}
  return { [dragState.value.name]: previewStartBit.value }
})

const selectedSignalSet = computed(() => {
  if (!ui.selectedSignalName) return null
  return new Set([ui.selectedSignalName])
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
const dragState = ref(null)
const previewStartBit = ref(null)
const isProcessingDrop = ref(false)
const hasMoved = ref(false)

/** 坐标 → 网格位置 */
function clientToGrid(clientX, clientY) {
  const stageNode = layoutCanvasRef.value?.stageNode
  if (!stageNode) return null
  const container = stageNode.container()
  const rect = container.getBoundingClientRect()
  const stageX = clientX - rect.left
  const stageY = clientY - rect.top
  const raw = pixelToGridCell(stageX, stageY, { labelWidth, headerH, cellSize: cellSize.value })
  const r = Math.max(0, Math.min(totalRows.value - 1, raw.row))
  const c = Math.max(0, Math.min(cols - 1, raw.col))
  return { row: r, col: c, bit: r * 8 + (7 - c) }
}

function onCellMouseDown(cell, nativeEvent) {
  if (nativeEvent?.button !== 0) return
  nativeEvent?.preventDefault?.()

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
    name: cell.name,
    sigStartBit: cell.startBit,
    sigLength: cell.length,
    sigByteOrder: cell.byteOrder,
    offsetRow, offsetCol,
    grabBit: cell.bit,
    grabPos,
  }
  dragExtraRows.value = 0
  previewStartBit.value = null
  hasMoved.value = false

  store.addLogEntry('drag', `${cell.name}: mousedown bit=${cell.bit} (row=${grabRow},col=${grabCol}) offset=(${offsetRow},${offsetCol})`)
}

function onCellClick(cell) {
  if (hasMoved.value) return
  ui.selectedSignalName = cell.name
}

function handleGlobalMouseMove(e) {
  if (!dragState.value) return
  const ds = dragState.value
  const grid = clientToGrid(e.clientX, e.clientY)
  if (!grid) return

  const stageNode = layoutCanvasRef.value?.stageNode
  if (stageNode) {
    const rect = stageNode.container().getBoundingClientRect()
    const stageY = e.clientY - rect.top
    const rawRow = Math.floor((stageY - headerH) / cellSize.value)
    if (rawRow >= totalRows.value) {
      dragExtraRows.value = Math.max(dragExtraRows.value, rawRow - rows.value + 2)
    }
  }

  const dragMaxBit = Math.max(totalRows.value * 8 - 1, ds.sigStartBit + ds.sigLength, 511)
  let newStartBit

  if (ds.sigByteOrder === 'intel') {
    newStartBit = ds.sigStartBit + (grid.bit - ds.grabBit)
  } else {
    newStartBit = motorolaFindMsbByPosition(ds.grabPos, ds.sigLength, grid.bit, dragMaxBit, ds.sigStartBit)
  }

  if (newStartBit >= 0) {
    const totalMaxBit = totalRows.value * 8 - 1
    if (newStartBit <= totalMaxBit) {
      if (newStartBit !== ds.sigStartBit) hasMoved.value = true
      previewStartBit.value = newStartBit
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

    // 使用扩展范围：覆盖 DLC + 额外行 + Motorola MSB 可能的高位
    const dragMaxBit = Math.max(totalRows.value * 8 - 1, ds.sigStartBit + ds.sigLength, 511)
    let newStartBit
    let calcDetail = ''

    if (ds.sigByteOrder === 'intel') {
      newStartBit = ds.sigStartBit + (grid.bit - ds.grabBit)
      calcDetail = `drop=${grid.bit} − grab=${ds.grabBit} + msb=${ds.sigStartBit}`
    } else {
      newStartBit = motorolaFindMsbByPosition(ds.grabPos, ds.sigLength, grid.bit, dragMaxBit, ds.sigStartBit)
      calcDetail = `grabPos=${ds.grabPos} drop=${grid.bit} → MSB=${newStartBit}`
    }

    if (newStartBit == null || newStartBit < 0) {
      store.addLogEntry('drag', `松开(${grid.row},${grid.col}) bit=${grid.bit} 无法计算新位置`)
      return
    }

    const totalMaxBit = totalRows.value * 8 - 1
    if (newStartBit > totalMaxBit) {
      store.addLogEntry('drag', `松开(${grid.row},${grid.col}) bit=${grid.bit} 超出网格范围`)
      return
    }

    const sig = store.selectedMessage?.signals?.[ds.name]
    const sigName = sig?.name || ds.name

    if (newStartBit === ds.sigStartBit) {
      store.addLogEntry('drag', `${sigName}: 松开(${grid.row},${grid.col}) bit=${grid.bit} → ${ds.sigStartBit} 未变 (${calcDetail})`)
      return
    }

    store.addLogEntry('layout', [
      `${sigName}: startBit ${ds.sigStartBit} → ${newStartBit}`,
      `  松开(${grid.row},${grid.col}) bit=${grid.bit}  ${calcDetail}`,
    ].join('\n'))
    signals.moveSignalByLayout(ds.name, newStartBit)
  } finally {
    isProcessingDrop.value = false
    dragExtraRows.value = 0
  }
}

function handleGlobalMouseUp(e) {
  if (!dragState.value) return
  if (e.button !== 0) return
  e.preventDefault()
  processDrop(e.clientX, e.clientY)
}

function onStageMouseUp(nativeEvent) {
  if (!dragState.value) return
  if (nativeEvent.button !== 0) return
  processDrop(nativeEvent.clientX, nativeEvent.clientY)
}

function onStageClick() {
  ui.selectedSignalName = null
}

// ── Watch selectedMsgId → clear selection ──
watch(() => store.selectedMsgId, () => {
  ui.selectedSignalName = null
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

</style>
