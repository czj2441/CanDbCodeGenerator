<template>
  <div class="statusbar">
    <span>{{ store.messageCount }} {{ store.messageCount === 1 ? t('status.message') : t('status.messages') }}</span>
    <span>{{ store.signalCount }} {{ store.signalCount === 1 ? t('status.signal') : t('status.signals') }}</span>
    <span class="spacer"></span>
    <span v-if="store.backendDirty" class="modified">{{ t('status.modified') }}</span>
    <span class="version-tag">{{ manualVersion }} {{ autoVersion }}</span>
  </div>
</template>

<script setup>
import { useEditorStore } from '../stores/editor.js'
import { t } from '../i18n.js'
const store = useEditorStore()
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
.modified { color: var(--warn); }
.version-tag { font-family: var(--font-mono); font-size: 10px; opacity: 0.6; }
</style>
