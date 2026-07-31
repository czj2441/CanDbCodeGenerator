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
      <table v-else class="valtable-table" ref="tableRef">
        <colgroup>
          <col v-for="col in visibleColumns" :key="col.key"
               :style="{ width: normalizedPcts[col.key] + '%' }">
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
          <template v-for="(name, idx) in filteredNames" :key="name">
            <tr :class="{ selected: ui.selectedVtName === name }"
                @click="selectRow(name)">
              <td v-for="col in visibleColumns" :key="col.key"
                  :class="{ 'col-idx': col.key === 'vt_idx' }">
                <template v-if="col.key === 'vt_idx'"><span class="idx-label">{{ idx }}</span></template>
                <template v-else-if="col.key === 'vt_name'"><span class="vt-name">{{ name }}</span></template>
                <template v-else-if="col.key === 'vt_entries'">{{ entryCount(name) }}</template>
                <template v-else-if="col.key === 'vt_refs'">{{ refCountMap.get(name) || 0 }}</template>
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
import { useEditorStore } from '../stores/editor.js'
import { useValueTablesStore } from '../stores/valueTables.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

const COLUMNS = [
  { key: 'vt_idx',     i18n: 'valtable.thIdx',     toggleable: false, defaultPct: 4  },
  { key: 'vt_name',    i18n: 'valtable.thName',    toggleable: false, defaultPct: 28 },
  { key: 'vt_entries', i18n: 'valtable.thEntries', toggleable: true,  defaultPct: 10 },
  { key: 'vt_refs',    i18n: 'valtable.thRefs',    toggleable: true,  defaultPct: 10 },
  { key: 'vt_actions', i18n: null,                 toggleable: false, defaultPct: 6  },
]

const editor = useEditorStore()
const valueTables = useValueTablesStore()
const ui = useUiStore()

// ── 列显隐 + 列宽 ──
const visibleColumns = computed(() =>
  COLUMNS.filter(col => !col.toggleable || ui.isVtColumnVisible(col.key))
)
const toggleableColumns = computed(() => COLUMNS.filter(c => c.toggleable))

function getColumnPct(col) {
  return ui.getVtColumnWidth(col.key, col.defaultPct)
}

/** 归一化列宽百分比，确保总和 = 100%，防止浏览器自动缩放导致拖拽不同步 */
const normalizedPcts = computed(() => {
  const cols = visibleColumns.value
  const raw = {}
  let total = 0
  for (const c of cols) {
    const v = ui.getVtColumnWidth(c.key, c.defaultPct)
    raw[c.key] = v
    total += v
  }
  if (Math.abs(total - 100) < 0.01 || total === 0) return raw
  const scale = 100 / total
  const result = {}
  for (const c of cols) {
    result[c.key] = raw[c.key] * scale
  }
  return result
})

const showColMenu = ref(false)
const colToggleRef = ref(null)
const tableRef = ref(null)

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

// ── 引用计数（computed Map 优化） ──
const refCountMap = computed(() => {
  const map = new Map()
  for (const msg of editor.messages) {
    const cache = editor.messageCache[msg.id]
    if (cache?.signals) {
      for (const s of cache.signals) {
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

// ── 行选中 ──
function selectRow(name) {
  ui.selectedVtName = name
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

// ── 列宽拖拽 ──
let resizeState = null

function startResize(colIndex, e) {
  e.preventDefault()
  const cols = visibleColumns.value
  const col = cols[colIndex]
  const nextCol = cols[colIndex + 1]
  if (!nextCol) return

  // 从 DOM 读取实际渲染宽度，避免 store 原始百分比与浏览器缩放后的渲染宽度不一致
  const tableWidth = tableRef.value.getBoundingClientRect().width
  const colEls = tableRef.value.querySelectorAll('colgroup col')
  const curPct = colEls[colIndex]?.getBoundingClientRect().width / tableWidth * 100
    ?? ui.getVtColumnWidth(col.key, col.defaultPct)
  const nextPct = colEls[colIndex + 1]?.getBoundingClientRect().width / tableWidth * 100
    ?? ui.getVtColumnWidth(nextCol.key, nextCol.defaultPct)

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

  const colEls = tableRef.value.querySelectorAll('colgroup col')
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

  const widths = { ...ui.vtColumnWidths }
  widths[resizeState.col.key] = Math.round(newCur * 100) / 100
  widths[resizeState.nextCol.key] = Math.round(newNext * 100) / 100
  ui.setVtColumnWidths(widths)

  resizeState = null
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// 列显隐时宽度归一化
watch(() => ui.vtHiddenColumns, () => {
  const visible = visibleColumns.value
  if (!visible.length) return
  const total = visible.reduce((s, c) => s + ui.getVtColumnWidth(c.key, c.defaultPct), 0)
  if (Math.abs(total - 100) > 0.1) {
    const scale = 100 / total
    const widths = { ...ui.vtColumnWidths }
    for (const c of visible) {
      widths[c.key] = Math.round(ui.getVtColumnWidth(c.key, c.defaultPct) * scale * 100) / 100
    }
    ui.setVtColumnWidths(widths)
  }
}, { deep: true })

onMounted(() => {
  if (sortedNames.value.length > 0 && !ui.selectedVtName) {
    ui.selectedVtName = sortedNames.value[0]
  }
})
</script>

<style scoped>
.valtable-area { display: flex; flex-direction: column; flex: 1; min-height: 0; }

.center-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.center-title { font-size: 13px; color: var(--text-dim); }

.toolbar { display: flex; gap: 6px; align-items: center; }

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

.table-wrap { flex: 1 1 auto; overflow: auto; padding: 8px; min-height: 120px; }

.empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.valtable-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
}
.valtable-table th {
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
.valtable-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.valtable-table tr:hover > td { background: var(--signal-bg); }
.valtable-table tr.selected > td {
  background: color-mix(in oklch, var(--accent) 15%, transparent) !important;
}
.valtable-table tr.selected .col-idx {
  border-left: 3px solid var(--accent);
}

.idx-label {
  display: block;
  text-align: center;
  opacity: 0.45;
  font-size: 11px;
  font-family: var(--font-mono);
  user-select: none;
  cursor: pointer;
  line-height: 1.8;
}
tr:hover .idx-label { opacity: 0.7; }
tr.selected .idx-label { opacity: 1; font-weight: 600; }

.vt-name { font-weight: 500; }

.action-delete {
  background: transparent;
  border: none;
  color: var(--danger);
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
}
.action-delete:hover { color: oklch(0.75 0.15 25); }

/* ── 拖拽手柄 ── */
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
.resize-handle:hover::after { background: var(--accent); }

/* ── 列显隐下拉菜单 ── */
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
  box-shadow: var(--shadow);
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
</style>
