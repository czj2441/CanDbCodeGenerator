<template>
  <div class="message-area">
    <div class="center-header">
      <div class="center-title">
        {{ t('msgtable.allMessages') }} · {{ messageCount }} {{ t('msgtable.unit') }}
      </div>
      <div class="toolbar">
        <button class="btn" @click="addMessage">{{ t('msgtable.add') }}</button>
        <template v-if="multiSelect.isMultiSelect.value">
          <button class="btn" @click="batchEditModalOpen = true">{{ t('multiselect.batchEdit') }} ({{ multiSelect.selectedCount.value }})</button>
          <button class="btn btn-danger" @click="batchDeleteSelected">{{ t('multiselect.batchDelete') }}</button>
        </template>
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
      <div v-if="messageCount === 0" class="empty">{{ t('msgtable.empty') }}</div>
      <table v-else class="message-table data-table" ref="tableRef" @keydown="onCellKeyDown">
        <colgroup>
          <col v-for="col in visibleColumns" :key="col.key"
               :style="{ width: normalizedPcts[col.key] + '%' }">
        </colgroup>
        <thead>
          <tr>
            <th v-for="(col, ci) in visibleColumns" :key="col.key"
                @click="col.key !== '_cb' && col.sortable !== false ? onHeaderClick(col.sortField || col.key) : null"
                :class="{ 'th-sortable': col.key !== '_cb' && col.sortable !== false }">
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
          <tr v-for="(m, mIdx) in sortedMessages" :key="m.id"
              :data-msg-id="m.id"
              :class="{ selected: store.selectedMsgId === m.id, 'multi-selected': multiSelect.selectedKeys.value.has(m.id) }"
              @mousedown="handleRowMouseDown(m.id, mIdx, $event)">
            <td v-for="col in visibleColumns" :key="col.key">
              <template v-if="col.key === '_cb'">
                <input type="checkbox" :checked="multiSelect.selectedKeys.value.has(m.id)"
                       @click.stop @change="multiSelect.toggleCheckbox(m.id)">
              </template>
              <template v-else-if="col.key === 'msg_id'"><input class="mono" v-lazy-value="toHex(m.id)" @blur="e => isCellEditable(m.id) && update(m.id, 'id', parseHex(e.target.value))" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(m.id)"></template>
              <template v-else-if="col.key === 'msg_name'"><input v-lazy-value="m.name" @blur="e => isCellEditable(m.id) && update(m.id, 'name', e.target.value)" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(m.id)"></template>
              <template v-else-if="col.key === 'msg_dlc'"><input class="mono" type="number" v-lazy-value="m.dlc" @blur="e => isCellEditable(m.id) && update(m.id, 'dlc', parseInt(e.target.value))" :readonly="!isCellEditable(m.id)"></template>
              <template v-else-if="col.key === 'msg_cycle'"><input class="mono" type="number" v-lazy-value="m.cycle_time" @blur="e => isCellEditable(m.id) && update(m.id, 'cycle_time', parseInt(e.target.value))" :readonly="!isCellEditable(m.id)"></template>
              <template v-else-if="col.key === 'msg_fd'">
                <select :value="String(m.is_fd)" @change="e => update(m.id, 'is_fd', e.target.value === 'true')">
                  <option value="false">CAN</option>
                  <option value="true">CAN FD</option>
                </select>
              </template>
              <template v-else-if="col.key === 'msg_edit_signals'"><button class="vt-tag" @click.stop="jumpToSignals(m.id)">{{ t('msgtable.editSignals') }}</button></template>
              <template v-else-if="col.key === 'msg_actions'"><button class="action-delete" @click.stop="deleteMessage(m.id)" title="删除">×</button></template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <BatchEditModal v-model:visible="batchEditModalOpen"
    :fields="MSG_BATCH_EDIT_FIELDS"
    :selected-count="multiSelect.selectedCount.value"
    @apply="onBatchEditApply" />
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useMessagesStore } from '../stores/messages.js'
import { useClipboardStore } from '../stores/clipboard.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'
import { vLazyValue } from '../directives/lazyValue.js'

import { sortByField, toggleSort, getSortIcon } from '../utils/sortHelper.js'
import { useColumnResize } from '../composables/useColumnResize.js'
import { useMultiSelect } from '../composables/useMultiSelect.js'
import BatchEditModal from './BatchEditModal.vue'

const COLUMNS = [
  { key: '_cb',         i18n: null,                toggleable: false, defaultPct: 2,  sortable: false },
  { key: 'msg_id',      i18n: 'msgtable.thId',      toggleable: false, defaultPct: 10, sortField: 'id' },
  { key: 'msg_name',    i18n: 'msgtable.thName',    toggleable: false, defaultPct: 18, sortField: 'name' },
  { key: 'msg_dlc',     i18n: 'msgtable.thDlc',     toggleable: true,  defaultPct: 6,  sortField: 'dlc' },
  { key: 'msg_cycle',   i18n: 'msgtable.thCycle',   toggleable: true,  defaultPct: 8,  sortField: 'cycle_time' },
  { key: 'msg_fd',      i18n: 'msgtable.thFd',      toggleable: true,  defaultPct: 7,  sortable: false },
  { key: 'msg_edit_signals', i18n: null,                 toggleable: false, defaultPct: 6,  sortable: false },
  { key: 'msg_actions', i18n: null,                 toggleable: false, defaultPct: 4,  sortable: false },
]

const store = useEditorStore()
const messages = useMessagesStore()
const clipboard = useClipboardStore()
const ui = useUiStore()

// ── 双击编辑状态 ──
const editingKey = ref(null) // msgId | null
function isCellEditable(msgId) {
  return editingKey.value === msgId
}

// ── 报文数量 + 排序后的报文数组 ──
const messageCount = computed(() => Object.keys(store.messages).length)

const sortedMessages = computed(() => {
  const arr = Object.values(store.messages)
  return sortByField(arr, ui.msgSortField, ui.msgSortDir)
})

function onHeaderClick(field) {
  if (consumeJustResized()) return
  const result = toggleSort(ui.msgSortField, ui.msgSortDir, field)
  ui.setMsgSort(result.field, result.dir)
}

function getSortIconText(field) {
  return getSortIcon(field, ui.msgSortField, ui.msgSortDir)
}

// ── 列显隐 + 列宽 ──
const visibleColumns = computed(() =>
  COLUMNS.filter(col => !col.toggleable || ui.isMsgColumnVisible(col.key))
)
const toggleableColumns = computed(() => COLUMNS.filter(c => c.toggleable))

const showColMenu = ref(false)
const colToggleRef = ref(null)
const tableRef = ref(null)

const { normalizedPcts, startResize, consumeJustResized } = useColumnResize(tableRef, visibleColumns, {
  getColumnWidth: (key, def) => ui.getMsgColumnWidth(key, def),
  getColumnWidths: () => ui.msgColumnWidths,
  setColumnWidths: (w) => ui.setMsgColumnWidths(w),
  hiddenColumns: () => ui.msgHiddenColumns,
})

// ── 多选 ──
const multiSelect = useMultiSelect(
  () => sortedMessages.value,
  { getKey: (m) => m.id }
)

// 同步多选 keys 到 uiStore（供右键菜单判断多选状态）
watch(multiSelect.selectedKeys, (keys) => {
  ui.msgMultiKeys = [...keys]
})

// ── 批量编辑 Modal ──
const batchEditModalOpen = ref(false)

const MSG_BATCH_EDIT_FIELDS = [
  { key: 'dlc',        i18n: 'msgtable.thDlc',    type: 'number', default: 8 },
  { key: 'cycle_time', i18n: 'msgtable.thCycle',  type: 'number', default: 0 },
  { key: 'is_fd',      i18n: 'msgtable.thFd',     type: 'select', default: false,
    options: [{ value: false, label: 'CAN' }, { value: true, label: 'CAN FD' }] },
  { key: 'sender',     i18n: 'msgtable.thSender',  type: 'text',   default: '' },
  { key: 'comment',    i18n: 'msgtable.thComment', type: 'text',   default: '' },
]

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

onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('keydown', onKeyDown)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('keydown', onKeyDown)
})

// ── 行操作 ──
function handleRowMouseDown(msgId, msgIndex, event) {
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
    multiSelect.handleRowClick(msgId, msgIndex, event)
    editingKey.value = null
    if (isInteractive) event.preventDefault()
    return
  }

  // 普通点击：清空多选，走单选逻辑，同时将当前项加入 selectedKeys
  multiSelect.clearSelection()

  // 点击输入/选择元素 → 双击进入编辑模式
  if (isInteractive) {
    if (event.detail >= 2) {
      editingKey.value = msgId
    }
    messages.selectMessage(msgId)
    multiSelect.handleRowClick(msgId, msgIndex, {})
  } else {
    editingKey.value = null
    messages.selectMessage(msgId)
    multiSelect.handleRowClick(msgId, msgIndex, {})
  }
}

function addMessage() {
  messages.addMessage()
}

function update(msgId, field, value) {
  messages.updateMessageField(field, value, msgId).catch(() => {})
}

function batchDeleteSelected() {
  if (multiSelect.selectedCount.value === 0) return
  messages.batchDeleteMessages(multiSelect.getSelectedKeys())
  multiSelect.clearSelection()
}

function onBatchEditApply(fields) {
  if (Object.keys(fields).length === 0) return
  messages.batchUpdateMessages(multiSelect.getSelectedKeys(), fields)
}

function deleteMessage(id) {
  messages.deleteMessage(id)
}

function onKeyDown(e) {
  const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable
  const ctrl = e.ctrlKey || e.metaKey

  // Escape 退出编辑模式
  if (e.key === 'Escape' && isInput && editingKey.value != null) {
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
      clipboard.copyMessages(multiSelect.getSelectedKeys())
    } else if (store.selectedMsgId != null) {
      clipboard.copyMessage()
    }
  } else if (e.key === 'x' && !isInput) {
    e.preventDefault()
    if (multiSelect.isMultiSelect.value) {
      clipboard.cutMessages(multiSelect.getSelectedKeys())
      multiSelect.clearSelection()
    } else if (store.selectedMsgId != null) {
      clipboard.cutMessage()
    }
  } else if (e.key === 'v' && !isInput) {
    e.preventDefault()
    clipboard.pasteMessages()
  } else if (e.key === 'a' && !isInput) {
    e.preventDefault()
    multiSelect.toggleAll()
  } else if (e.key === 'z' && !isInput) {
    e.preventDefault()
    // undo handled by global shortcut
  }
}

function jumpToSignals(id) {
  messages.selectMessage(id)
  ui.switchCenterTab('signals')
}

// ── 方向键单元格导航 ──
const NON_NAVIGABLE_COLS = new Set(['msg_edit_signals', 'msg_actions'])

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
  const totalRows = sortedMessages.value.length
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
  const targetMsg = sortedMessages.value[targetRow]
  if (targetMsg) messages.selectMessage(targetMsg.id)
}
</script>

<style scoped>
@import './table-styles.css';

.message-area { display: flex; flex-direction: column; flex: 1; min-height: 0; user-select: none; }

/* 编辑信号按钮 - 复用信号表值描述标签样式 */
.vt-tag {
  display: inline-block;
  background: color-mix(in oklch, var(--accent) 15%, transparent);
  color: var(--accent);
  border: none;
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.vt-tag:hover { background: color-mix(in oklch, var(--accent) 25%, transparent); }

/* 多选行高亮 */
.message-table tr.multi-selected {
  background: color-mix(in oklch, var(--accent) 20%, transparent) !important;
}

/* checkbox 列 */
.message-table th input[type="checkbox"],
.message-table td input[type="checkbox"] {
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
</style>
