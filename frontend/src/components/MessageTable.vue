<template>
  <div class="message-area">
    <div class="center-header">
      <div class="center-title">
        {{ t('msgtable.allMessages') }} · {{ store.messages.length }} {{ t('msgtable.unit') }}
      </div>
      <div class="toolbar">
        <button class="btn" @click="addMessage">{{ t('msgtable.add') }}</button>
        <div class="col-toggle-wrap" ref="colToggleRef">
          <button class="btn" @click.stop="showColMenu = !showColMenu">{{ t('msgtable.columnSettings') }} ▾</button>
          <div v-if="showColMenu" class="col-dropdown" @click.stop>
            <label v-for="col in toggleableColumns" :key="col.key" class="col-dropdown-item">
              <input type="checkbox" :checked="ui.isMsgColumnVisible(col.key)"
                     @change="ui.toggleMsgColumnVisibility(col.key)">
              {{ t(col.i18n) }}
            </label>
            <div class="col-dropdown-divider"></div>
            <button class="col-dropdown-reset" @click="resetAll">{{ t('msgtable.resetColumns') }}</button>
          </div>
        </div>
      </div>
    </div>

    <div class="table-wrap">
      <div v-if="store.messages.length === 0" class="empty">{{ t('msgtable.empty') }}</div>
      <table v-else class="message-table" ref="tableRef" @keydown="onCellKeyDown">
        <colgroup>
          <col v-for="col in visibleColumns" :key="col.key"
               :style="{ width: getColumnPct(col) + '%' }">
        </colgroup>
        <thead>
          <tr>
            <th v-for="(col, ci) in visibleColumns" :key="col.key">
              <span class="th-label">{{ col.i18n ? t(col.i18n) : '' }}</span>
              <span v-if="ci < visibleColumns.length - 1"
                    class="resize-handle"
                    @mousedown.stop="startResize(ci, $event)"></span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(m, idx) in store.messages" :key="m.id"
              :class="{ selected: store.selectedMsgId === m.id }"
              @mousedown="selectRow(m.id)"
              @dblclick="jumpToSignals(m.id)">
            <td v-for="col in visibleColumns" :key="col.key" :class="{ 'col-idx': col.key === 'msg_idx' }">
              <template v-if="col.key === 'msg_idx'"><span class="idx-label">{{ idx }}</span></template>
              <template v-else-if="col.key === 'msg_id'"><input class="mono" v-lazy-value="toHex(m.id)" @blur="e => update('id', parseHex(e.target.value))"></template>
              <template v-else-if="col.key === 'msg_name'"><input v-lazy-value="m.name" @blur="e => update('name', e.target.value)"></template>
              <template v-else-if="col.key === 'msg_dlc'"><input class="mono" type="number" v-lazy-value="m.dlc" @blur="e => update('dlc', parseInt(e.target.value))"></template>
              <template v-else-if="col.key === 'msg_cycle'"><input class="mono" type="number" v-lazy-value="m.cycle_time" @blur="e => update('cycle_time', parseInt(e.target.value))"></template>
              <template v-else-if="col.key === 'msg_fd'">
                <select :value="String(m.is_fd)" @change="e => update('is_fd', e.target.value === 'true')">
                  <option value="false">CAN</option>
                  <option value="true">CAN FD</option>
                </select>
              </template>
              <template v-else-if="col.key === 'msg_actions'"><button class="action-delete" @click.stop="deleteMessage(m.id)" title="删除">×</button></template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useMessagesStore } from '../stores/messages.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'
import { vLazyValue } from '../directives/lazyValue.js'

const COLUMNS = [
  { key: 'msg_idx',     i18n: 'msgtable.thIdx',     toggleable: false, defaultPct: 3  },
  { key: 'msg_id',      i18n: 'msgtable.thId',      toggleable: false, defaultPct: 10 },
  { key: 'msg_name',    i18n: 'msgtable.thName',    toggleable: false, defaultPct: 18 },
  { key: 'msg_dlc',     i18n: 'msgtable.thDlc',     toggleable: true,  defaultPct: 6  },
  { key: 'msg_cycle',   i18n: 'msgtable.thCycle',   toggleable: true,  defaultPct: 8  },
  { key: 'msg_fd',      i18n: 'msgtable.thFd',      toggleable: true,  defaultPct: 7  },
  { key: 'msg_actions', i18n: null,                 toggleable: false, defaultPct: 4  },
]

const store = useEditorStore()
const messages = useMessagesStore()
const ui = useUiStore()

// ── 列显隐 + 列宽 ──
const visibleColumns = computed(() =>
  COLUMNS.filter(col => !col.toggleable || ui.isMsgColumnVisible(col.key))
)
const toggleableColumns = computed(() => COLUMNS.filter(c => c.toggleable))

function getColumnPct(col) {
  return ui.getMsgColumnWidth(col.key, col.defaultPct)
}

const showColMenu = ref(false)
const colToggleRef = ref(null)
const tableRef = ref(null)

function resetAll() {
  ui.resetMsgColumnVisibility()
  ui.resetMsgColumnWidths()
  showColMenu.value = false
}

function onDocClick(e) {
  if (showColMenu.value && colToggleRef.value && !colToggleRef.value.contains(e.target)) {
    showColMenu.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

// ── 列宽拖拽 ──
let resizeState = null

function startResize(colIndex, e) {
  e.preventDefault()
  const cols = visibleColumns.value
  const col = cols[colIndex]
  const nextCol = cols[colIndex + 1]
  if (!nextCol) return

  const curPct = ui.getMsgColumnWidth(col.key, col.defaultPct)
  const nextPct = ui.getMsgColumnWidth(nextCol.key, nextCol.defaultPct)
  const tableWidth = document.querySelector('.message-table').getBoundingClientRect().width

  resizeState = { col, nextCol, colIndex, startX: e.clientX, curPct, nextPct, tableWidth }
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onResize(e) {
  if (!resizeState) return
  const deltaPct = ((e.clientX - resizeState.startX) / resizeState.tableWidth) * 100
  const MIN = 2
  let newCur = Math.max(MIN, resizeState.curPct + deltaPct)
  let newNext = resizeState.nextPct - (newCur - resizeState.curPct)
  if (newNext < MIN) { newNext = MIN; newCur = resizeState.curPct + resizeState.nextPct - MIN }

  const colEls = document.querySelectorAll('.message-table colgroup col')
  if (colEls[resizeState.colIndex]) colEls[resizeState.colIndex].style.width = newCur + '%'
  if (colEls[resizeState.colIndex + 1]) colEls[resizeState.colIndex + 1].style.width = newNext + '%'
}

function stopResize(e) {
  if (!resizeState) return
  const deltaPct = ((e.clientX - resizeState.startX) / resizeState.tableWidth) * 100
  const MIN = 2
  let newCur = Math.max(MIN, resizeState.curPct + deltaPct)
  let newNext = resizeState.nextPct - (newCur - resizeState.curPct)
  if (newNext < MIN) { newNext = MIN; newCur = resizeState.curPct + resizeState.nextPct - MIN }

  const widths = { ...ui.msgColumnWidths }
  widths[resizeState.col.key] = Math.round(newCur * 100) / 100
  widths[resizeState.nextCol.key] = Math.round(newNext * 100) / 100
  ui.setMsgColumnWidths(widths)

  resizeState = null
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// 列显隐时宽度归一化
watch(() => ui.msgHiddenColumns, () => {
  const visible = visibleColumns.value
  if (!visible.length) return
  const total = visible.reduce((s, c) => s + ui.getMsgColumnWidth(c.key, c.defaultPct), 0)
  if (Math.abs(total - 100) > 0.1) {
    const scale = 100 / total
    const widths = { ...ui.msgColumnWidths }
    for (const c of visible) {
      widths[c.key] = Math.round(ui.getMsgColumnWidth(c.key, c.defaultPct) * scale * 100) / 100
    }
    ui.setMsgColumnWidths(widths)
  }
}, { deep: true })

// ── 行操作 ──
function selectRow(id) {
  messages.selectMessage(id)
}

function addMessage() {
  messages.addMessage()
}

function update(field, value) {
  messages.updateMessageField(field, value).catch(() => {})
}

function deleteMessage(id) {
  messages.deleteMessage(id)
}

function jumpToSignals(id) {
  messages.selectMessage(id)
  ui.switchCenterTab('signals')
}

// ── 方向键单元格导航 ──
const NON_NAVIGABLE_COLS = new Set(['msg_idx', 'msg_actions'])

function getCellPosition(el) {
  const td = el.closest('td')
  if (!td) return null
  const tr = td.parentElement
  if (!tr || tr.tagName !== 'TR') return null
  const tbody = tr.parentElement
  if (!tbody || tbody.tagName !== 'TBODY') return null
  const rowIdx = Array.from(tbody.children).indexOf(tr)
  return { rowIdx, colIdx: td.cellIndex }
}

function getCellEditor(rowIdx, colIdx) {
  const table = tableRef.value
  if (!table) return null
  const tbody = table.tBodies[0]
  if (!tbody) return null
  const row = tbody.rows[rowIdx]
  if (!row) return null
  const cell = row.cells[colIdx]
  if (!cell) return null
  return cell.querySelector('input:not([readonly]), select')
}

function findNavigableCol(colIdx, direction) {
  const cols = visibleColumns.value
  let i = colIdx + direction
  while (i >= 0 && i < cols.length) {
    if (!NON_NAVIGABLE_COLS.has(cols[i].key)) return i
    i += direction
  }
  return -1
}

function onCellKeyDown(e) {
  const NAV_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])
  if (!NAV_KEYS.has(e.key)) return

  const el = e.target
  if (el.tagName !== 'INPUT' && el.tagName !== 'SELECT') return
  if (!tableRef.value?.contains(el)) return

  const pos = getCellPosition(el)
  if (!pos) return

  const cols = visibleColumns.value
  const totalRows = store.messages.length
  let { rowIdx, colIdx } = pos
  let targetRow = rowIdx
  let targetCol = colIdx

  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    if (el.tagName === 'INPUT') {
      const supportsSelection = el.type === 'text' || el.type === 'search' || el.type === 'url' || el.type === 'tel' || el.type === 'password' || el.type === ''
      if (supportsSelection) {
        if (e.key === 'ArrowLeft' && el.selectionStart > 0) return
        if (e.key === 'ArrowRight' && el.selectionEnd < el.value.length) return
      }
    }
    const dir = e.key === 'ArrowLeft' ? -1 : 1
    const nextCol = findNavigableCol(colIdx, dir)
    if (nextCol < 0) return
    targetCol = nextCol
  }

  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    const dir = e.key === 'ArrowUp' ? -1 : 1
    targetRow = rowIdx + dir
    if (targetRow < 0 || targetRow >= totalRows) return
    if (NON_NAVIGABLE_COLS.has(cols[colIdx]?.key)) {
      const nextCol = findNavigableCol(colIdx, 1)
      if (nextCol < 0) return
      targetCol = nextCol
    }
  }

  e.preventDefault()
  const target = getCellEditor(targetRow, targetCol)
  if (!target) return
  target.focus()
  if (target.tagName === 'INPUT') target.select()
  target.closest('tr')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  const targetMsg = store.messages[targetRow]
  if (targetMsg) messages.selectMessage(targetMsg.id)
}
</script>

<style scoped>
.message-area { display: flex; flex-direction: column; flex: 1; min-height: 0; }

.center-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.center-title {
  font-size: 13px;
  color: var(--text-dim);
}
.center-title strong { color: var(--text); font-weight: 600; }

.toolbar { display: flex; gap: 6px; }

.btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.btn:hover { background: var(--bg-hover); }

.table-wrap { flex: 1 1 auto; overflow: auto; padding: 8px; min-height: 120px; }

.empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.message-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
}
.message-table th {
  position: relative;
  text-align: left;
  padding: 6px 8px;
  color: var(--text-muted);
  font-weight: 500;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.th-label { overflow: hidden; text-overflow: ellipsis; }
.message-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.message-table tr:nth-child(even) { background: var(--signal-bg-alt); }
.message-table tr:hover { background: var(--signal-bg); }

.message-table input {
  width: 100%;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text);
  padding: 3px 5px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.message-table select {
  width: 100%;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text);
  padding: 3px 5px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
  cursor: pointer;
}
.message-table input:focus,
.message-table select:focus {
  background: var(--bg-raised);
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in oklch, var(--accent) 40%, transparent);
}
.message-table input.mono { font-family: var(--font-mono); }
.message-table input[type="number"]::-webkit-inner-spin-button,
.message-table input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.message-table input[type="number"] {
  -moz-appearance: textfield;
}
.message-table .idx-label {
  display: block;
  text-align: center;
  opacity: 0.45;
  font-size: 11px;
  font-family: var(--font-mono);
  user-select: none;
  cursor: pointer;
  line-height: 1.8;
}
.message-table tr:hover .idx-label { opacity: 0.7; }
.message-table tr.selected .idx-label { opacity: 1; font-weight: 600; }

.message-table tbody tr { cursor: pointer; }

.action-delete {
  background: transparent;
  border: none;
  color: var(--danger);
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
}
.action-delete:hover { color: oklch(0.75 0.15 25); }

/* 拖拽手柄 */
.resize-handle {
  position: absolute;
  top: 0; right: 0;
  width: 20px; height: 100%;
  cursor: col-resize;
  z-index: 4;
  user-select: none;
}
.resize-handle::after {
  content: '';
  position: absolute;
  top: 25%; right: 5px;
  width: 2px; height: 50%;
  border-radius: 1px;
  background: var(--border);
}
.resize-handle:hover::after,
.resize-handle.active::after { background: var(--accent); }

/* 列显隐下拉菜单 */
.col-toggle-wrap { position: relative; }
.col-dropdown {
  position: absolute;
  top: 100%; right: 0;
  margin-top: 4px;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 6px 0;
  min-width: 140px;
  z-index: 20;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
.col-dropdown-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
}
.col-dropdown-item:hover { background: var(--bg-hover); }
.col-dropdown-divider { height: 1px; background: var(--border); margin: 4px 0; }
.col-dropdown-reset {
  display: block;
  width: 100%;
  background: none;
  border: none;
  color: var(--accent);
  font-size: 12px;
  padding: 4px 12px;
  text-align: left;
  cursor: pointer;
}
.col-dropdown-reset:hover { background: var(--bg-hover); }

/* 选中行高亮 */
.message-table tr.selected {
  background: color-mix(in oklch, var(--accent) 15%, transparent) !important;
}
.message-table tr.selected .col-idx {
  border-left: 3px solid var(--accent);
}
</style>
