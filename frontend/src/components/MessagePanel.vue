<template>
  <div class="panel">
    <div v-if="!msg" class="panel-empty" v-html="t('panel.empty')">
    </div>
    <template v-else>
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.properties') }}</div>
        <div class="field">
          <label>{{ t('panel.id') }}</label>
          <input class="mono" :value="toHex(msg.id)" @blur="e => update('id', parseHex(e.target.value))">
        </div>
        <div class="field">
          <label>{{ t('panel.name') }}</label>
          <input :value="msg.name" @blur="e => update('name', e.target.value)">
        </div>
        <div class="field-row">
          <div class="field">
            <label>{{ t('panel.dlc') }}</label>
            <input class="mono" type="number" min="0" max="8" :value="msg.dlc" @blur="e => update('dlc', parseInt(e.target.value)||8)">
          </div>
          <div class="field">
            <label>{{ t('panel.cycle') }}</label>
            <input class="mono" type="number" min="0" :value="msg.cycle_time" @blur="e => update('cycle_time', parseInt(e.target.value)||0)">
          </div>
        </div>
        <div class="field">
          <label>{{ t('panel.sender') }}</label>
          <input :value="msg.sender" @blur="e => update('sender', e.target.value)">
        </div>
        <div class="field">
          <label>{{ t('panel.comment') }}</label>
          <textarea rows="2" :value="msg.comment" @blur="e => update('comment', e.target.value)"></textarea>
        </div>
      </div>
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.actions') }}</div>
        <button class="btn" @click="duplicate" style="width:100%">{{ t('panel.duplicate') }}</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'

const store = useEditorStore()
const msg = computed(() => store.selectedMessage)

function update(field, value) {
  store.updateMessageField(field, value)
}

function duplicate() {
  store.duplicateMessage()
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
.field input, .field textarea {
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
.field input:focus, .field textarea:focus { border-color: var(--accent-dim); }
.field input.mono { font-family: var(--font-mono); }
.field textarea { resize: vertical; }

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
