<template>
  <div class="panel">
    <!-- 信号属性区域（动态报文 tab，有选中信号时显示） -->
    <template v-if="isDynamicMsgTab && selectedSig">
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

    <!-- 空状态 -->
    <div v-else class="panel-empty" v-html="t('panel.signalEmpty')">
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useCoreStore } from '../stores/coreStore.js'
import { useSignalsStore } from '../stores/signals.js'
import { useValueTablesStore } from '../stores/valueTables.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'
import { toDisplayStartBit, toStorageStartBit } from '../utils/signalLayout.js'
import { vLazyValue } from '../directives/lazyValue.js'
import './panel-styles.css'

const store = useCoreStore()
const signals = useSignalsStore()
const valueTablesStore = useValueTablesStore()
const ui = useUiStore()
const msg = computed(() => store.selectedMessage)

// 动态报文标签页时为 true（centerTab 形如 'msg_{id}'）
const isDynamicMsgTab = computed(() => typeof ui.centerTab === 'string' && ui.centerTab.startsWith('msg_'))

const selectedSig = computed(() => {
  if (!msg.value || !ui.selectedSignalName) return null
  return msg.value.signals[ui.selectedSignalName] || null
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
  signals.updateSignal(ui.selectedSignalName, 'value_table_name', localValueTableName.value, msg.value?.id).catch(() => {})
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

// 从 selectedSig.value_table_name 同步
watch(() => selectedSig.value?.value_table_name, (v) => {
  localValueTableName.value = v || ''
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
  signals.updateSignal(ui.selectedSignalName, 'start_bit', valueToSend, msg.value?.id).catch(() => {})
}

function updateSignal(field, value) {
  if (ui.selectedSignalName) {
    signals.updateSignal(ui.selectedSignalName, field, value, msg.value?.id).catch(() => {})
  }
}

function handleByteOrderChange(e) {
  if (!ui.selectedSignalName) return
  const oldOrder = selectedSig.value?.byte_order
  signals.updateSignal(ui.selectedSignalName, 'byte_order', e.target.value, msg.value?.id)
    .catch(() => { if (oldOrder != null) e.target.value = oldOrder })
}
</script>

<style scoped>
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
</style>
