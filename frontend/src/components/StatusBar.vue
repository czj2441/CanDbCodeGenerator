<template>
  <div class="statusbar">
    <span>{{ store.messageCount }} {{ store.messageCount === 1 ? t('status.message') : t('status.messages') }}</span>
    <span>{{ store.signalCount }} {{ store.signalCount === 1 ? t('status.signal') : t('status.signals') }}</span>
    <span class="spacer"></span>
    <span v-if="store.modified" class="modified">{{ t('status.modified') }}</span>
  </div>
</template>

<script setup>
import { useEditorStore } from '../stores/editor.js'
import { t } from '../i18n.js'
const store = useEditorStore()
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
</style>
