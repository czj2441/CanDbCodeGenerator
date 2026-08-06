<template>
  <div class="panel">
    <!-- 信号属性区域 -->
    <template v-if="ui.centerTab === 'signals' && selectedSig">
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.signalProperties') }}</div>
        <div class="field">
          <label>{{ t('panel.signalName') }}</label>
          <input v-lazy-value="selectedSig.name" @blur="e => updateSignal('name', e.target.value)">
        </div>
        <div class="field-row">
          <div class="field">
            <label>{{ t('panel.signalStart') }}</label>
            <input class="mono" type="number" min="0" v-lazy-value="showDisplayStartBit()" @blur="e => modifyDisplayStartBit(parseInt(e.target.value)||0)">
          </div>
          <div class="field">
            <label>{{ t('panel.signalLength') }}</label>
            <input class="mono" type="number" min="1" max="64" v-lazy-value="selectedSig.length" @blur="e => updateSignal('length', parseInt(e.target.value))">
          </div>
        </div>
        <div class="field">
          <label>{{ t('panel.signalByteOrder') }}</label>
          <select :value="selectedSig.byte_order" @change="handleByteOrderChange">
            <option value="intel">{{ t('panel.intel') }}</option>
            <option value="motorola">{{ t('panel.motorola') }}</option>
          </select>
        </div>
        <div class="field-row">
          <div class="field">
            <label>{{ t('panel.signalFactor') }}</label>
            <input class="mono" type="number" step="any" v-lazy-value="selectedSig.factor" @blur="e => updateSignal('factor', parseFloat(e.target.value))">
          </div>
          <div class="field">
            <label>{{ t('panel.signalOffset') }}</label>
            <input class="mono" type="number" step="any" v-lazy-value="selectedSig.offset" @blur="e => updateSignal('offset', parseFloat(e.target.value))">
          </div>
        </div>
        <div class="field-row">
          <div class="field">
            <label>{{ t('panel.signalMin') }}</label>
            <input class="mono" type="number" step="any" v-lazy-value="selectedSig.min_val" @blur="e => updateSignal('min_val', parseFloat(e.target.value))">
          </div>
          <div class="field">
            <label>{{ t('panel.signalMax') }}</label>
            <input class="mono" type="number" step="any" v-lazy-value="selectedSig.max_val" @blur="e => updateSignal('max_val', parseFloat(e.target.value))">
          </div>
        </div>
        <div class="field">
          <label>{{ t('panel.signalUnit') }}</label>
          <input v-lazy-value="selectedSig.unit" @blur="e => updateSignal('unit', e.target.value)">
        </div>
        <div class="field">
          <label>{{ t('panel.signalComment') }}</label>
          <textarea rows="3" v-lazy-value="selectedSig.comment" @blur="e => updateSignal('comment', e.target.value)"></textarea>
        </div>
      </div>

      <!-- 值描述区域 -->
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.signalChoices') }}</div>

        <!-- 引用选择器 -->
        <div class="field">
          <label>{{ t('panel.valueTableRef') }}</label>
          <select v-model="localValueTableName" @change="onValueTableRefChange">
            <option value="">{{ t('panel.noValueTable') }}</option>
            <option v-for="name in valueTableNames" :key="name" :value="name">{{ name }}</option>
            <option value="__new__">+ {{ t('panel.createNewVt') }}</option>
          </select>
        </div>

        <!-- 新建表输入框 -->
        <div v-if="showNewVtInput" class="new-vt-inline">
          <input ref="newVtInputRef" v-model="newVtName" :placeholder="t('panel.newVtPlaceholder')"
                 spellcheck="false" @keydown.enter="confirmNewVt" @blur="confirmNewVt">
        </div>

        <!-- 内联条目编辑器 -->
        <template v-if="localValueTableName && localValueTableName !== '__new__' && valueTablePreview">
          <div class="vt-inline-editor">
            <div v-for="(row, eidx) in inlineEntries" :key="eidx" class="choices-row">
              <input class="choices-input-value mono"
                     type="number"
                     v-model.number="row.value"
                     :class="{ 'input-error': row._error }"
                     @blur="inlineCommitEntries">
              <input class="choices-input-desc"
                     type="text"
                     v-model="row.desc"
                     :class="{ 'input-error': row._error }"
                     @blur="inlineCommitEntries">
              <button class="choices-delete" @click="inlineRemoveEntry(eidx)">✕</button>
            </div>
            <button class="btn add-entry-btn" @click="inlineAddEntry">
              + {{ t('panel.addChoice') }}
            </button>
          </div>
        </template>
      </div>

    </template>

    <!-- 报文属性区域 -->
    <template v-else-if="ui.centerTab === 'messages' && msg">
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.properties') }}</div>
        <div class="field">
          <label>{{ t('panel.id') }}</label>
          <input class="mono" :value="toHex(msg.id)" @blur="e => update('id', parseHex(e.target.value))">
        </div>
        <div class="field">
          <label>{{ t('panel.name') }}</label>
          <input v-lazy-value="msg.name" @blur="e => update('name', e.target.value)">
        </div>
        <div class="field-row">
          <div class="field">
            <label>{{ t('panel.dlc') }}</label>
            <input class="mono" type="number" min="1" :max="msg.is_fd ? 64 : 8" v-lazy-value="msg.dlc" @blur="e => updateDlc(parseInt(e.target.value))">
          </div>
          <div class="field">
            <label>{{ t('panel.cycle') }}</label>
            <input class="mono" type="number" min="0" v-lazy-value="msg.cycle_time" @blur="e => update('cycle_time', parseInt(e.target.value))">
          </div>
        </div>
        <div class="field">
          <label>{{ t('panel.networkType') }}</label>
          <select ref="isFdEl" v-model="localIsFd" @change="toggleIsFd($event.target.value === 'true')">
            <option value="false">{{ t('panel.canClassic') }}</option>
            <option value="true">{{ t('panel.canfd') }}</option>
          </select>
        </div>
        <div class="field">
          <label>{{ t('panel.sender') }}</label>
          <input v-lazy-value="msg.sender" @blur="e => update('sender', e.target.value)">
        </div>
        <div class="field">
          <label>{{ t('panel.comment') }}</label>
          <textarea rows="2" v-lazy-value="msg.comment" @blur="e => update('comment', e.target.value)"></textarea>
        </div>
      </div>

      <!-- 位使用率 -->
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.bitUsage') }}</div>
        <div class="bit-usage-bar">
          <div class="bit-usage-fill" :class="bitUsageClass" :style="{ width: bitUsagePct + '%' }"></div>
        </div>
        <div class="bit-usage-text">{{ totalBits }} / {{ maxBits }} bit</div>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-else class="panel-empty" v-html="emptyHtml">
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useMessagesStore } from '../stores/messages.js'
import { useSignalsStore } from '../stores/signals.js'
import { useValueTablesStore } from '../stores/valueTables.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'
import { toDisplayStartBit, toStorageStartBit } from '../utils/signalLayout.js'
import { vLazyValue } from '../directives/lazyValue.js'

const store = useEditorStore()
const messages = useMessagesStore()
const signals = useSignalsStore()
const valueTablesStore = useValueTablesStore()
const ui = useUiStore()
const msg = computed(() => store.selectedMessage)

// ── 空状态文本 ──
const emptyHtml = computed(() =>
  ui.centerTab === 'signals'
    ? t('panel.signalEmpty')
    : t('panel.msgEmpty')
)

// ── 报文位使用率 ──
const totalBits = computed(() => {
  if (!msg.value) return 0
  return Object.values(msg.value.signals).reduce((sum, s) => sum + (s.length || 0), 0)
})
const maxBits = computed(() => (msg.value?.dlc || 0) * 8)
const bitUsagePct = computed(() => maxBits.value > 0 ? Math.min(100, (totalBits.value / maxBits.value) * 100) : 0)
const bitUsageClass = computed(() => {
  const pct = bitUsagePct.value
  if (pct >= 100) return 'danger'
  if (pct >= 75) return 'warn'
  return 'ok'
})

// ── 值描述表引用 ──
const localValueTableName = ref('')
const valueTableNames = computed(() => Object.keys(store.valueTables).sort())
const valueTablePreview = computed(() => {
  const name = localValueTableName.value
  if (!name || !store.valueTables[name]) return null
  return store.valueTables[name]
})

function onValueTableRefChange() {
  if (localValueTableName.value === '__new__') return
  if (!ui.selectedSignalName) return
  signals.updateSignal(ui.selectedSignalName, 'value_table_name', localValueTableName.value).catch(() => {})
}

// ── 内联条目编辑 ──
const inlineEntries = ref([])
let _skipVtWatch = false

function syncInlineEntries(name) {
  const entries = store.valueTables[name]
  if (!entries || typeof entries !== 'object') {
    inlineEntries.value = []
    return
  }
  inlineEntries.value = Object.entries(entries)
    .map(([k, v]) => ({ value: Number(k), desc: String(v), _error: false }))
    .sort((a, b) => a.value - b.value)
}

// 表名变化时同步条目
watch(localValueTableName, (name) => {
  if (name && name !== '__new__' && store.valueTables[name]) {
    syncInlineEntries(name)
  } else {
    inlineEntries.value = []
  }
})

function inlineAddEntry() {
  const maxVal = inlineEntries.value.length > 0
    ? Math.max(...inlineEntries.value.map(r => Number(r.value) || 0))
    : -1
  inlineEntries.value.push({ value: maxVal + 1, desc: '', _error: false })
}

function inlineRemoveEntry(idx) {
  inlineEntries.value.splice(idx, 1)
  inlineCommitEntries()
}

function inlineCommitEntries() {
  const name = localValueTableName.value
  if (!name || name === '__new__') return
  let valid = true
  const seen = new Set()
  for (const row of inlineEntries.value) {
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
  for (const row of inlineEntries.value) {
    dict[String(row.value)] = row.desc
  }
  valueTablesStore.updateValueTable(name, dict).catch(() => {})
  _skipVtWatch = true
}

// 外部数据变化时同步内联条目
watch(() => localValueTableName.value && localValueTableName.value !== '__new__' && store.valueTables[localValueTableName.value], () => {
  if (_skipVtWatch) { _skipVtWatch = false; return }
  if (localValueTableName.value && localValueTableName.value !== '__new__') {
    syncInlineEntries(localValueTableName.value)
  }
})

// ── 内联新建值描述表 ──
const showNewVtInput = ref(false)
const newVtName = ref('')
const newVtInputRef = ref(null)

watch(localValueTableName, (v) => {
  showNewVtInput.value = (v === '__new__')
  if (v === '__new__') {
    nextTick(() => newVtInputRef.value?.focus())
  }
})

async function confirmNewVt() {
  const name = newVtName.value.trim()
  if (!name) {
    localValueTableName.value = ''
    showNewVtInput.value = false
    return
  }
  if (store.valueTables[name]) {
    ui.showToast(t('valtable.duplicateName'), true)
    localValueTableName.value = ''
    showNewVtInput.value = false
    return
  }
  try {
    await valueTablesStore.addValueTable(name, { '0': 'Default' })
    localValueTableName.value = name
    onValueTableRefChange()
    syncInlineEntries(name)
  } catch { /* toast already shown */ }
  showNewVtInput.value = false
  newVtName.value = ''
}

const selectedSig = computed(() => {
  if (!msg.value || !ui.selectedSignalName) return null
  return msg.value.signals[ui.selectedSignalName] || null
})

// 从 selectedSig.value_table_name 同步
watch(() => selectedSig.value?.value_table_name, (v) => {
  localValueTableName.value = v || ''
}, { immediate: true })

// 本地 is_fd 状态
const localIsFd = ref(msg.value?.is_fd ? 'true' : 'false')
const isFdEl = ref(null)
watch(() => msg.value?.is_fd, (v) => {
  localIsFd.value = v ? 'true' : 'false'
}, { immediate: true })

/**
 * 显示用的起始位：Motorola 信号显示 LSB，Intel 信号显示原始 start_bit
 */
function showDisplayStartBit() {
  if (!selectedSig.value) return 0
  return toDisplayStartBit(selectedSig.value.start_bit, selectedSig.value.length, selectedSig.value.byte_order)
}

/**
 * 编辑起始位：Motorola 信号将用户输入的 display start bit 转换为 storage start bit (MSB) 存储
 * 转换失败时仍发送请求，由后端校验，错误在 DataErrorList 展示
 */
function modifyDisplayStartBit(displayValue) {
  if (!selectedSig.value) return
  const msbValue = toStorageStartBit(displayValue, selectedSig.value.length, selectedSig.value.byte_order, 63, selectedSig.value.start_bit)
  const valueToSend = msbValue >= 0 ? msbValue : -1
  signals.updateSignal(ui.selectedSignalName, 'start_bit', valueToSend).catch(() => {})
}

function updateSignal(field, value) {
  if (ui.selectedSignalName) {
    signals.updateSignal(ui.selectedSignalName, field, value).catch(() => {})
  }
}

function handleByteOrderChange(e) {
  if (!ui.selectedSignalName) return
  const oldOrder = selectedSig.value?.byte_order
  signals.updateSignal(ui.selectedSignalName, 'byte_order', e.target.value)
    .catch(() => { if (oldOrder != null) e.target.value = oldOrder })
}

function update(field, value) {
  messages.updateMessageField(field, value).catch(() => {})
}

function updateDlc(value) {
  update('dlc', value)
}

function toggleIsFd(newIsFd) {
  messages.updateMessageField('is_fd', newIsFd)
    .catch(e => {
      localIsFd.value = msg.value?.is_fd ? 'true' : 'false'
      if (isFdEl.value) {
        isFdEl.value.value = localIsFd.value
      }
    })
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
.field input, .field textarea, .field select {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
  font-family: var(--font-sans);
}
.field input:focus, .field textarea:focus, .field select:focus { border-color: var(--accent-dim); }
.field input.mono { font-family: var(--font-mono); }
.field textarea { resize: vertical; }
.field select { cursor: pointer; }

.field-row { display: flex; gap: 10px; }
.field-row .field { flex: 1; }

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

/* ── 内联条目编辑器 ── */
.vt-inline-editor {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  padding: 6px 8px;
  max-height: 220px;
  overflow-y: auto;
}
.choices-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
}
.choices-row + .choices-row { border-top: 1px solid var(--border-light); }
.choices-input-value {
  width: 60px;
  flex-shrink: 0;
  background: var(--bg-panel);
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
  background: var(--bg-panel);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 6px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.choices-input-value:focus, .choices-input-desc:focus { border-color: var(--accent-dim); }
.choices-input-value.input-error, .choices-input-desc.input-error { border-color: var(--danger, #e74c3c); }
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
.add-entry-btn { width: 100%; margin-top: 6px; font-size: 11px; }

/* ── 内联新建表 ── */
.new-vt-inline { margin-top: 4px; margin-bottom: 8px; }
.new-vt-inline input {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  color: var(--text);
  padding: 5px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}

/* ── 位使用率 ── */
.bit-usage-bar {
  height: 8px;
  background: var(--bg-raised);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 4px;
}
.bit-usage-fill {
  height: 100%;
  border-radius: 4px;
  transition: width var(--transition);
}
.bit-usage-fill.ok { background: var(--accent); }
.bit-usage-fill.warn { background: var(--warn); }
.bit-usage-fill.danger { background: var(--danger); }
.bit-usage-text { font-size: 11px; color: var(--text-muted); }

</style>
