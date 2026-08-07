<template>
  <div class="panel">
    <template v-if="selectedName">
      <!-- 属性 section -->
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.vtProperties') }}</div>
        <div class="field">
          <label>{{ t('panel.name') }}</label>
          <input v-model="editingName" @blur="commitRename" spellcheck="false">
        </div>
        <div class="ref-info">
          {{ t('valtable.refCount') }}: {{ refCount }}
        </div>
      </div>

      <!-- 值描述条目 section -->
      <div class="panel-section entries-section">
        <div class="panel-section-title">{{ t('panel.choicesTitle') }}</div>
        <div class="vt-entries">
          <div v-for="(row, eidx) in localEntries" :key="eidx" class="choices-row">
            <input class="choices-input-value mono"
                   type="number"
                   v-model.number="row.value"
                   :class="{ 'input-error': row._error }"
                   @blur="commitEntries">
            <input class="choices-input-desc"
                   type="text"
                   v-model="row.desc"
                   :class="{ 'input-error': row._error }"
                   @blur="commitEntries">
            <button class="choices-delete" @click="removeEntry(eidx)">✕</button>
          </div>
        </div>
        <button class="btn add-entry-btn" @click="addEntry">
          + {{ t('panel.addChoice') }}
        </button>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-else class="panel-empty">
      {{ t('valtable.panelEmpty') }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useCoreStore } from '../stores/coreStore.js'
import { useValueTablesStore } from '../stores/valueTables.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

const editor = useCoreStore()
const valueTables = useValueTablesStore()
const ui = useUiStore()

// ── 选中状态 ──
const selectedName = computed(() => {
  const name = ui.selectedVtName
  return (name && editor.valueTables[name]) ? name : null
})

// ── 引用计数 ──
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

const refCount = computed(() =>
  selectedName.value ? (refCountMap.value.get(selectedName.value) || 0) : 0
)

// ── 本地编辑状态 ──
const editingName = ref('')
const localEntries = ref([])
let _skipVtWatch = false

function syncLocalEntries(name) {
  editingName.value = name
  const entries = editor.valueTables[name]
  if (!entries || typeof entries !== 'object') {
    localEntries.value = []
    return
  }
  localEntries.value = Object.entries(entries)
    .map(([k, v]) => ({ value: Number(k), desc: String(v), _error: false }))
    .sort((a, b) => a.value - b.value)
}

// selectedName 变化时同步
watch(selectedName, (name) => {
  if (name) syncLocalEntries(name)
  else { localEntries.value = []; editingName.value = '' }
}, { immediate: true })

// 外部数据变化时同步（WS 事件等）
watch(() => selectedName.value && editor.valueTables[selectedName.value], () => {
  if (_skipVtWatch) { _skipVtWatch = false; return }
  if (selectedName.value) syncLocalEntries(selectedName.value)
})

// ── 重命名 ──
async function commitRename() {
  const oldName = selectedName.value
  if (!oldName) return
  const newName = editingName.value.trim()
  if (!newName) {
    editingName.value = oldName
    ui.showToast(t('valtable.emptyName'), true)
    return
  }
  if (newName === oldName) return
  if (editor.valueTables[newName]) {
    editingName.value = oldName
    ui.showToast(t('valtable.duplicateName'), true)
    return
  }
  try {
    await valueTables.renameValueTable(oldName, newName)
    _skipVtWatch = true
    ui.selectedVtName = newName
    editingName.value = newName
  } catch {
    editingName.value = oldName
  }
}

// ── 编辑条目 ──
function addEntry() {
  const maxVal = localEntries.value.length > 0
    ? Math.max(...localEntries.value.map(r => Number(r.value) || 0))
    : -1
  localEntries.value.push({ value: maxVal + 1, desc: '', _error: false })
}

function removeEntry(idx) {
  localEntries.value.splice(idx, 1)
  commitEntries()
}

function commitEntries() {
  if (!selectedName.value) return
  let valid = true
  const seen = new Set()
  for (const row of localEntries.value) {
    row._error = false
    if (row.value === '' || row.value === null || !Number.isInteger(row.value)) {
      row._error = true; valid = false
    } else if (!row.desc?.trim()) {
      row._error = true; valid = false
    } else if (seen.has(row.value)) {
      row._error = true; valid = false
    }
    seen.add(row.value)
  }
  if (!valid) return
  const dict = {}
  for (const row of localEntries.value) {
    dict[String(row.value)] = row.desc
  }
  valueTables.updateValueTable(selectedName.value, dict).catch(() => {})
}
</script>

<style scoped>
.panel {
  width: 100%;
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  flex-shrink: 0;
}

.panel-empty {
  padding: 40px 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.panel-section {
  padding: 14px;
  border-bottom: 1px solid var(--border);
}
.panel-section-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.field { margin-bottom: 10px; }
.field label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 3px;
}
.field input {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.field input:focus { border-color: var(--accent-dim); }

.ref-info {
  font-size: 11px;
  color: var(--text-muted);
}

/* ── 条目编辑区 ── */
.entries-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.vt-entries {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.choices-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
}
.choices-row + .choices-row {
  border-top: 1px solid var(--border-light);
}
.choices-input-value {
  width: 60px;
  flex-shrink: 0;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 6px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
  font-family: var(--font-mono);
}
.choices-input-desc {
  flex: 1;
  min-width: 0;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 6px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.choices-input-value:focus, .choices-input-desc:focus {
  border-color: var(--accent-dim);
}
.choices-input-value.input-error, .choices-input-desc.input-error {
  border-color: var(--danger, #e74c3c);
}
.choices-delete {
  width: 20px; height: 20px;
  flex-shrink: 0;
  background: none; border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0;
}
.choices-delete:hover { color: var(--danger, #e74c3c); }

.add-entry-btn {
  width: 100%;
  margin-top: 8px;
  font-size: 11px;
}

.btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.btn:hover { background: var(--bg-hover); }
</style>
