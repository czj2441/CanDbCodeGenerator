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
          </select>
        </div>

        <!-- 全局表只读预览 -->
        <template v-if="localValueTableName && valueTablePreview">
          <div class="vt-preview-header">
            <span>{{ t('panel.valueTablePreview') }}: {{ localValueTableName }}</span>
            <button class="btn btn-sm" @click="openValueTableManager">{{ t('panel.editValueTable') }}</button>
          </div>
          <div class="vt-preview">
            <div v-for="(desc, val) in valueTablePreview" :key="val" class="vt-preview-row">
              <span class="vt-preview-val mono">{{ val }}</span>
              <span class="vt-preview-desc">{{ desc }}</span>
            </div>
          </div>
        </template>
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


      <!-- 值描述统计 -->
      <div class="panel-section" v-if="msg.signals.length > 0">
        <div class="panel-section-title">{{ t('panel.valTableStats') }}</div>
        <div class="vt-stats">{{ valTableStatsText }}</div>
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
import { computed, ref, watch } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useMessagesStore } from '../stores/messages.js'
import { useSignalsStore } from '../stores/signals.js'
import { useClipboardStore } from '../stores/clipboard.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'
import { toDisplayStartBit, toStorageStartBit } from '../utils/signalLayout.js'
import { vLazyValue } from '../directives/lazyValue.js'

const store = useEditorStore()
const messages = useMessagesStore()
const signals = useSignalsStore()
const clipboard = useClipboardStore()
const ui = useUiStore()
const msg = computed(() => store.selectedMessage)

// ── 报文位使用率 ──
const totalBits = computed(() => {
  if (!msg.value) return 0
  return msg.value.signals.reduce((sum, s) => sum + (s.length || 0), 0)
})
const maxBits = computed(() => (msg.value?.dlc || 0) * 8)
const bitUsagePct = computed(() => maxBits.value > 0 ? Math.min(100, (totalBits.value / maxBits.value) * 100) : 0)
const bitUsageClass = computed(() => {
  const pct = bitUsagePct.value
  if (pct >= 100) return 'danger'
  if (pct >= 75) return 'warn'
  return 'ok'
})

// ── 报文值描述统计 ──
const valTableStatsText = computed(() => {
  if (!msg.value?.signals) return ''
  let refCount = 0, noneCount = 0
  for (const sig of msg.value.signals) {
    if (sig.value_table_name) refCount++
    else noneCount++
  }
  const parts = []
  if (refCount) parts.push(t('panel.statsRefCount', { count: refCount }))
  if (noneCount) parts.push(t('panel.statsNoneCount', { count: noneCount }))
  return parts.join(' · ') || t('panel.statsNoSignals')
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
  if (!ui.selectedSignalUuid) return
  signals.updateSignal(ui.selectedSignalUuid, 'value_table_name', localValueTableName.value).catch(() => {})
}

function openValueTableManager() {
  ui.valueTableFocusName = localValueTableName.value
  ui.switchCenterTab('valtables')
}

// 从 selectedSig.value_table_name 同步
watch(() => selectedSig.value?.value_table_name, (v) => {
  localValueTableName.value = v || ''
}, { immediate: true })


// 本地 is_fd 状态：从 msg.is_fd 同步，用于 v-model 双向绑定
const localIsFd = ref(msg.value?.is_fd ? 'true' : 'false')
const isFdEl = ref(null)
watch(() => msg.value?.is_fd, (v) => {
  localIsFd.value = v ? 'true' : 'false'
}, { immediate: true })
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
 * 转换失败时仍发送请求，由后端校验，错误在 DataErrorList 展示
 */
function modifyDisplayStartBit(displayValue) {
  if (!selectedSig.value) return
  const msbValue = toStorageStartBit(displayValue, selectedSig.value.length, selectedSig.value.byte_order, 63, selectedSig.value.start_bit)
  const valueToSend = msbValue >= 0 ? msbValue : -1
  signals.updateSignal(ui.selectedSignalUuid, 'start_bit', valueToSend).catch(() => {})
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
      // 后端拒绝时，updateMessageField 已将缓存恢复为后端值
      // 同步本地 ref 并强制 DOM 恢复
      localIsFd.value = msg.value?.is_fd ? 'true' : 'false'
      if (isFdEl.value) {
        isFdEl.value.value = localIsFd.value
      }
    })
}

function updateSignal(field, value) {
  if (ui.selectedSignalUuid) {
    signals.updateSignal(ui.selectedSignalUuid, field, value).catch(() => {})
  }
}

function handleByteOrderChange(e) {
  if (!ui.selectedSignalUuid) return
  const oldOrder = selectedSig.value?.byte_order
  signals.updateSignal(ui.selectedSignalUuid, 'byte_order', e.target.value)
    .catch(() => { if (oldOrder != null) e.target.value = oldOrder })
}

function duplicate() {
  clipboard.duplicateMessage()
}

function copySig() {
  if (ui.selectedSignalUuid) {
    clipboard.copySignal(ui.selectedSignalUuid)
  }
}

function deleteSig() {
  if (ui.selectedSignalUuid) {
    signals.deleteSignal(ui.selectedSignalUuid)
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

/* ── 值描述表预览 ── */
.vt-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--text-muted);
}
.btn-sm {
  padding: 2px 8px;
  font-size: 10px;
}
.vt-preview {
  max-height: 150px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
}
.vt-preview-row {
  display: flex;
  gap: 8px;
  padding: 3px 8px;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.vt-preview-row:last-child { border-bottom: none; }
.vt-preview-val { width: 50px; color: var(--text-dim); text-align: right; }
.vt-preview-desc { flex: 1; }

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

/* ── 值描述统计 ── */
.vt-stats { font-size: 11px; color: var(--text-muted); line-height: 1.6; }
</style>
