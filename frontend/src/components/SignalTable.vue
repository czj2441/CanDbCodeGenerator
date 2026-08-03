<template>
  <div class="signal-area">
    <div class="center-header">
      <div class="center-title">
        <template v-if="msg">
          <strong>{{ msg.name || t('msglist.unnamed') }}</strong>
          — {{ toHex(msg.id) }} · {{ signalCount }} {{ signalCount === 1 ? t('status.signal') : t('status.signals') }}
        </template>
        <template v-else>{{ t('signal.selectMessage') }}</template>
      </div>
      <div v-if="msg" class="toolbar">
        <button class="btn" @click="addSignal">{{ t('signal.add') }}</button>
        <button class="btn btn-accent" @click="ui.batchModalOpen = true">{{ t('signal.batch') }}</button>
        <button class="btn" @click="ui.toggleLayoutView()">{{ t('layout.viewLayout') }}</button>
        <div class="col-toggle-wrap" ref="colToggleRef">
          <button class="btn" @click.stop="showColMenu = !showColMenu">{{ t('signal.columnSettings') }} ▾</button>
          <div v-if="showColMenu" class="col-dropdown" @click.stop>
            <label v-for="col in toggleableColumns" :key="col.key" class="col-dropdown-item">
              <input type="checkbox" :checked="ui.isColumnVisible(col.key)"
                     @change="ui.toggleColumnVisibility(col.key)">
              {{ t(col.i18n) }}
            </label>
            <div class="col-dropdown-divider"></div>
            <button class="col-dropdown-reset" @click="resetAll">{{ t('signal.resetColumns') }}</button>
          </div>
        </div>
        <button class="btn btn-danger" @click="deleteMsg">{{ t('signal.deleteMsg') }}</button>
      </div>
    </div>

    <div class="table-wrap">
      <div v-if="!msg" class="empty" v-html="t('signal.selectMessage')">
      </div>
      <div v-else-if="signalCount === 0" class="empty" v-html="t('signal.empty')">
      </div>
      <table v-else class="signal-table" ref="tableRef" @keydown="onCellKeyDown">
        <colgroup>
          <col v-for="col in visibleColumns" :key="col.key"
               :style="{ width: normalizedPcts[col.key] + '%' }">
        </colgroup>
        <thead>
          <tr>
            <th v-for="(col, ci) in visibleColumns" :key="col.key"
                @click="col.sortable !== false ? onHeaderClick(col.sortField || col.key) : null"
                :class="{ 'th-sortable': col.sortable !== false }">
              <span class="th-label">{{ col.i18n ? t(col.i18n) : '' }}</span>
              <span v-if="col.sortable !== false && getSortIconText(col.sortField || col.key)" class="sort-icon">{{ getSortIconText(col.sortField || col.key) }}</span>
              <span v-if="ci < visibleColumns.length - 1"
                    class="resize-handle"
                    @mousedown.stop="startResize(ci, $event)"></span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="sig in sortedSignals" :key="sig.name" :data-sig-id="sig.name" :class="{ 'has-error': errorNames.has(sig.name), 'selected': selectedSigName === sig.name }" @mousedown="handleRowMouseDown(sig.name, $event)">
            <td v-for="col in visibleColumns" :key="col.key">
              <template v-if="col.key === 'name'"><input v-lazy-value="sig.name" @blur="e => update(sig.name, 'name', e.target.value)"></template>
              <template v-else-if="col.key === 'start'"><input class="mono" type="number" v-lazy-value="displayStartBit(sig)" @blur="e => updateStartBit(sig, parseInt(e.target.value)||0)"></template>
              <template v-else-if="col.key === 'length'"><input class="mono" type="number" v-lazy-value="sig.length" @blur="e => update(sig.name, 'length', parseInt(e.target.value))"></template>
              <template v-else-if="col.key === 'order'">
                <select :value="sig.byte_order" @change="e => updateByteOrder(sig, e)">
                  <option value="intel">Intel</option>
                  <option value="motorola">Motorola</option>
                </select>
              </template>
              <template v-else-if="col.key === 'factor'"><input class="mono" type="number" step="any" v-lazy-value="sig.factor" @blur="e => update(sig.name, 'factor', parseFloat(e.target.value))"></template>
              <template v-else-if="col.key === 'offset'"><input class="mono" type="number" step="any" v-lazy-value="sig.offset" @blur="e => update(sig.name, 'offset', parseFloat(e.target.value))"></template>
              <template v-else-if="col.key === 'min'"><input class="mono" type="number" step="any" v-lazy-value="sig.min_val" @blur="e => update(sig.name, 'min_val', parseFloat(e.target.value))"></template>
              <template v-else-if="col.key === 'max'"><input class="mono" type="number" step="any" v-lazy-value="sig.max_val" @blur="e => update(sig.name, 'max_val', parseFloat(e.target.value))"></template>
              <template v-else-if="col.key === 'unit'"><input v-lazy-value="sig.unit" @blur="e => update(sig.name, 'unit', e.target.value)"></template>
              <template v-else-if="col.key === 'comment'"><input v-lazy-value="sig.comment" @blur="e => update(sig.name, 'comment', e.target.value)"></template>
              <template v-else-if="col.key === 'valTable'">
                <span v-if="sig.value_table_name" class="vt-tag" @click.stop="ui.valueTableFocusName = sig.value_table_name; ui.switchCenterTab('valtables')">{{ sig.value_table_name }}</span>
                <span v-else class="vt-none">-</span>
              </template>
              <template v-else-if="col.key === 'actions'"><button class="action-delete" @click.stop="signals.deleteSignal(sig.name)" title="删除">×</button></template>
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
import { useSignalsStore } from '../stores/signals.js'
import { useMessagesStore } from '../stores/messages.js'
import { useClipboardStore } from '../stores/clipboard.js'
import { useUndoRedoStore } from '../stores/undoRedo.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex } from '../utils/format.js'
import { toDisplayStartBit, toStorageStartBit } from '../utils/signalLayout.js'
import { t } from '../i18n.js'
import { vLazyValue } from '../directives/lazyValue.js'
import { sortByField, toggleSort, getSortIcon } from '../utils/sortHelper.js'
import { useColumnResize } from '../composables/useColumnResize.js'

const COLUMNS = [
  { key: 'name',    i18n: 'signal.thName',     toggleable: false, defaultPct: 14, sortField: 'name'  },
  { key: 'start',   i18n: 'signal.thStart',    toggleable: true,  defaultPct: 7,  sortField: 'start_bit' },
  { key: 'length',  i18n: 'signal.thLen',      toggleable: true,  defaultPct: 5,  sortField: 'length' },
  { key: 'order',   i18n: 'signal.thOrder',    toggleable: true,  defaultPct: 8,  sortable: false },
  { key: 'factor',  i18n: 'signal.thFactor',   toggleable: true,  defaultPct: 7,  sortField: 'factor' },
  { key: 'offset',  i18n: 'signal.thOffset',   toggleable: true,  defaultPct: 7,  sortField: 'offset' },
  { key: 'min',     i18n: 'signal.thMin',      toggleable: true,  defaultPct: 7,  sortField: 'min_val' },
  { key: 'max',     i18n: 'signal.thMax',      toggleable: true,  defaultPct: 7,  sortField: 'max_val' },
  { key: 'unit',    i18n: 'signal.thUnit',     toggleable: true,  defaultPct: 6,  sortField: 'unit' },
  { key: 'comment', i18n: 'signal.thComment',  toggleable: true,  defaultPct: 26, sortField: 'comment' },
  { key: 'valTable', i18n: 'signal.thValTable', toggleable: true,  defaultPct: 8,  sortField: 'value_table_name' },
  { key: 'actions', i18n: null,                toggleable: false, defaultPct: 3,  sortable: false },
]

const store = useEditorStore()
const signals = useSignalsStore()
const messages = useMessagesStore()
const clipboard = useClipboardStore()
const undoRedo = useUndoRedoStore()
const ui = useUiStore()

const msg = computed(() => store.selectedMessage)
// ✅ 使用单一数据源：直接代理 ui.selectedSignalName，避免双写
const selectedSigName = computed({
  get: () => ui.selectedSignalName,
  set: (val) => { ui.selectedSignalName = val }
})

// 切换报文时清除选中
watch(msg, () => {
  ui.selectedSignalName = null
})

const errorNames = computed(() => {
  const set = new Set()
  for (const err of store.signalErrors) {
    if (err.signal_name) set.add(err.signal_name)
    if (err.conflicts_name) set.add(err.conflicts_name)
  }
  return set
})

// ── 信号数量 + 排序后的信号数组 ──
const signalCount = computed(() => {
  if (!msg.value?.signals) return 0
  return Object.keys(msg.value.signals).length
})

const sortedSignals = computed(() => {
  if (!msg.value?.signals) return []
  const arr = Object.values(msg.value.signals)
  return sortByField(arr, ui.signalSortField, ui.signalSortDir)
})

function onHeaderClick(field) {
  if (consumeJustResized()) return
  const result = toggleSort(ui.signalSortField, ui.signalSortDir, field)
  ui.setSignalSort(result.field, result.dir)
}

function getSortIconText(field) {
  return getSortIcon(field, ui.signalSortField, ui.signalSortDir)
}

// ── 列显隐 + 列宽 ──
const visibleColumns = computed(() =>
  COLUMNS.filter(col => !col.toggleable || ui.isColumnVisible(col.key))
)
const toggleableColumns = computed(() => COLUMNS.filter(c => c.toggleable))

const showColMenu = ref(false)
const colToggleRef = ref(null)
const tableRef = ref(null)

const { normalizedPcts, startResize, consumeJustResized } = useColumnResize(tableRef, visibleColumns, {
  getColumnWidth: (key, def) => ui.getColumnWidth(key, def),
  getColumnWidths: () => ui.columnWidths,
  setColumnWidths: (w) => ui.setColumnWidths(w),
  hiddenColumns: () => ui.hiddenColumns,
})

function resetAll() {
  ui.resetColumnVisibility()
  ui.resetColumnWidths()
  showColMenu.value = false
}

function onDocClick(e) {
  if (showColMenu.value && colToggleRef.value && !colToggleRef.value.contains(e.target)) {
    showColMenu.value = false
  }
}

function handleRowMouseDown(sigName, event) {
  // ⚠️ 维护注意：新增交互元素类型（如自定义 datepicker/autocomplete）时，
  // 需同步扩展下面的 INTERACTIVE_TAGS 集合，否则会被误判为“空白区域”触发 toggle。
  const INTERACTIVE_TAGS = new Set(['INPUT', 'SELECT'])
  const isInteractive = INTERACTIVE_TAGS.has(event.target.tagName)

  if (isInteractive) {
    // 点击交互元素：确保选中该信号（已选中则保持，不切换）
    if (ui.selectedSignalName !== sigName) {
      ui.selectedSignalName = sigName
    }
  } else {
    // 点击空白区域：切换选中状态
    ui.selectedSignalName = ui.selectedSignalName === sigName ? null : sigName
  }
}

function onKeyDown(e) {
  const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable
  const ctrl = e.ctrlKey || e.metaKey
  if (!ctrl) return

  if (e.key === 'c' && !isInput) {
    e.preventDefault()
    if (ui.selectedSignalName) {
      clipboard.copySignal(ui.selectedSignalName)
    }
  } else if (e.key === 'v' && !isInput) {
    e.preventDefault()
    clipboard.pasteSignal()
  } else if (e.key === 'z' && !isInput) {
    e.preventDefault()
    undoRedo.undo()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  document.addEventListener('click', onDocClick)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  document.removeEventListener('click', onDocClick)
})

function addSignal() {
  signals.addSignal({})
}

function update(sigName, field, value) {
  signals.updateSignal(sigName, field, value).catch(() => {})
}

function updateByteOrder(sig, e) {
  const oldOrder = sig.byte_order
  signals.updateSignal(sig.name, 'byte_order', e.target.value)
    .catch(() => { e.target.value = oldOrder })
}

/**
 * 显示用的起始位：Motorola 信号显示 LSB，Intel 信号显示原始 start_bit
 */
function displayStartBit(sig) {
  return toDisplayStartBit(sig.start_bit, sig.length, sig.byte_order)
}

/**
 * 编辑起始位：Motorola 信号将用户输入的 display start bit 转换为 storage start bit (MSB)
 * 转换失败时仍发送请求，由后端校验，错误在 DataErrorList 展示
 */
function updateStartBit(sig, displayValue) {
  const msbValue = toStorageStartBit(displayValue, sig.length, sig.byte_order, 63, sig.start_bit)
  const valueToSend = msbValue >= 0 ? msbValue : -1
  signals.updateSignal(sig.name, 'start_bit', valueToSend).catch(() => {})
}

function deleteMsg() {
  if (store.selectedMsgId == null) return
  messages.deleteMessage(store.selectedMsgId)
}

// ── 方向键单元格导航 ──
const NON_NAVIGABLE_COLS = new Set(['actions'])

/** 从当前 DOM 元素定位所在行列索引 */
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

/** 获取目标单元格内的可编辑元素 */
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

/** 从当前列出发，沿 direction 方向查找下一个可导航列 */
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
  const totalRows = sortedSignals.value?.length ?? 0
  let { rowIdx, colIdx } = pos
  let targetRow = rowIdx
  let targetCol = colIdx

  // ── 水平导航（左右） ──
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    // 对 input：仅在光标处于边界时才导航
    if (el.tagName === 'INPUT') {
      // type="number" 等不支持 selectionStart/End，无光标概念，始终允许导航
      const supportsSelection = el.type === 'text' || el.type === 'search' || el.type === 'url' || el.type === 'tel' || el.type === 'password' || el.type === ''
      if (supportsSelection) {
        if (e.key === 'ArrowLeft' && el.selectionStart > 0) return
        if (e.key === 'ArrowRight' && el.selectionEnd < el.value.length) return
      }
    }
    // select 元素：左右键同样导航（选项切换通过鼠标点击完成）

    const dir = e.key === 'ArrowLeft' ? -1 : 1
    const nextCol = findNavigableCol(colIdx, dir)
    if (nextCol < 0) return
    targetCol = nextCol
  }

  // ── 垂直导航（上下） ──
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    // select 元素：上下键同样导航（选项切换通过鼠标点击完成）

    const dir = e.key === 'ArrowUp' ? -1 : 1
    targetRow = rowIdx + dir
    if (targetRow < 0 || targetRow >= totalRows) return

    // 若当前列不可编辑，跳到最近的可编辑列
    if (NON_NAVIGABLE_COLS.has(cols[colIdx]?.key)) {
      const nextCol = findNavigableCol(colIdx, 1)
      if (nextCol < 0) return
      targetCol = nextCol
    }
  }

  e.preventDefault()

  // ── 聚焦目标 ──
  const target = getCellEditor(targetRow, targetCol)
  if (!target) return

  target.focus()
  if (target.tagName === 'INPUT') target.select()

  // 确保目标行在视口内
  target.closest('tr')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })

  // 同步行选中状态
  const targetSig = sortedSignals.value[targetRow]
  if (targetSig) ui.selectedSignalName = targetSig.name
}
</script>

<style scoped>
.signal-area { display: flex; flex-direction: column; flex: 1; min-height: 0; }

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
.btn-accent { background: var(--accent); color: oklch(0.12 0.01 155); border-color: transparent; font-weight: 600; }
.btn-danger { background: oklch(0.22 0.05 25); color: oklch(0.85 0.05 25); border-color: oklch(0.35 0.08 25); }

.table-wrap { flex: 1 1 auto; overflow: auto; padding: 8px; min-height: 120px; }

.empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.signal-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
}
.signal-table th {
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
.signal-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.signal-table tr:nth-child(even) { background: var(--signal-bg-alt); }
.signal-table tr:hover { background: var(--signal-bg); }

.signal-table input {
  width: 100%;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text);
  padding: 3px 5px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.signal-table select {
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
.signal-table input:focus,
.signal-table select:focus {
  background: var(--bg-raised);
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in oklch, var(--accent) 40%, transparent);
}
.signal-table input.mono { font-family: var(--font-mono); }
/* 隐藏数值输入框的上下按钮 */
.signal-table input[type="number"]::-webkit-inner-spin-button,
.signal-table input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.signal-table input[type="number"] {
  -moz-appearance: textfield;
}
.th-sortable { cursor: pointer; user-select: none; }
.th-sortable:hover { color: var(--text); }
.sort-icon { font-size: 10px; margin-left: 2px; }

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
.signal-table tr.selected {
  background: color-mix(in oklch, var(--accent) 15%, transparent) !important;
}
.signal-table tr.selected td:first-child {
  border-left: 3px solid var(--accent);
}

/* 冲突行高亮 */
.signal-table tr.has-error {
  background: color-mix(in oklch, var(--danger) 12%, transparent) !important;
}
.signal-table tr.has-error td:first-child {
  border-left: 3px solid var(--danger);
}
.signal-table tr.has-error input {
  border-color: color-mix(in oklch, var(--danger) 40%, transparent);
  color: var(--text);
}

/* 同时选中和报错：以 danger 为主，但保留 accent 左边框提示 */
.signal-table tr.selected.has-error {
  background: color-mix(in oklch, var(--danger) 18%, transparent) !important;
}
.signal-table tr.selected.has-error td:first-child {
  border-left: 3px solid var(--danger);
}

/* 错误跳转高亮闪烁 */
@keyframes highlight-flash-anim {
  0%, 100% { background: inherit; }
  50% { background: color-mix(in oklch, var(--accent) 30%, transparent); }
}
.signal-table tr.highlight-flash {
  animation: highlight-flash-anim 0.6s ease-in-out 3;
}

/* ── 值描述表标签 ── */
.vt-tag {
  display: inline-block;
  background: color-mix(in oklch, var(--accent) 15%, transparent);
  color: var(--accent);
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vt-tag:hover { background: color-mix(in oklch, var(--accent) 25%, transparent); }
.vt-none { color: var(--text-muted); }
</style>
