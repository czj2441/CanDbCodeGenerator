<template>
  <div class="signal-area">
    <div class="center-header">
      <div class="center-title">
        <template v-if="msg">
          <strong>{{ msg.name || t('msglist.unnamed') }}</strong>
          — {{ toHex(msg.id) }} · {{ msg.signals.length }} {{ msg.signals.length === 1 ? t('status.signal') : t('status.signals') }}
        </template>
        <template v-else>{{ t('signal.selectMessage') }}</template>
      </div>
      <div v-if="msg" class="toolbar">
        <button class="btn" @click="addSignal">{{ t('signal.add') }}</button>
        <button class="btn btn-accent" @click="store.batchModalOpen = true">{{ t('signal.batch') }}</button>
        <button class="btn btn-danger" @click="deleteMsg">{{ t('signal.deleteMsg') }}</button>
      </div>
    </div>

    <div class="table-wrap">
      <div v-if="!msg" class="empty" v-html="t('signal.selectMessage')">
      </div>
      <div v-else-if="msg.signals.length === 0" class="empty" v-html="t('signal.empty')">
      </div>
      <table v-else class="signal-table">
        <thead>
          <tr>
            <th>{{ t('signal.thIdx') }}</th>
            <th>{{ t('signal.thName') }}</th>
            <th>{{ t('signal.thStart') }}</th>
            <th>{{ t('signal.thLen') }}</th>
            <th>{{ t('signal.thOrder') }}</th>
            <th>{{ t('signal.thFactor') }}</th>
            <th>{{ t('signal.thOffset') }}</th>
            <th>{{ t('signal.thMin') }}</th>
            <th>{{ t('signal.thMax') }}</th>
            <th>{{ t('signal.thUnit') }}</th>
            <th>{{ t('signal.thComment') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(sig, idx) in msg.signals" :key="sig.uuid" :data-sig-id="sig.uuid" :class="{ 'has-error': errorUuids.has(sig.uuid), 'selected': selectedSigUuid === sig.uuid }" @click="selectRow(sig.uuid)">
            <td><input class="hex" :value="idx" readonly></td>
            <td><input v-model="sig.name" @blur="update(sig.uuid, 'name', sig.name)"></td>
            <td><input class="mono" type="number" v-model.number="sig.start_bit" @blur="update(sig.uuid, 'start_bit', sig.start_bit)"></td>
            <td><input class="mono" type="number" v-model.number="sig.length" @blur="update(sig.uuid, 'length', sig.length)"></td>
            <td><input class="mono" v-model="sig.byte_order" @blur="update(sig.uuid, 'byte_order', sig.byte_order)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.factor" @blur="update(sig.uuid, 'factor', sig.factor)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.offset" @blur="update(sig.uuid, 'offset', sig.offset)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.min_val" @blur="update(sig.uuid, 'min_val', sig.min_val)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.max_val" @blur="update(sig.uuid, 'max_val', sig.max_val)"></td>
            <td><input v-model="sig.unit" @blur="update(sig.uuid, 'unit', sig.unit)"></td>
            <td><input v-model="sig.comment" @blur="update(sig.uuid, 'comment', sig.comment)"></td>
            <td><button class="action-delete" @click="store.deleteSignal(sig.uuid)" title="删除">×</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 信号布局错误提示区 -->
    <div v-if="msg && store.signalErrors.length > 0" class="error-panel">
      <div class="error-title">{{ t('signal.errorsTitle') }}</div>
      <div v-for="err in store.signalErrors" :key="err.signal_uuid + err.type" class="error-item">
        <span v-if="err.type === 'out_of_bounds'">
          {{ t('signal.errorOutOfBounds', { name: err.signal_name, bits: err.out_of_bounds_bits.join(','), max: msg.dlc * 8 - 1 }) }}
        </span>
        <span v-if="err.type === 'overlap'">
          {{ t('signal.errorOverlap', { name: err.signal_name, other: err.conflicts_name, bits: err.overlapping_bits.join(',') }) }}
        </span>
        <button v-if="err.suggestion" class="btn-fix" @click="fixSignal(err.signal_uuid, err.suggestion.recommended_start_bit)">
          {{ t('signal.fixBtn') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { toHex } from '../utils/format.js'
import { t } from '../i18n.js'

const store = useEditorStore()

const msg = computed(() => store.selectedMessage)
const selectedSigUuid = ref(null)

// 切换报文时清除选中
watch(msg, () => { selectedSigUuid.value = null })

const errorUuids = computed(() => {
  const set = new Set()
  for (const err of store.signalErrors) {
    set.add(err.signal_uuid)
    if (err.conflicts_uuid) set.add(err.conflicts_uuid)
  }
  return set
})

function selectRow(uuid) {
  selectedSigUuid.value = selectedSigUuid.value === uuid ? null : uuid
}

function onKeyDown(e) {
  const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable
  const ctrl = e.ctrlKey || e.metaKey
  if (!ctrl) return

  if (e.key === 'c' && !isInput) {
    e.preventDefault()
    if (selectedSigUuid.value) {
      store.copySignal(selectedSigUuid.value)
    }
  } else if (e.key === 'v' && !isInput) {
    e.preventDefault()
    store.pasteSignal()
  } else if (e.key === 'z' && !isInput) {
    e.preventDefault()
    store.undo()
  }
}

onMounted(() => window.addEventListener('keydown', onKeyDown))
onUnmounted(() => window.removeEventListener('keydown', onKeyDown))

function addSignal() {
  store.addSignal({ name: 'NewSignal', start_bit: 0, length: 8 })
}

function update(idx, field, value) {
  store.updateSignal(idx, field, value)
}

function deleteMsg() {
  if (store.selectedMsgId == null) return
  store.deleteMessage(store.selectedMsgId)
}

function fixSignal(uuid, newStartBit) {
  store.autoFixSignal(uuid, newStartBit)
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
  border-collapse: collapse;
  font-size: 12px;
}
.signal-table th {
  text-align: left;
  padding: 6px 8px;
  color: var(--text-muted);
  font-weight: 500;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.signal-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
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
.signal-table input:focus {
  background: var(--bg-raised);
  border-color: var(--accent-dim);
}
.signal-table input.mono { font-family: var(--font-mono); }
.signal-table input.hex { opacity: 0.5; text-align: center; }

.action-delete {
  background: transparent;
  border: none;
  color: var(--danger);
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
}
.action-delete:hover { color: oklch(0.75 0.15 25); }

/* 错误提示区 */
.error-panel {
  background: oklch(0.18 0.06 25);
  border: 1px solid oklch(0.4 0.1 25);
  border-radius: var(--radius-sm);
  margin: 8px;
  padding: 8px 12px;
  font-size: 12px;
  flex-shrink: 0;
  max-height: 140px;
  overflow-y: auto;
}
.error-title {
  color: oklch(0.75 0.15 25);
  font-weight: 600;
  margin-bottom: 4px;
}
.error-item {
  color: oklch(0.8 0.08 25);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0;
  flex-wrap: wrap;
}
.btn-fix {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  cursor: pointer;
}
.btn-fix:hover { background: var(--accent); }

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
</style>
