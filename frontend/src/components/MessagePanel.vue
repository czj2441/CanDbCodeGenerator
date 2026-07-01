<template>
  <div class="panel">
    <!-- 信号属性区域 -->
    <template v-if="selectedSig">
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
          <select :value="selectedSig.byte_order" @change="e => updateSignal('byte_order', e.target.value)">
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
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.signalActions') }}</div>
        <button class="btn" @click="copySig" style="width:100%;margin-bottom:6px">{{ t('panel.copySignal') }}</button>
        <button class="btn btn-danger" @click="deleteSig" style="width:100%">{{ t('panel.deleteSignal') }}</button>
      </div>
    </template>

    <!-- 报文属性区域 -->
    <template v-else-if="msg">
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
            <input class="mono" type="number" min="1" max="8" v-lazy-value="msg.dlc" @blur="e => update('dlc', parseInt(e.target.value))">
          </div>
          <div class="field">
            <label>{{ t('panel.cycle') }}</label>
            <input class="mono" type="number" min="0" v-lazy-value="msg.cycle_time" @blur="e => update('cycle_time', parseInt(e.target.value))">
          </div>
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
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.actions') }}</div>
        <button class="btn" @click="duplicate" style="width:100%">{{ t('panel.duplicate') }}</button>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-else class="panel-empty" v-html="t('panel.empty')">
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'
import { toDisplayStartBit, toStorageStartBit } from '../utils/signalLayout.js'
import { vLazyValue } from '../directives/lazyValue.js'

function showToast(msg, isError = false) {
  useUiStore().showToast(msg, isError)
}

const store = useEditorStore()
const ui = useUiStore()
const msg = computed(() => store.selectedMessage)
const selectedSig = computed(() => {
  if (!msg.value || !ui.selectedSignalUuid) return null
  return msg.value.signals.find(s => s.uuid === ui.selectedSignalUuid) || null
})

/**
 * 显示用的起始位：Motorola 信号显示 LSB，Intel 信号显示原始 start_bit
 */
function showDisplayStartBit() {
  if (!selectedSig.value) return 0
  return toDisplayStartBit(selectedSig.value.start_bit, selectedSig.value.length, selectedSig.value.byte_order)
}

/**
 * 编辑起始位：Motorola 信号将用户输入的 display start bit 转换为 storage start bit (MSB) 存储
 */
function modifyDisplayStartBit(displayValue) {
  if (!selectedSig.value) return
  const msbValue = toStorageStartBit(displayValue, selectedSig.value.length, selectedSig.value.byte_order, 63, selectedSig.value.start_bit)
  if (msbValue >= 0) {
    store.updateSignal(ui.selectedSignalUuid, 'start_bit', msbValue)
  } else {
    showToast(`起始位 ${displayValue} 对于 ${selectedSig.value.byte_order} length=${selectedSig.value.length} 不合法`, true)
  }
}

function update(field, value) {
  store.updateMessageField(field, value)
}

function updateSignal(field, value) {
  if (ui.selectedSignalUuid) {
    store.updateSignal(ui.selectedSignalUuid, field, value)
  }
}

function duplicate() {
  store.duplicateMessage()
}

function copySig() {
  if (ui.selectedSignalUuid) {
    store.copySignal(ui.selectedSignalUuid)
  }
}

function deleteSig() {
  if (ui.selectedSignalUuid) {
    store.deleteSignal(ui.selectedSignalUuid)
  }
}
</script>

<style scoped>
.panel {
  width: 280px;
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
</style>
