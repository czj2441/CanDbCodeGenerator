<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="modal-overlay" @click.self="close">
        <div class="modal-panel">
          <div class="modal-header">{{ t('batch.title') }}</div>
          <div class="modal-body">
            <div class="field">
              <label>{{ t('batch.nameTemplate') }}</label>
              <input class="mono" v-model="form.nameTemplate" spellcheck="false">
              <div class="hint">{{ t('batch.nameHint') }}</div>
            </div>
            <div class="row">
              <div class="field">
                <label>{{ t('batch.count') }}</label>
                <input class="mono" type="number" v-model.number="form.count" min="1" max="64">
              </div>
              <div class="field">
                <label>{{ t('batch.startNum') }}</label>
                <input class="mono" type="number" v-model.number="form.startNum" min="0">
              </div>
            </div>
            <div class="row">
              <div class="field">
                <label>{{ t('batch.startBit') }}</label>
                <input class="mono" type="number" v-model.number="form.startBit" min="0" max="63">
              </div>
              <div class="field">
                <label>{{ t('batch.bitStep') }}</label>
                <input class="mono" type="number" v-model.number="form.bitStep" min="1" max="64">
              </div>
            </div>
            <div class="row">
              <div class="field">
                <label>{{ t('batch.length') }}</label>
                <input class="mono" type="number" v-model.number="form.length" min="1" max="64">
              </div>
              <div class="field">
                <label>{{ t('batch.byteOrder') }}</label>
                <select v-model="form.byteOrder">
                  <option value="intel">{{ t('batch.intel') }}</option>
                  <option value="motorola">{{ t('batch.motorola') }}</option>
                </select>
              </div>
            </div>
            <div class="row">
              <div class="field"><label>{{ t('batch.factor') }}</label><input class="mono" type="number" step="any" v-model.number="form.factor"></div>
              <div class="field"><label>{{ t('batch.offset') }}</label><input class="mono" type="number" step="any" v-model.number="form.offset"></div>
            </div>
            <div class="row">
              <div class="field"><label>{{ t('batch.min') }}</label><input class="mono" type="number" step="any" v-model.number="form.minVal"></div>
              <div class="field"><label>{{ t('batch.max') }}</label><input class="mono" type="number" step="any" v-model.number="form.maxVal"></div>
            </div>
            <div class="field">
              <label>{{ t('batch.unit') }}</label>
              <input v-model="form.unit">
            </div>
            <div class="field">
              <label>{{ t('batch.commentTemplate') }}</label>
              <input v-model="form.commentTemplate" spellcheck="false">
              <div class="hint">{{ t('batch.commentHint') }}</div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="close">{{ t('batch.cancel') }}</button>
            <button class="btn btn-accent" @click="create">{{ t('batch.create') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { reactive } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { t } from '../i18n.js'

const store = useEditorStore()

const visible = defineModel('visible', { type: Boolean, default: false })

const form = reactive({
  nameTemplate: 'PTA{n:02d}_AdVal',
  count: 8,
  startNum: 1,
  startBit: 0,
  bitStep: 8,
  length: 8,
  byteOrder: 'motorola',
  factor: 1.0,
  offset: 0.0,
  minVal: 0.0,
  maxVal: 0.0,
  unit: '',
  commentTemplate: '',
})

function close() {
  visible.value = false
}

async function create() {
  await store.batchAddSignals({ ...form })
  close()
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: oklch(0.08 0.01 260 / 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 520px;
  max-width: 92vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow);
}

.modal-header {
  padding: 14px 18px;
  font-size: 14px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}

.modal-body {
  padding: 14px 18px;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--border);
}

.field { margin-bottom: 10px; }
.field label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 3px;
}
.field input, .field select {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.field input:focus, .field select:focus { border-color: var(--accent-dim); }
.field input.mono { font-family: var(--font-mono); }
.field .hint {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
}

.row { display: flex; gap: 10px; }
.row .field { flex: 1; }

.btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.btn:hover { background: var(--bg-hover); }
.btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}

.modal-enter-active, .modal-leave-active { transition: opacity 200ms; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>
