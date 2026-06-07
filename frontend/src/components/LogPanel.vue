<template>
  <div v-if="ui.showLogPanel" class="log-panel" :style="{ height: panelHeight + 'px' }">
    <div class="log-resize" @mousedown="startResize"></div>
    <div class="log-header">
      <span class="log-title">{{ t('log.title') }}</span>
      <div class="log-actions">
        <button class="log-btn" @click="store.clearLog()">{{ t('log.clear') }}</button>
      </div>
    </div>
    <div ref="logBody" class="log-body">
      <div
        v-for="(entry, idx) in store.logEntries"
        :key="idx"
        class="log-row"
        :class="'log-' + entry.type"
      >
        <span class="log-time">{{ entry.time }}</span>
        <span class="log-type">{{ typeLabel(entry.type) }}</span>
        <span class="log-desc">{{ entry.description }}</span>
      </div>
      <div v-if="store.logEntries.length === 0" class="log-empty">
        {{ t('log.empty') }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

const store = useEditorStore()
const ui = useUiStore()
const logBody = ref(null)
const panelHeight = ref(160)
let isResizing = false
let startY = 0
let startHeight = 0

const typeLabels = computed(() => ({
  undo: t('log.type.undo'),
  redo: t('log.type.redo'),
  update: t('log.type.update'),
  add: t('log.type.add'),
  delete: t('log.type.delete'),
  batch: t('log.type.batch'),
  info: t('log.type.info'),
}))

function typeLabel(type) {
  return typeLabels.value[type] || type
}

function startResize(e) {
  isResizing = true
  startY = e.clientY
  startHeight = panelHeight.value
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
}

function onResize(e) {
  if (!isResizing) return
  const delta = startY - e.clientY
  panelHeight.value = Math.max(60, Math.min(400, startHeight + delta))
}

function stopResize() {
  isResizing = false
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
}

// 新日志自动滚动到顶部
watch(() => store.logEntries.length, () => {
  nextTick(() => {
    if (logBody.value) {
      logBody.value.scrollTop = 0
    }
  })
})
</script>

<style scoped>
.log-panel {
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--border);
  background: var(--bg-panel);
  flex-shrink: 0;
  overflow: hidden;
}

.log-resize {
  height: 4px;
  background: var(--border);
  cursor: row-resize;
  flex-shrink: 0;
  transition: background 150ms;
}

.log-resize:hover {
  background: var(--accent);
}

.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.log-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.log-actions {
  display: flex;
  gap: 4px;
}

.log-btn {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--border);
  background: var(--bg-raised);
  color: var(--text-dim);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 150ms;
}

.log-btn:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.log-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
}

.log-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.log-row:hover {
  background: var(--bg-hover);
}

.log-time {
  color: var(--text-muted);
  flex-shrink: 0;
  min-width: 60px;
}

.log-type {
  flex-shrink: 0;
  min-width: 40px;
  font-weight: 600;
  font-size: 10px;
  padding: 0 4px;
  border-radius: var(--radius-sm);
}

.log-undo .log-type { color: var(--info); background: oklch(0.72 0.14 240 / 0.15); }
.log-redo .log-type { color: var(--accent); background: oklch(0.68 0.18 155 / 0.15); }
.log-update .log-type { color: var(--warn); background: oklch(0.72 0.17 80 / 0.15); }
.log-add .log-type { color: var(--accent); background: oklch(0.68 0.18 155 / 0.15); }
.log-delete .log-type { color: var(--danger); background: oklch(0.60 0.20 25 / 0.15); }
.log-batch .log-type { color: var(--accent-dim); background: oklch(0.55 0.12 155 / 0.15); }
.log-info .log-type { color: var(--text-dim); background: var(--bg-hover); }

.log-desc {
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
}

.log-empty {
  padding: 16px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
