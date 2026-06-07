<template>
  <div class="file-browser">
    <div class="browser-header">
      <h2>{{ t('browser.title') }}</h2>
      <button class="new-file-btn" @click="createNew">{{ t('browser.newFile') }}</button>
    </div>
    <div class="file-list">
      <div v-if="files.length === 0" class="empty">{{ t('history.empty') }}</div>
      <div
        v-for="file in files"
        :key="file.session_id"
        class="file-item"
        :class="{ locked: file.is_locked }"
      >
        <div class="file-info" @click="open(file)">
          <div class="file-name">{{ file.name }}</div>
          <div class="file-meta">
            {{ file.message_count }} messages · {{ file.signal_count }} signals · {{ formatTime(file.mtime) }}
            <span v-if="file.is_locked" class="lock-badge">{{ t('browser.locked') }}</span>
          </div>
        </div>
        <button
          v-if="!file.is_locked"
          class="open-btn"
          @click="open(file)"
        >{{ t('browser.open') }}</button>
        <button v-else class="open-btn" disabled>{{ t('browser.locked') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api, getSessionId } from '../api/client.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

const emit = defineEmits(['open'])

const files = ref([])
const openingSessionId = ref(null)  // 防止重复点击
let refreshTimer = null

async function loadFiles() {
  try {
    const currentSid = getSessionId()
    files.value = await api('GET', '/api/sessions', null, { 'X-Session-Id': currentSid })
  } catch (e) {
    const ui = useUiStore()
    ui.showToast(e.message, true)
  }
}

function open(file) {
  if (file.is_locked) {
    const ui = useUiStore()
    ui.showToast(t('toast.fileLocked'), true)
    return
  }
  // 防止重复点击
  if (openingSessionId.value === file.session_id) return
  openingSessionId.value = file.session_id
  emit('open', file.session_id)
  // 500ms 后重置
  setTimeout(() => { openingSessionId.value = null }, 500)
}

async function createNew() {
  try {
    const data = await api('POST', '/api/new', { name: 'Untitled' })
    emit('open', data.session_id)
  } catch (e) {
    const ui = useUiStore()
    ui.showToast(e.message, true)
  }
}

function formatTime(ts) {
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

onMounted(() => {
  loadFiles()
  refreshTimer = setInterval(loadFiles, 5000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.file-browser {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
  color: var(--text);
}

.browser-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}

.browser-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.new-file-btn {
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 8px 16px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
}
.new-file-btn:hover {
  opacity: 0.9;
}

.file-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty {
  text-align: center;
  color: var(--text-muted);
  padding: 48px;
  font-size: 14px;
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: background 150ms;
}
.file-item:hover {
  background: var(--bg-raised);
}
.file-item.locked {
  opacity: 0.6;
}

.file-info {
  flex: 1;
  cursor: pointer;
  min-width: 0;
}

.file-name {
  font-weight: 500;
  font-size: 14px;
  margin-bottom: 4px;
}

.file-meta {
  font-size: 12px;
  color: var(--text-muted);
}

.lock-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  background: var(--warn);
  color: #fff;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
}

.open-btn {
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 6px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  margin-left: 12px;
  font-weight: 500;
}
.open-btn:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}
.open-btn:disabled {
  border-color: var(--border);
  color: var(--text-muted);
  cursor: not-allowed;
}
</style>
