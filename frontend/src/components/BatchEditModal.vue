<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="modal-overlay" @mousedown.self="close">
        <div class="modal-panel">
          <div class="modal-header">{{ t('batchEdit.title') }} — {{ t('multiselect.selectedCount', { count: selectedCount }) }}</div>
          <div class="modal-body">
            <div v-for="field in fields" :key="field.key" class="field-row">
              <label class="field-check">
                <input type="checkbox" v-model="checked[field.key]">
                <span class="field-label">{{ t(field.i18n) }}</span>
              </label>
              <div class="field-input">
                <template v-if="field.type === 'select'">
                  <select v-model="values[field.key]" :disabled="!checked[field.key]">
                    <option v-for="opt in field.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                </template>
                <template v-else-if="field.type === 'number'">
                  <input class="mono" type="number" step="any" v-model.number="values[field.key]" :disabled="!checked[field.key]">
                </template>
                <template v-else>
                  <input v-model="values[field.key]" :disabled="!checked[field.key]" spellcheck="false">
                </template>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="close">{{ t('batch.cancel') }}</button>
            <button class="btn btn-accent" :disabled="!hasCheckedFields" @click="apply">{{ t('batchEdit.apply') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { reactive, computed, watch } from 'vue'
import { t } from '../i18n.js'

const props = defineProps({
  fields: { type: Array, required: true },
  selectedCount: { type: Number, default: 0 },
})

const visible = defineModel('visible', { type: Boolean, default: false })
const emit = defineEmits(['apply'])

// 每个字段的勾选状态和值
const checked = reactive({})
const values = reactive({})

// 初始化 / 重置
watch(visible, (newVal) => {
  if (newVal) {
    for (const field of props.fields) {
      checked[field.key] = false
      values[field.key] = field.default ?? ''
    }
  }
})

const hasCheckedFields = computed(() => {
  return props.fields.some(f => checked[f.key])
})

function close() {
  visible.value = false
}

function apply() {
  const result = {}
  for (const field of props.fields) {
    if (checked[field.key]) {
      result[field.key] = values[field.key]
    }
  }
  emit('apply', result)
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
  width: 480px;
  max-width: 92vw;
  max-height: 80vh;
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

.field-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.field-check {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 120px;
  cursor: pointer;
}

.field-check input[type="checkbox"] {
  accent-color: var(--accent);
  cursor: pointer;
}

.field-label {
  font-size: 12px;
  color: var(--text);
  user-select: none;
}

.field-input {
  flex: 1;
}

.field-input input, .field-input select {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}

.field-input input:focus, .field-input select:focus { border-color: var(--accent-dim); }
.field-input input:disabled, .field-input select:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.field-input input.mono { font-family: var(--font-mono); }

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
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}

.modal-enter-active, .modal-leave-active { transition: opacity 200ms; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>
