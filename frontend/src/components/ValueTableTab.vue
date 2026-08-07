<template>
  <div class="valtable-area">
    <div class="center-header">
      <div class="center-title">
        {{ t('valtable.allTables') }} · {{ sortedNames.length }} {{ t('valtable.unit') }}
      </div>
      <div class="toolbar">
        <button class="btn" @click="addNewTable">{{ t('valtable.add') }}</button>
        <input class="search-input" type="text" v-model="searchQuery"
               :placeholder="t('valtable.search')" spellcheck="false">
        <div class="col-toggle-wrap" ref="colToggleRef">
          <button class="btn" @click.stop="showColMenu = !showColMenu">{{ t('valtable.columnSettings') }} ▾</button>
          <div v-if="showColMenu" class="col-dropdown" @click.stop>
            <label v-for="col in toggleableColumns" :key="col.key" class="col-dropdown-item">
              <input type="checkbox" :checked="ui.isVtColumnVisible(col.key)"
                     @change="ui.toggleVtColumnVisibility(col.key)">
              {{ t(col.i18n) }}
            </label>
            <div class="col-dropdown-divider"></div>
            <button class="col-dropdown-reset" @click="resetAll">{{ t('valtable.resetColumns') }}</button>
          </div>
        </div>
      </div>
    </div>

    <div class="table-wrap">
      <div v-if="filteredNames.length === 0" class="empty">
        {{ searchQuery ? t('valtable.noResults') : t('valtable.empty') }}
      </div>
      <table v-else class="valtable-table data-table" ref="tableRef" @keydown="onCellKeyDown">
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
          <template v-for="name in sortedFilteredNames" :key="name">
            <tr :data-vt-name="name"
                :class="{ selected: ui.selectedVtName === name }"
                @mousedown="handleRowMouseDown(name, $event)">
              <td v-for="col in visibleColumns" :key="col.key">
                <template v-if="col.key === 'vt_name'">
                  <input v-lazy-value="name"
                         @blur="e => commitRename(name, e)"
                         @keydown.enter.prevent="$event.target.blur()"
                         @keydown.escape.prevent="cancelRename(name, $event)"
                         :readonly="editingName !== name">
                </template>
                <template v-else-if="col.key === 'vt_entries'"><input :value="entryCount(name)" readonly></template>
                <template v-else-if="col.key === 'vt_refs'"><input :value="refCountMap.get(name) || 0" readonly></template>
                <template v-else-if="col.key === 'vt_actions'">
                  <button class="action-delete" @click.stop="deleteTable(name)" title="删除">×</button>
                </template>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useCoreStore } from '../stores/coreStore.js'
import { useValueTablesStore } from '../stores/valueTables.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

import { sortByField, toggleSort, getSortIcon } from '../utils/sortHelper.js'
import { vLazyValue } from '../directives/lazyValue.js'
import { useColumnResize } from '../composables/useColumnResize.js'

const COLUMNS = [
  { key: 'vt_name',    i18n: 'valtable.thName',    toggleable: false, defaultPct: 28, sortField: 'name' },
  { key: 'vt_entries', i18n: 'valtable.thEntries', toggleable: true,  defaultPct: 10, sortable: false },
  { key: 'vt_refs',    i18n: 'valtable.thRefs',    toggleable: true,  defaultPct: 10, sortable: false },
  { key: 'vt_actions', i18n: null,                 toggleable: false, defaultPct: 6,  sortable: false },
]

const editor = useCoreStore()
const valueTables = useValueTablesStore()
const ui = useUiStore()

// ── 列显隐 + 列宽 ──
const visibleColumns = computed(() =>
  COLUMNS.filter(col => !col.toggleable || ui.isVtColumnVisible(col.key))
)
const toggleableColumns = computed(() => COLUMNS.filter(c => c.toggleable))

const showColMenu = ref(false)
const colToggleRef = ref(null)
const tableRef = ref(null)

const { normalizedPcts, startResize, consumeJustResized } = useColumnResize(tableRef, visibleColumns, {
  getColumnWidth: (key, def) => ui.getVtColumnWidth(key, def),
  getColumnWidths: () => ui.vtColumnWidths,
  setColumnWidths: (w) => ui.setVtColumnWidths(w),
  hiddenColumns: () => ui.vtHiddenColumns,
})

function resetAll() {
  ui.resetVtColumnVisibility()
  ui.resetVtColumnWidths()
  showColMenu.value = false
}

function onDocClick(e) {
  if (showColMenu.value && colToggleRef.value && !colToggleRef.value.contains(e.target)) {
    showColMenu.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

// ── 数据源 ──
const searchQuery = ref('')
const sortedNames = computed(() => Object.keys(editor.valueTables).sort())
const filteredNames = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return sortedNames.value
  return sortedNames.value.filter(n => n.toLowerCase().includes(q))
})

// ── 排序 ──
const sortedFilteredNames = computed(() => {
  const items = filteredNames.value.map(name => ({ name, _entryCount: entryCount(name), _refCount: refCountMap.value.get(name) || 0 }))
  const field = ui.vtSortField
  const dir = ui.vtSortDir
  return sortByField(items, field === 'name' ? 'name' : field === 'entries' ? '_entryCount' : '_refCount', dir).map(i => i.name)
})

function onHeaderClick(field) {
  if (consumeJustResized()) return
  const mappedField = field === 'entries' ? 'entries' : field === 'refs' ? 'refs' : field
  const result = toggleSort(ui.vtSortField, ui.vtSortDir, mappedField)
  ui.setVtSort(result.field, result.dir)
}

function getSortIconText(field) {
  return getSortIcon(field, ui.vtSortField, ui.vtSortDir)
}

// ── 引用计数（computed Map 优化） ──
const refCountMap = computed(() => {
  const map = new Map()
  for (const msg of Object.values(editor.messages)) {
    const cache = editor.messageCache[msg.id]
    if (cache?.signals) {
      for (const s of Object.values(cache.signals)) {
        if (s.value_table_name) {
          map.set(s.value_table_name, (map.get(s.value_table_name) || 0) + 1)
        }
      }
    }
  }
  return map
})

function entryCount(name) {
  const entries = editor.valueTables[name]
  if (!entries || typeof entries !== 'object') return 0
  return Object.keys(entries).length
}

// ── 双击重命名 ──
const editingName = ref(null)

async function commitRename(name, event) {
  const newName = event.target.value.trim()
  if (!newName || newName === name) return
  try {
    await valueTables.renameValueTable(name, newName)
    if (ui.selectedVtName === name) ui.selectedVtName = newName
  } catch { /* toast already shown */ }
}

function cancelRename(name, event) {
  editingName.value = null
  event.target.value = name
}

// ── 行交互 ──
function handleRowMouseDown(name, event) {
  const INTERACTIVE_TAGS = new Set(['INPUT', 'SELECT'])
  if (event.button !== 0) {
    if (INTERACTIVE_TAGS.has(event.target.tagName)) event.preventDefault()
    return
  }
  const isInteractive = INTERACTIVE_TAGS.has(event.target.tagName)
  if (isInteractive) {
    if (event.detail >= 2) editingName.value = name
    ui.selectedVtName = name
  } else {
    editingName.value = null
    ui.selectedVtName = name
  }
}

// ── 方向键单元格导航 ──
const NON_NAVIGABLE_COLS = new Set(['vt_actions'])

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
  const totalRows = sortedFilteredNames.value.length
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
  ui.selectedVtName = sortedFilteredNames.value[targetRow]
}

// ── 新增表 ──
async function addNewTable() {
  let baseName = 'NewTable'
  let i = 1
  while (editor.valueTables[baseName + i]) i++
  const name = baseName + i
  try {
    await valueTables.addValueTable(name, { '0': 'Default' })
    ui.selectedVtName = name
  } catch { /* toast already shown */ }
}

// ── 删除表 ──
async function deleteTable(name) {
  const refs = refCountMap.value.get(name) || 0
  if (refs > 0) {
    ui.showToast(t('valtable.hasReferences', { count: refs }), true)
    return
  }
  if (!confirm(t('valtable.confirmDelete'))) return
  try {
    await valueTables.deleteValueTable(name)
    if (ui.selectedVtName === name) {
      ui.selectedVtName = null
    }
  } catch { /* toast already shown */ }
}

// ── 外部跳转支持 ──
watch(() => ui.valueTableFocusName, (name) => {
  if (name && editor.valueTables[name]) {
    ui.selectedVtName = name
    searchQuery.value = ''
  }
  ui.valueTableFocusName = ''
})

onMounted(() => {
  if (sortedNames.value.length > 0 && !ui.selectedVtName) {
    ui.selectedVtName = sortedNames.value[0]
  }
})
</script>

<style scoped>
@import './table-styles.css';

.valtable-area { display: flex; flex-direction: column; flex: 1; min-height: 0; user-select: none; }

.search-input {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
  width: 140px;
}
.search-input:focus { border-color: var(--accent-dim); }
</style>
