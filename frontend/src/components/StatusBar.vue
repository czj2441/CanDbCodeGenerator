<template>
  <div class="statusbar">
    <span>{{ store.messageCount }} {{ store.messageCount === 1 ? t('status.message') : t('status.messages') }}</span>
    <span>{{ store.signalCount }} {{ store.signalCount === 1 ? t('status.signal') : t('status.signals') }}</span>
    <span class="spacer"></span>
    <span class="save-indicator" :class="saveClass">
      <template v-if="store.saveStatus === 'saving'">
        <span class="save-spinner">⏳</span> {{ t('status.saving') }}
      </template>
      <template v-else-if="store.saveStatus === 'saved' && !store.backendDirty">
        <span class="save-check">✓</span> {{ t('status.saved') }}
      </template>
      <template v-else-if="store.backendDirty">
        <span class="save-dot">●</span> {{ t('status.unsaved') }}
      </template>
    </span>
    <span class="version-tag">{{ manualVersion }} {{ autoVersion }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { t } from '../i18n.js'
const store = useEditorStore()
const saveClass = computed(() => {
  if (store.saveStatus === 'saving') return 'saving'
  if (store.saveStatus === 'saved' && !store.backendDirty) return 'saved'
  if (store.backendDirty) return 'modified'
  return ''
})
const manualVersion = typeof __MANUAL_VERSION__ !== 'undefined' ? __MANUAL_VERSION__ : 'dev'
const autoVersion = typeof __AUTO_VERSION__ !== 'undefined' ? __AUTO_VERSION__ : 'dev'
</script>

<style scoped>
.statusbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  height: 26px;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.spacer { flex: 1; }
.save-indicator { display: flex; align-items: center; gap: 4px; transition: var(--transition); }
.save-indicator.saved { color: var(--accent); }
.save-indicator.saving { color: var(--text-muted); }
.save-indicator.modified { color: var(--warn); }
.save-check { color: var(--accent); }
.save-dot { color: var(--warn); }
@keyframes spin { to { transform: rotate(360deg); } }
.save-spinner { display: inline-block; animation: spin 1s linear infinite; font-style: normal; }
.version-tag { font-family: var(--font-mono); font-size: 10px; opacity: 0.6; }
</style>
