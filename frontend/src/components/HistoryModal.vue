<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="ui.historyModalOpen" class="modal-overlay" @click="ui.historyModalOpen = false">
        <div class="modal-content" @click.stop>
          <div class="modal-header">
            <h3>{{ t('history.title') }}</h3>
            <button class="close-btn" @click="ui.historyModalOpen = false">&times;</button>
          </div>
          <div class="modal-body">
            <div v-if="store.sessionHistory.length === 0" class="empty">{{ t('history.empty') }}</div>
            <div v-else class="history-list">
              <div
                v-for="item in store.sessionHistory"
                :key="item.session_id"
                class="history-item"
                :class="{ locked: item.is_locked }"
              >
                <div class="history-info" @click="load(item.session_id)">
                  <div class="history-name">{{ item.name }}</div>
                  <div class="history-meta">
                    {{ item.message_count }} messages · {{ item.signal_count }} signals · {{ formatTime(item.mtime) }}
                    <span v-if="item.is_locked" class="lock-badge">{{ t('browser.locked') }}</span>
                  </div>
                </div>
                <button class="delete-btn" @click.stop="del(item.session_id)">{{ t('history.delete') }}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { useUiStore } from '../stores/uiStore.js'
import { useEditorStore } from '../stores/editor.js'
import { t } from '../i18n.js'

const ui = useUiStore()
const store = useEditorStore()

function formatTime(ts) {
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

async function load(sessionId) {
  try {
    await store.loadHistorySession(sessionId)
    ui.historyModalOpen = false
  } catch (e) {
    // loadHistorySession 内部已显示 Toast，这里只需阻止关闭弹窗
    console.error('Failed to load session:', e)
  }
}

async function del(sessionId) {
  if (!confirm(t('history.deleteConfirm'))) return
  await store.deleteHistorySession(sessionId)
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1500;
}

.modal-content {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 520px;
  max-width: 90vw;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}

.modal-header h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 20px;
  cursor: pointer;
  line-height: 1;
}
.close-btn:hover { color: var(--text); }

.modal-body {
  padding: 12px;
  overflow-y: auto;
  flex: 1;
}

.empty {
  text-align: center;
  color: var(--text-muted);
  padding: 32px;
  font-size: 13px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--bg);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  transition: background 100ms;
}
.history-item:hover {
  background: var(--bg-raised);
}

.history-info {
  flex: 1;
  cursor: pointer;
  min-width: 0;
}
.history-item.locked .history-info {
  opacity: 0.5;
  pointer-events: none;
}

.history-name {
  font-weight: 500;
  font-size: 13px;
  margin-bottom: 2px;
}

.history-meta {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.lock-badge {
  background: var(--warn);
  color: oklch(0.15 0.01 80);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
}

.delete-btn {
  background: transparent;
  border: 1px solid var(--danger);
  color: var(--danger);
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  margin-left: 10px;
}
.delete-btn:hover {
  background: var(--danger);
  color: #fff;
}

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
