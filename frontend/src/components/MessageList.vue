<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <span>{{ t('msglist.title') }}</span>
      <button class="btn-icon" @click="messages.addMessage()" :title="t('msglist.addTooltip')">+</button>
    </div>
    <div class="message-list">
      <div
        v-for="m in store.messages"
        :key="m.id"
        class="message-item"
        :class="{ active: store.selectedMsgId === m.id }"
        @click="messages.selectMessage(m.id)"
      >
        <span class="message-id">{{ m.id_hex || toHex(m.id) }}</span>
        <span class="message-name">{{ m.name || t('msglist.unnamed') }}</span>
        <span class="message-signal-count">{{ m.signal_count }}s</span>
      </div>
      <div v-if="store.messages.length === 0" class="empty" v-html="t('msglist.empty')">
      </div>
    </div>
  </div>
</template>

<script setup>
import { useEditorStore } from '../stores/editor.js'
import { useMessagesStore } from '../stores/messages.js'
import { t } from '../i18n.js'
import { toHex } from '../utils/format.js'
const store = useEditorStore()
const messages = useMessagesStore()
</script>

<style scoped>
.sidebar {
  width: 240px;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  flex-shrink: 0;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
}

.btn-icon {
  width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 16px;
  cursor: pointer;
  border-radius: var(--radius-sm);
}
.btn-icon:hover { background: var(--bg-hover); color: var(--text); }

.message-list { flex: 1; overflow-y: auto; padding: 4px; }

.message-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  transition: var(--transition);
}
.message-item:hover { background: var(--bg-hover); }
.message-item.active {
  background: var(--signal-bg);
  border-left: 2px solid var(--accent);
  padding-left: 8px;
}

.message-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  min-width: 42px;
}
.message-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.message-signal-count {
  font-size: 10px;
  color: var(--text-muted);
  background: var(--bg-raised);
  padding: 1px 5px;
  border-radius: 10px;
}

.empty {
  padding: 40px 16px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}
</style>
