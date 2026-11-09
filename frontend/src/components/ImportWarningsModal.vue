<template>
  <Teleport to="body">
    <div class="modal-overlay" @mousedown.self="$emit('close')">
      <div class="modal import-warnings-modal">
        <h3>{{ t('importWarnings.title') }}</h3>
        <p class="warn-desc">{{ t('importWarnings.desc') }}</p>

        <div class="warn-list">
          <div v-for="(w, i) in warnings" :key="i" class="warn-item">
            <div class="warn-head">
              <span class="warn-code">{{ codeLabel(w.code) }}</span>
              <span class="warn-level">{{ w.level_label || w.level }}</span>
              <span class="warn-name">{{ w.name }}</span>
              <span class="warn-count">{{ t('importWarnings.count', { count: w.count }) }}</span>
            </div>
            <div v-if="w.examples && w.examples.length" class="warn-examples">
              {{ t('importWarnings.examples') }}: {{ w.examples.join(', ') }}
            </div>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn btn-confirm" @click="$emit('close')">
            {{ t('importWarnings.close') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { t } from '../i18n.js'

defineProps({
  warnings: { type: Array, default: () => [] },
})
defineEmits(['close'])

function codeLabel(code) {
  const key = `importWarnings.code.${code}`
  const value = t(key)
  return value === key ? code : value
}
</script>

<style scoped>
.import-warnings-modal {
  max-width: 640px;
  width: 90vw;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
}
.warn-desc {
  color: var(--text-dim);
  font-size: 12px;
  margin: 6px 0 10px;
}
.warn-list {
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.warn-item {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.warn-item:last-child {
  border-bottom: none;
}
.warn-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.warn-code {
  color: var(--warn, #e6a23c);
  font-weight: 600;
}
.warn-level {
  color: var(--text-muted);
  font-size: 11px;
}
.warn-name {
  font-family: var(--font-mono);
  color: var(--text);
}
.warn-count {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 11px;
}
.warn-examples {
  margin-top: 4px;
  color: var(--text-dim);
  font-size: 11px;
  word-break: break-all;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>