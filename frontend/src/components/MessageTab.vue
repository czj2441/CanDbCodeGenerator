<template>
  <div class="message-area">
    <div class="center-header">
      <div class="center-title">
        {{ t('msgtable.allMessages') }} · {{ messageCount }} {{ t('msgtable.unit') }}
      </div>
      <div class="toolbar">
        <button v-if="!store.readOnly" class="btn" @click="addMessage">{{ t('msgtable.add') }}</button>
        <template v-if="!store.readOnly && multiSelect.isMultiSelect.value">
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
      <table v-else class="message-table data-table" :class="{ 'data-table-readonly': store.readOnly }" ref="tableRef" @keydown="onCellKeyDown" @focusout="onTableFocusOut">
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
          <tr v-for="(m, mIdx) in sortedMessages" :key="m.key"
              :data-msg-key="m.key"
              :class="{ selected: store.selectedMsgKey === m.key, 'multi-selected': multiSelect.selectedKeys.value.has(m.key) }"
              @mousedown="handleRowMouseDown(m.key, mIdx, $event)">
            <td v-for="col in visibleColumns" :key="col.key"
                :class="{ 'cb-cell': col.key === '_cb' }"
                @mousedown="col.key === '_cb' ? onCbCellMouseDown(m.key, $event) : null">
              <template v-if="col.key === '_cb'">
                <input type="checkbox" :checked="multiSelect.selectedKeys.value.has(m.key)"
                       @click.stop @change="multiSelect.toggleCheckbox(m.key)">
              </template>
              <template v-else-if="col.key === 'msg_key'">
                <div class="msg-id-cell">
                  <input class="mono" v-lazy-value="toHex(m.id)" @blur="e => isCellEditable(m.key) && update(m.key, 'id', parseHex(e.target.value))" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(m.key)" data-field="msg_key">
                  <span v-if="m.is_extended_frame" class="ext-badge" :title="t('panel.extendedFrame')">ext</span>
                </div>
              </template>
              <template v-else-if="col.key === 'msg_name'"><input v-lazy-value="m.name" @blur="e => isCellEditable(m.key) && update(m.key, 'name', e.target.value)" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(m.key)" data-field="msg_name"></template>
              <template v-else-if="col.key === 'msg_dlc'"><input class="mono" type="number" v-lazy-value="m.dlc" @blur="e => isCellEditable(m.key) && update(m.key, 'dlc', parseInt(e.target.value))" :readonly="!isCellEditable(m.key)" data-field="msg_dlc"></template>
              <template v-else-if="col.key === 'msg_cycle'"><input class="mono" type="number" v-lazy-value="m.cycle_time" @blur="e => isCellEditable(m.key) && update(m.key, 'cycle_time', parseInt(e.target.value))" :readonly="!isCellEditable(m.key)" data-field="msg_cycle"></template>
              <template v-else-if="col.key === 'msg_fd'">
                <select :value="String(m.is_fd)" @change="e => update(m.key, 'is_fd', e.target.value === 'true')" data-field="msg_fd">
                  <option value="false">CAN</option>
                  <option value="true">CAN FD</option>
                </select>
              </template>
              <template v-else-if="col.key === 'msg_sender'"><input v-lazy-value="m.sender" @blur="e => isCellEditable(m.key) && update(m.key, 'sender', e.target.value)" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(m.key)" data-field="msg_sender"></template>
              <template v-else-if="col.key === 'msg_bit_usage'">
                <div class="bit-bar-cell">
                  <div class="bit-bar"><div class="bit-bar-fill" :class="bitUsageClass(m)" :style="{ width: bitUsagePct(m) + '%' }"></div></div>
                  <span class="bit-bar-text">{{ m.total_signal_bits || 0 }}/{{ m.dlc * 8 }} bit</span>
                </div>
              </template>
              <template v-else-if="col.key === 'msg_comment'"><input v-lazy-value="m.comment" @blur="e => isCellEditable(m.key) && update(m.key, 'comment', e.target.value)" :disabled="multiSelect.isMultiSelect.value" :readonly="!isCellEditable(m.key)" data-field="msg_comment"></template>
              <template v-else-if="col.key === 'msg_edit_signals'"><button class="vt-tag" @click.stop="jumpToSignals(m.key)">{{ t('msgtable.editSignals') }}</button></template>
              <template v-else-if="col.key === 'msg_actions'">
                              <button v-if="!store.readOnly" class="action-delete" @click.stop="deleteMessage(m.key)" title="删除">×</button>
                            </template>
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
import { useCoreStore } from '../stores/coreStore.js'
import { useMessagesStore } from '../stores/messages.js'
import { useClipboardStore } from '../stores/clipboard.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'
import { vLazyValue } from '../directives/lazyValue.js'

import { sortByField, toggleSort, getSortIcon } from '../utils/sortHelper.js'
import { useColumnResize } from '../composables/useColumnResize.js'
import { useMultiSelect } from '../composables/useMultiSelect.js'
import { useTableNavigation } from '../composables/useTableNavigation.js'
import BatchEditModal from './BatchEditModal.vue'

const COLUMNS = [
  { key: '_cb',         i18n: null,                toggleable: false, defaultPct: 2,  sortable: false },
  { key: 'msg_key',      i18n: 'msgtable.thId',      toggleable: false, defaultPct: 9,  sortField: 'id' },
  { key: 'msg_name',    i18n: 'msgtable.thName',    toggleable: false, defaultPct: 15, sortField: 'name' },
  { key: 'msg_sender',  i18n: 'msgtable.thSender',  toggleable: true,  defaultPct: 8,  sortField: 'sender' },
  { key: 'msg_dlc',     i18n: 'msgtable.thDlc',     toggleable: true,  defaultPct: 5,  sortField: 'dlc' },
  { key: 'msg_cycle',   i18n: 'msgtable.thCycle',   toggleable: true,  defaultPct: 7,  sortField: 'cycle_time' },
  { key: 'msg_fd',      i18n: 'msgtable.thFd',      toggleable: true,  defaultPct: 6,  sortable: false },
  { key: 'msg_bit_usage', i18n: 'msgtable.thBitUsage', toggleable: true, defaultPct: 10, sortable: false },
  { key: 'msg_comment', i18n: 'msgtable.thComment', toggleable: true,  defaultPct: 12, sortField: 'comment' },
  { key: 'msg_edit_signals', i18n: null,                 toggleable: false, defaultPct: 5,  sortable: false },
  { key: 'msg_actions', i18n: null,                 toggleable: false, defaultPct: 3,  sortable: false },
]

const store = useCoreStore()
const messages = useMessagesStore()
const clipboard = useClipboardStore()
const ui = useUiStore()

// ── 双击编辑状态 ──
const editingKey = ref(null) // { msgKey, field } | null
function isCellEditable(msgKey) {
  if (store.readOnly) return false
  return editingKey.value && editingKey.value.msgKey === msgKey
}

/** input type 是否支持 setSelectionRange / selectionStart */
const SELECTION_TYPES = new Set(['text', 'search', 'url', 'tel', 'password', ''])

/** 提交当前编辑并退出编辑模式：先 blur 触发 @blur 保存，再清除编辑状态 */
function commitAndExitEdit() {
  const el = document.activeElement
  if (el?.tagName === 'INPUT') el.blur()
  editingKey.value = null
}

// ── 报文数量 + 排序后的报文数组 ──
const messageCount = computed(() => Object.keys(store.messages).length)

const sortedMessages = computed(() => {
  const arr = Object.values(store.messages)
  return sortByField(arr, ui.msgSortField, ui.msgSortDir)
})

// ── 位使用率计算 ──
function bitUsagePct(m) {
  const max = (m.dlc || 0) * 8
  return max > 0 ? ((m.total_signal_bits || 0) / max) * 100 : 0
}
function bitUsageClass(m) {
  const pct = bitUsagePct(m)
  return pct > 100 ? 'danger' : pct >= 80 ? 'warn' : 'ok'
}

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
  { getKey: (m) => m.key }
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

function handleRowMouseDown(msgKey, msgIndex, event) {
  const INTERACTIVE_TAGS = new Set(['INPUT', 'SELECT'])

  // 非左键：阻止输入框聚焦，不干扰多选状态（右键菜单由 contextmenu 事件处理）
  if (event.button !== 0) {
    if (INTERACTIVE_TAGS.has(event.target.tagName)) event.preventDefault()
    return
  }

  const targetEl = event.target
  const isInteractive = INTERACTIVE_TAGS.has(targetEl.tagName)

  const isCheckbox = targetEl.type === 'checkbox'

  // Checkbox 点击：提交当前编辑并退出，不干扰多选状态，交给 @change 处理
  if (isCheckbox) {
    commitAndExitEdit()
    return
  }

  // Ctrl/Shift + Click → 多选（preventDefault 阻止浏览器聚焦 input，避免进入编辑状态）
  if (event.ctrlKey || event.metaKey || event.shiftKey) {
    multiSelect.handleRowClick(msgKey, msgIndex, event)
    commitAndExitEdit()
    if (isInteractive) event.preventDefault()
    return
  }

  // 普通点击：清空多选，走单选逻辑，同时将当前项加入 selectedKeys
  multiSelect.clearSelection()

  // 点击输入/选择元素 → 双击进入编辑模式
  if (isInteractive) {
    if (event.detail >= 2) {
      // 双击新单元格前，先提交上一个编辑
      if (editingKey.value) commitAndExitEdit()
      editingKey.value = { msgKey, field: targetEl.dataset.field }
    } else {
      // 单击非当前编辑单元格时提交并退出编辑模式
      const ek = editingKey.value
      if (ek && (ek.msgKey !== msgKey || ek.field !== targetEl.dataset.field)) {
        commitAndExitEdit()
      }
    }
    messages.selectMessage(msgKey)
    multiSelect.handleRowClick(msgKey, msgIndex, {})
  } else {
    commitAndExitEdit()
    messages.selectMessage(msgKey)
    multiSelect.handleRowClick(msgKey, msgIndex, {})
  }
}

/** 输入框失焦时清除文本选中，防止“虚假编辑”外观 */
function onTableFocusOut(e) {
  if (e.target.tagName === 'INPUT' && SELECTION_TYPES.has(e.target.type)) {
    e.target.setSelectionRange(0, 0)
  }
}

function addMessage() {
  messages.addMessage()
}

function update(msgKey, field, value) {
  messages.updateMessageField(field, value, msgKey).catch(() => {})
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

  // Escape 退出编辑模式但保持焦点
  if (e.key === 'Escape' && isInput && editingKey.value != null) {
    editingKey.value = null
    // 还原输入值到 store 原始值，但不失去焦点
    if (e.target.__lastCommitted !== undefined) {
      e.target.value = String(e.target.__lastCommitted ?? '')
    }
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
    } else if (store.selectedMsgKey != null) {
      clipboard.copyMessage()
    }
  } else if (e.key === 'x' && !isInput) {
    e.preventDefault()
    if (multiSelect.isMultiSelect.value) {
      clipboard.cutMessages(multiSelect.getSelectedKeys())
      multiSelect.clearSelection()
    } else if (store.selectedMsgKey != null) {
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
  ui.openMessageTab(id)
}

// ── 方向键单元格导航 ──
const { onCellKeyDown } = useTableNavigation(tableRef, visibleColumns, {
  nonNavigableCols: new Set(['_cb', 'msg_edit_signals', 'msg_actions', 'msg_bit_usage']),
  getTotalRows: () => sortedMessages.value.length,
  isEditing: () => editingKey.value !== null,
  onRowSelect: (rowIdx) => {
    const msg = sortedMessages.value[rowIdx]
    if (msg) messages.selectMessage(msg.key)
  },
  onStartEdit: (el) => {
    if (store.readOnly) return false
    const msgKey = el.closest('tr')?.dataset.msgKey
    if (!msgKey) return false
    editingKey.value = { msgKey, field: el.dataset.field }
  },
  onEndEdit: () => { editingKey.value = null },
})
</script>

<style scoped>
@import './table-styles.css';

.message-area { display: flex; flex-direction: column; flex: 1; min-height: 0; user-select: none; }

/* 编辑信号按钮 — 撑满列宽，文字居中 */
.vt-tag {
  display: block;
  width: 100%;
  box-sizing: border-box;
  background: color-mix(in oklch, var(--accent) 15%, transparent);
  color: var(--accent);
  border: none;
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
  cursor: pointer;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.vt-tag:hover { background: color-mix(in oklch, var(--accent) 25%, transparent); }

/* 多选行高亮 */
.message-table tr.multi-selected {
  background: color-mix(in oklch, var(--accent) 20%, transparent) !important;
}

/* checkbox 列 — 扩大可点击范围 */
.cb-cell { cursor: pointer; }
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

/* 位使用率进度条 */
.bit-bar-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.bit-bar {
  flex: 1;
  min-width: 30px;
  height: 6px;
  background: var(--bg-raised);
  border-radius: 3px;
  overflow: hidden;
}
.bit-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width var(--transition);
}
.bit-bar-fill.ok { background: var(--accent); }
.bit-bar-fill.warn { background: var(--warn); }
.bit-bar-fill.danger { background: var(--danger); }
.bit-bar-text {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.msg-id-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}
.ext-badge {
  flex-shrink: 0;
  font-size: 9px;
  line-height: 1;
  padding: 2px 3px;
  border-radius: 3px;
  color: var(--accent);
  border: 1px solid var(--accent-dim);
  font-family: var(--font-mono);
}
</style>
