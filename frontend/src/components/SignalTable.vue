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
        <button class="btn btn-accent" @click="ui.batchModalOpen = true">{{ t('signal.batch') }}</button>
        <button class="btn" @click="ui.toggleLayoutView()">{{ t('layout.viewLayout') }}</button>
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
          <tr v-for="(sig, idx) in msg.signals" :key="sig.uuid" :data-sig-id="sig.uuid" :class="{ 'has-error': errorUuids.has(sig.uuid), 'selected': selectedSigUuid === sig.uuid }" @mousedown="handleRowMouseDown(sig.uuid, $event)">
            <td><input class="hex" :value="idx" readonly></td>
            <td><input v-lazy-value="sig.name" @blur="e => update(sig.uuid, 'name', e.target.value)"></td>
            <td><input class="mono" type="number" v-lazy-value="displayStartBit(sig)" @blur="e => updateStartBit(sig, parseInt(e.target.value)||0)"></td>
            <td><input class="mono" type="number" v-lazy-value="sig.length" @blur="e => update(sig.uuid, 'length', parseInt(e.target.value))"></td>
            <td>
              <select :value="sig.byte_order" @change="e => update(sig.uuid, 'byte_order', e.target.value)">
                <option value="intel">Intel</option>
                <option value="motorola">Motorola</option>
              </select>
            </td>
            <td><input class="mono" type="number" step="any" v-lazy-value="sig.factor" @blur="e => update(sig.uuid, 'factor', parseFloat(e.target.value))"></td>
            <td><input class="mono" type="number" step="any" v-lazy-value="sig.offset" @blur="e => update(sig.uuid, 'offset', parseFloat(e.target.value))"></td>
            <td><input class="mono" type="number" step="any" v-lazy-value="sig.min_val" @blur="e => update(sig.uuid, 'min_val', parseFloat(e.target.value))"></td>
            <td><input class="mono" type="number" step="any" v-lazy-value="sig.max_val" @blur="e => update(sig.uuid, 'max_val', parseFloat(e.target.value))"></td>
            <td><input v-lazy-value="sig.unit" @blur="e => update(sig.uuid, 'unit', e.target.value)"></td>
            <td><input v-lazy-value="sig.comment" @blur="e => update(sig.uuid, 'comment', e.target.value)"></td>
            <td><button class="action-delete" @click.stop="store.deleteSignal(sig.uuid)" title="删除">×</button></td>
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
import { useUiStore } from '../stores/uiStore.js'
import { toHex } from '../utils/format.js'
import { toDisplayStartBit, toStorageStartBit } from '../utils/signalLayout.js'
import { t } from '../i18n.js'
import { vLazyValue } from '../directives/lazyValue.js'

function showToast(msg, isError = false) {
  useUiStore().showToast(msg, isError)
}

const store = useEditorStore()
const ui = useUiStore()

const msg = computed(() => store.selectedMessage)
// ✅ 使用单一数据源：直接代理 ui.selectedSignalUuid，避免双写
const selectedSigUuid = computed({
  get: () => ui.selectedSignalUuid,
  set: (val) => { ui.selectedSignalUuid = val }
})

// 切换报文时清除选中
watch(msg, () => {
  ui.selectedSignalUuid = null
})

const errorUuids = computed(() => {
  const set = new Set()
  for (const err of store.signalErrors) {
    set.add(err.signal_uuid)
    if (err.conflicts_uuid) set.add(err.conflicts_uuid)
  }
  return set
})

function handleRowMouseDown(uuid, event) {
  // ⚠️ 维护注意：新增交互元素类型（如自定义 datepicker/autocomplete）时，
  // 需同步扩展下面的 INTERACTIVE_TAGS 集合，否则会被误判为"空白区域"触发 toggle。
  const INTERACTIVE_TAGS = new Set(['INPUT', 'SELECT'])
  const isInteractive = INTERACTIVE_TAGS.has(event.target.tagName)

  if (isInteractive) {
    // 点击交互元素：确保选中该信号（已选中则保持，不切换）
    if (ui.selectedSignalUuid !== uuid) {
      ui.selectedSignalUuid = uuid
    }
  } else {
    // 点击空白区域：切换选中状态
    ui.selectedSignalUuid = ui.selectedSignalUuid === uuid ? null : uuid
  }
}

function onKeyDown(e) {
  const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable
  const ctrl = e.ctrlKey || e.metaKey
  if (!ctrl) return

  if (e.key === 'c' && !isInput) {
    e.preventDefault()
    if (ui.selectedSignalUuid) {
      store.copySignal(ui.selectedSignalUuid)
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
  store.addSignal({ name: 'NewSignal' })
}

function update(idx, field, value) {
  store.updateSignal(idx, field, value)
}

/**
 * 显示用的起始位：Motorola 信号显示 LSB，Intel 信号显示原始 start_bit
 */
function displayStartBit(sig) {
  return toDisplayStartBit(sig.start_bit, sig.length, sig.byte_order)
}

/**
 * 编辑起始位：Motorola 信号将用户输入的 display start bit 转换为 storage start bit (MSB)
 */
function updateStartBit(sig, displayValue) {
  const msbValue = toStorageStartBit(displayValue, sig.length, sig.byte_order, 63, sig.start_bit)
  if (msbValue >= 0) {
    store.updateSignal(sig.uuid, 'start_bit', msbValue)
  } else {
    showToast(`起始位 ${displayValue} 对于 ${sig.byte_order} length=${sig.length} 不合法`, true)
  }
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
