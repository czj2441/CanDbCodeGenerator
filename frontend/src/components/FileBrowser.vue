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
        <button 
          v-else 
          class="steal-btn"
          @click="confirmSteal(file)"
        >{{ t('browser.steal') }}</button>
      </div>
    </div>

    <!-- 抢占确认对话框 -->
    <div v-if="stealModalOpen" class="modal-overlay" @click="closeStealModal">
      <div class="modal-box" @click.stop>
        <h3>{{ t('browser.stealConfirmTitle') }}</h3>
        <p>
          <strong>{{ stealingFile?.name }}</strong><br>
          {{ t('browser.stealConfirmDesc') }}
        </p>
        <div class="modal-actions">
          <button class="btn btn-cancel" @click="closeStealModal">{{ t('browser.stealCancel') }}</button>
          <button class="btn btn-confirm" @click="executeSteal">{{ t('browser.stealConfirm') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api, getSessionId, notifySessionStolen } from '../api/client.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

const emit = defineEmits(['open'])

const files = ref([])
const openingSessionId = ref(null)  // 防止重复点击
const stealModalOpen = ref(false)
const stealingFile = ref(null)
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
    return
  }
  // 防止重复点击
  if (openingSessionId.value === file.session_id) return
  openingSessionId.value = file.session_id
  emit('open', file.session_id)
  // 500ms 后重置
  setTimeout(() => { openingSessionId.value = null }, 500)
}

function confirmSteal(file) {
  stealingFile.value = file
  stealModalOpen.value = true
}

function closeStealModal() {
  stealModalOpen.value = false
  stealingFile.value = null
}

async function executeSteal() {
  if (!stealingFile.value) return
  const targetSid = stealingFile.value.session_id
  const targetFileName = stealingFile.value.name
  
  try {
    const ui = useUiStore()
    
    // 调用后端 API 释放目标 session 的文件锁
    await api('POST', '/api/steal', { 
      target_session_id: targetSid 
    })
    
    // 通知其他标签页该 session 已被抢占
    notifySessionStolen(targetSid)
    
    ui.showToast(t('toast.stealSuccess') + ': ' + targetFileName)
    
    // 关闭对话框
    closeStealModal()
    
    // 重新加载文件列表
    await loadFiles()
    
    // 从更新后的列表中找到该文件并打开
    const updatedFile = files.value.find(f => f.name === targetFileName)
    if (updatedFile && !updatedFile.is_locked) {
      open(updatedFile)
    }
  } catch (e) {
    const ui = useUiStore()
    ui.showToast(t('toast.stealFailed') + ': ' + e.message, true)
    closeStealModal()
  }
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

.steal-btn {
  background: var(--warn);
  border: 1px solid var(--warn);
  color: #fff;
  padding: 6px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  margin-left: 12px;
  font-weight: 500;
}
.steal-btn:hover {
  opacity: 0.9;
}

/* 模态对话框样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  max-width: 500px;
  width: 90%;
}

.modal-box h3 {
  margin: 0 0 12px 0;
  font-size: 18px;
  font-weight: 600;
}

.modal-box p {
  margin: 0 0 20px 0;
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.5;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn {
  padding: 8px 16px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
  border: 1px solid transparent;
}

.btn-cancel {
  background: transparent;
  border-color: var(--border);
  color: var(--text);
}
.btn-cancel:hover {
  background: var(--bg-raised);
}

.btn-confirm {
  background: var(--warn);
  color: #fff;
  border-color: var(--warn);
}
.btn-confirm:hover {
  opacity: 0.9;
}
</style>
