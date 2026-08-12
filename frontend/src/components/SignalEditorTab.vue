<template>
  <SignalLayoutVisualizer v-if="ui.layoutViewMode" :msg-id="effectiveMsgId" />
  <template v-else>
  <div class="signal-area">
    <div class="center-header">
      <div class="center-title">
        <template v-if="msg">
          <strong>{{ toHex(msg.id) }}</strong>
          {{ msg.name || t('msglist.unnamed') }}
          · {{ signalCount }} {{ signalCount === 1 ? t('status.signal') : t('status.signals') }}
        </template>
        <template v-else>{{ t('signal.selectMessage') }}</template>
      </div>
      <div v-if="msg" class="toolbar">
        <button v-if="!store.readOnly" class="btn" @click="addSignal">{{ t('signal.add') }}</button>
        <button v-if="!store.readOnly" class="btn btn-accent" @click="ui.batchModalOpen = true">{{ t('signal.batch') }}</button>
        <template v-if="!store.readOnly && multiSelect.isMultiSelect.value">
          <button class="btn" @click="batchEditModalOpen = true">{{ t('multiselect.batchEdit') }} ({{ multiSelect.selectedCount.value }})</button>
          <button class="btn btn-danger" @click="batchDeleteSelected">{{ t('multiselect.batchDelete') }}</button>
        </template>
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

      </div>
    </div>

    <div class="table-wrap">
      <div v-if="!msg" class="empty" v-html="t('signal.selectMessage')">
      </div>
      <div v-else-if="signalCount === 0" class="empty" v-html="t('signal.empty')">
      </div>
      <table v-else class="signal-table data-table" ref="tableRef" @keydown="onCellKeyDown">
        <colgroup>
          <col v-for="col in visibleColumns" :key="col.key"
               :style="{ width: normalizedPcts[col.key] + '%' }">
        </colgroup>
        <thead>
          <tr>
            <th v-for="(col, ci) in visibleColumns" :key="col.key"
                @click="col.key !== '_cb' && col.sortable !== false ? onHeaderClick(col.sortField || col.key) : null"
                :class="{ 'th-sortable': col.key !== '_cb' && col.sortable !== false }"
                @mousedown="col.key === '_cb' ? onHeaderCbMouseDown($event) : null">
              <template v-if="col.key === '_cb'">
                <input type="checkbox" :checked="multiSelect.allSelected.value"
                       :indeterminate.prop="multiSelect.someSelected.value"
                       @change="multiSelect.toggleAll()" @click.stop>
              </template>
              <template v-else>
                <span class="th-label">{{ col.i18n ? t(col.i18n) : '' }}</span>
                <span v-if="col.sortable !== false && getSortIconText(col.sortField || col.key)" class="sort-icon">{{ getSortIconText(col.sortField || col.key) }}</span>
              </template>
              <span v-if="col.key !== '_cb' && ci < visibleColumns.length - 1"
                    class="resize-handle"
                    @mousedown.stop="startResize(ci, $event)"></span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(sig, sigIdx) in sortedSignals" :key="sig.name" :data-sig-id="sig.name" :class="{ 'has-error': errorNames.has(sig.name), 'selected': selectedSigName === sig.name, 'multi-selected': multiSelect.selectedKeys.value.has(sig.name) }" @mousedown="handleRowMouseDown(sig.name, sigIdx, $event)">
            <td v-for="col in visibleColumns" :key="col.key"
                :class="{ 'cb-cell': col.key === '_cb' }"
                @mousedown="col.key === '_cb' ? onCbCellMouseDown(sig.name, $event) : null">
              <template v-if="col.key === '_cb'">
                <input type="checkbox" :checked="multiSelect.selectedKeys.value.has(sig.name)"
                       @click.stop @change="multiSelect.toggleCheckbox(sig.name)">
              </template>
              <template v-else-if="col.key === 'name'"><input v-lazy-value="sig.name" @blur="e => isCellEditable(sig.name) && update(sig.name, 'name', e.target.value)" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(sig.name)" data-field="name"></template>
              <template v-else-if="col.key === 'start'"><input class="mono" type="number" v-lazy-value="displayStartBit(sig)" @blur="e => isCellEditable(sig.name) && updateStartBit(sig, parseInt(e.target.value)||0)" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(sig.name)" data-field="start"></template>
              <template v-else-if="col.key === 'length'"><input class="mono" type="number" v-lazy-value="sig.length" @blur="e => isCellEditable(sig.name) && update(sig.name, 'length', parseInt(e.target.value))" :readonly="!isCellEditable(sig.name)" data-field="length"></template>
              <template v-else-if="col.key === 'order'">
                <select :value="sig.byte_order" @change="e => updateByteOrder(sig, e)" :disabled="store.readOnly" data-field="order">
                  <option value="intel">Intel</option>
                  <option value="motorola">Motorola</option>
                </select>
              </template>
              <template v-else-if="col.key === 'factor'"><input class="mono" type="number" step="any" v-lazy-value="sig.factor" @blur="e => isCellEditable(sig.name) && update(sig.name, 'factor', parseFloat(e.target.value))" :readonly="!isCellEditable(sig.name)" data-field="factor"></template>
              <template v-else-if="col.key === 'offset'"><input class="mono" type="number" step="any" v-lazy-value="sig.offset" @blur="e => isCellEditable(sig.name) && update(sig.name, 'offset', parseFloat(e.target.value))" :readonly="!isCellEditable(sig.name)" data-field="offset"></template>
              <template v-else-if="col.key === 'min'"><input class="mono" type="number" step="any" v-lazy-value="sig.min_val" @blur="e => isCellEditable(sig.name) && update(sig.name, 'min_val', parseFloat(e.target.value))" :readonly="!isCellEditable(sig.name)" data-field="min"></template>
              <template v-else-if="col.key === 'max'"><input class="mono" type="number" step="any" v-lazy-value="sig.max_val" @blur="e => isCellEditable(sig.name) && update(sig.name, 'max_val', parseFloat(e.target.value))" :readonly="!isCellEditable(sig.name)" data-field="max"></template>
              <template v-else-if="col.key === 'unit'"><input v-lazy-value="sig.unit" @blur="e => isCellEditable(sig.name) && update(sig.name, 'unit', e.target.value)" :readonly="!isCellEditable(sig.name)" data-field="unit"></template>
              <template v-else-if="col.key === 'comment'"><input v-lazy-value="sig.comment" @blur="e => isCellEditable(sig.name) && update(sig.name, 'comment', e.target.value)" :readonly="!isCellEditable(sig.name)" data-field="comment"></template>
              <template v-else-if="col.key === 'valTable'">
                <select :value="sig.value_table_name || ''" @change="e => updateValueTableRef(sig.name, e.target.value)" :disabled="store.readOnly" data-field="valTable">
                  <option value="">-</option>
                  <option v-for="name in valueTableNames" :key="name" :value="name">{{ name }}</option>
                </select>
              </template>
              <template v-else-if="col.key === 'actions'">
                <button v-if="!store.readOnly" class="action-delete" @click.stop="signals.deleteSignal(sig.name)" title="删除">×</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

  </div>

  <BatchEditModal v-model:visible="batchEditModalOpen"
    :fields="SIGNAL_BATCH_EDIT_FIELDS"
    :selected-count="multiSelect.selectedCount.value"
    @apply="onBatchEditApply" />
  </template>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useCoreStore } from '../stores/coreStore.js'
import { useSignalsStore } from '../stores/signals.js'
import { useClipboardStore } from '../stores/clipboard.js'
import { useUndoRedoStore } from '../stores/undoRedo.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex } from '../utils/format.js'
import { toDisplayStartBit, toStorageStartBit } from '../utils/signalLayout.js'
import { t } from '../i18n.js'
import { vLazyValue } from '../directives/lazyValue.js'
import { sortByField, toggleSort, getSortIcon } from '../utils/sortHelper.js'
import { useColumnResize } from '../composables/useColumnResize.js'
import { useMultiSelect } from '../composables/useMultiSelect.js'
import BatchEditModal from './BatchEditModal.vue'
import SignalLayoutVisualizer from './SignalLayoutVisualizer.vue'

const COLUMNS = [
  { key: '_cb',     i18n: null,               toggleable: false, defaultPct: 2,  sortable: false },
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

const store = useCoreStore()
const signals = useSignalsStore()
const clipboard = useClipboardStore()
const undoRedo = useUndoRedoStore()
const ui = useUiStore()

const props = defineProps({
  // 当来自动态标签页时，强制使用本 tab 的 msgId；否则 fallback 到全局 selectedMsgId
  msgId: { type: Number, default: null },
})

// ── 值描述表名称列表 ──
const valueTableNames = computed(() => Object.keys(store.valueTables).sort())

// ── 双击编辑状态 ──
const editingKey = ref(null) // { sigName, field } | null
function isCellEditable(sigName) {
  if (store.readOnly) return false
  return editingKey.value && editingKey.value.sigName === sigName
}

// 动态 tab 时优先使用 prop，fallback 到全局 selectedMsgId
const effectiveMsgId = computed(() => props.msgId ?? store.selectedMsgId)
const msg = computed(() => {
  if (effectiveMsgId.value == null) return null
  return store.messageCache[effectiveMsgId.value] || null
})
// ✅ 使用单一数据源：直接代理 ui.selectedSignalName，避免双写
const selectedSigName = computed({
  get: () => ui.selectedSignalName,
  set: (val) => { ui.selectedSignalName = val }
})

// 切换报文时清除选中（仅在 effectiveMsgId 真正变化时触发，动态 tab 切换时 prop 不变，不会误清）
watch(effectiveMsgId, () => {
  ui.selectedSignalName = null
  editingKey.value = null
  multiSelect.clearSelection()
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

// ── 多选 ──
const multiSelect = useMultiSelect(
  () => sortedSignals.value,
  { getKey: (sig) => sig.name }
)

// 同步多选 keys 到 uiStore（供右键菜单判断多选状态）
watch(multiSelect.selectedKeys, (keys) => {
  ui.signalMultiKeys = [...keys]
})

// ── 批量编辑 Modal ──
const batchEditModalOpen = ref(false)

const SIGNAL_BATCH_EDIT_FIELDS = [
  { key: 'length',   i18n: 'signal.thLen',    type: 'number', default: 8 },
  { key: 'byte_order', i18n: 'signal.thOrder', type: 'select', default: 'motorola',
    options: [{ value: 'intel', label: 'Intel' }, { value: 'motorola', label: 'Motorola' }] },
  { key: 'factor',   i18n: 'signal.thFactor', type: 'number', default: 1.0 },
  { key: 'offset',   i18n: 'signal.thOffset', type: 'number', default: 0.0 },
  { key: 'min_val',  i18n: 'signal.thMin',    type: 'number', default: 0.0 },
  { key: 'max_val',  i18n: 'signal.thMax',    type: 'number', default: 0.0 },
  { key: 'unit',     i18n: 'signal.thUnit',   type: 'text',   default: '' },
  { key: 'comment',  i18n: 'signal.thComment', type: 'text',  default: '' },
]

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

function onCbCellMouseDown(key, event) {
  event.stopPropagation()
  if (event.target.type === 'checkbox') return
  multiSelect.toggleCheckbox(key)
}

function onHeaderCbMouseDown(event) {
  event.stopPropagation()
  if (event.target.type === 'checkbox') return
  multiSelect.toggleAll()
}

function handleRowMouseDown(sigName, sigIndex, event) {
  // ⚠️ 维护注意：新增交互元素类型（如自定义 datepicker/autocomplete）时，
  // 需同步扩展下面的 INTERACTIVE_TAGS 集合，否则会被误判为"空白区域"触发 toggle。
  const INTERACTIVE_TAGS = new Set(['INPUT', 'SELECT'])

  // 非左键：阻止输入框聚焦，不干扰多选状态（右键菜单由 contextmenu 事件处理）
  if (event.button !== 0) {
    if (INTERACTIVE_TAGS.has(event.target.tagName)) event.preventDefault()
    return
  }

  const targetEl = event.target
  const isInteractive = INTERACTIVE_TAGS.has(targetEl.tagName)

  const isCheckbox = targetEl.type === 'checkbox'

  // Checkbox 点击：不干扰多选状态，交给 @change 处理
  if (isCheckbox) return

  // Ctrl/Shift + Click → 多选（preventDefault 阻止浏览器聚焦 input，避免进入编辑状态）
  if (event.ctrlKey || event.metaKey || event.shiftKey) {
    multiSelect.handleRowClick(sigName, sigIndex, event)
    editingKey.value = null
    if (isInteractive) event.preventDefault()
    return
  }

  // 普通点击：清空多选，走单选逻辑，同时将当前项加入 selectedKeys
  multiSelect.clearSelection()

  // 点击输入/选择元素 → 双击进入编辑模式
  if (isInteractive) {
    if (event.detail >= 2) {
      editingKey.value = { sigName, field: targetEl.dataset.field }
    }
    if (ui.selectedSignalName !== sigName) {
      ui.selectedSignalName = sigName
    }
    multiSelect.handleRowClick(sigName, sigIndex, {})
  } else {
    editingKey.value = null
    if (ui.selectedSignalName === sigName) {
      ui.selectedSignalName = null
    } else {
      ui.selectedSignalName = sigName
      multiSelect.handleRowClick(sigName, sigIndex, {})
    }
  }
}

function onKeyDown(e) {
  const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable
  const ctrl = e.ctrlKey || e.metaKey

  // Escape 退出编辑模式
  if (e.key === 'Escape' && isInput && editingKey.value) {
    editingKey.value = null
    e.target.blur()
    e.preventDefault()
    return
  }

  // Delete 键批量删除
  if (e.key === 'Delete' && !isInput && multiSelect.selectedCount.value > 1) {
    e.preventDefault()
    batchDeleteSelected()
    return
  }

  if (!ctrl) return

  if (e.key === 'c' && !isInput) {
    e.preventDefault()
    if (multiSelect.isMultiSelect.value) {
      clipboard.copySignals(multiSelect.getSelectedKeys())
    } else if (ui.selectedSignalName) {
      clipboard.copySignal(ui.selectedSignalName)
    }
  } else if (e.key === 'x' && !isInput) {
    e.preventDefault()
    if (multiSelect.isMultiSelect.value) {
      clipboard.cutSignals(multiSelect.getSelectedKeys())
      multiSelect.clearSelection()
    } else if (ui.selectedSignalName) {
      clipboard.cutSignal(ui.selectedSignalName)
    }
  } else if (e.key === 'v' && !isInput) {
    e.preventDefault()
    clipboard.pasteSignals()
  } else if (e.key === 'z' && !isInput) {
    e.preventDefault()
    undoRedo.undo()
  } else if (e.key === 'a' && !isInput) {
    e.preventDefault()
    multiSelect.toggleAll()
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
  signals.updateSignal(sigName, field, value, msg.value?.id).catch(() => {})
}

function updateByteOrder(sig, e) {
  const oldOrder = sig.byte_order
  signals.updateSignal(sig.name, 'byte_order', e.target.value, msg.value?.id)
    .catch(() => { e.target.value = oldOrder })
}

function updateValueTableRef(sigName, value) {
  signals.updateSignal(sigName, 'value_table_name', value || '', msg.value?.id).catch(() => {})
}

function batchDeleteSelected() {
  if (multiSelect.selectedCount.value === 0) return
  signals.batchDeleteSignals(multiSelect.getSelectedKeys())
  multiSelect.clearSelection()
}

function onBatchEditApply(fields) {
  if (Object.keys(fields).length === 0) return
  signals.batchUpdateSignals(multiSelect.getSelectedKeys(), fields)
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
  signals.updateSignal(sig.name, 'start_bit', valueToSend, msg.value?.id).catch(() => {})
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
@import './table-styles.css';

.signal-area { display: flex; flex-direction: column; flex: 1; min-height: 0; user-select: none; }

.btn-accent { background: var(--accent); color: oklch(0.12 0.01 155); border-color: transparent; font-weight: 600; }

/* 多选行高亮 */
.signal-table tr.multi-selected {
  background: color-mix(in oklch, var(--accent) 20%, transparent) !important;
}

/* checkbox 列 — 扩大可点击范围 */
.cb-cell { cursor: pointer; }
.signal-table th input[type="checkbox"],
.signal-table td input[type="checkbox"] {
  accent-color: var(--accent);
  cursor: pointer;
  width: 14px;
  height: 14px;
  padding: 0;
}

/* 批量删除按钮 */
.btn-danger {
  background: color-mix(in oklch, var(--danger) 80%, oklch(0.3 0 0));
  color: #fff;
  border-color: transparent;
}
.btn-danger:hover {
  background: color-mix(in oklch, var(--danger) 90%, oklch(0.2 0 0));
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

</style>
