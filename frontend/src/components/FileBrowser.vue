<template>
  <div class="file-browser">
    <div class="browser-header">
      <h2>{{ t('browser.title') }}</h2>
      <div class="header-actions">
        <button class="new-file-btn" @click="createNew">{{ t('browser.newFile') }}</button>
        <button 
          v-if="selectedFiles.length > 0" 
          class="delete-btn"
          :disabled="deleting"
          @click="confirmDelete"
        >
          {{ deleting ? '删除中...' : `${t('browser.deleteSelected')} (${selectedFiles.length})` }}
        </button>
      </div>
    </div>

    <!-- 表格形式文件列表 -->
    <div class="table-container">
      <table class="file-table">
        <thead>
          <tr>
            <th class="col-checkbox">
              <input 
                type="checkbox" 
                :checked="selectAll" 
                :indeterminate="!selectAll && selectedFiles.length > 0"
                @change="toggleSelectAll"
              />
            </th>
            <th class="col-name">文件名</th>
            <th class="col-messages">报文</th>
            <th class="col-signals">信号</th>
            <th class="col-time">修改时间</th>
            <th class="col-status">状态</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="files.length === 0">
            <td colspan="7" class="empty-state">
              <div class="empty-state-content">
                <div class="empty-icon">📂</div>
                <p class="empty-title">{{ t('browser.emptyTitle') }}</p>
                <p class="empty-desc">{{ t('browser.emptyDesc') }}</p>
                <button class="empty-btn" @click="createNew">{{ t('browser.emptyNewBtn') }}</button>
                <ul class="empty-hints">
                  <li>{{ t('browser.emptyHint1') }}</li>
                  <li>{{ t('browser.emptyHint2') }}</li>
                  <li>{{ t('browser.emptyHint3') }}</li>
                </ul>
              </div>
            </td>
          </tr>
          <tr
            v-for="file in files"
            :key="file.file_name"
            class="file-row"
            :class="{ 
              'locked': file.is_locked,
              'selected': selectedFiles.includes(file.file_name)
            }"
            @click="toggleSelectFile(file)"
          >
            <td class="col-checkbox" @click.stop>
              <input 
                type="checkbox" 
                :checked="selectedFiles.includes(file.file_name)"
                :disabled="file.is_locked"
                @change="toggleSelectFile(file)"
              />
            </td>
            <td class="col-name" @click.stop="open(file)">
              <span class="file-name-link">{{ file.name }}</span>
            </td>
            <td class="col-messages">{{ file.message_count }}</td>
            <td class="col-signals">{{ file.signal_count }}</td>
            <td class="col-time">{{ formatTime(file.mtime) }}</td>
            <td class="col-status">
              <span v-if="file.is_locked" class="lock-badge">{{ t('browser.locked') }}</span>
              <span v-else-if="file.is_modified" class="unsaved-badge">{{ t('browser.unsaved') }}</span>
            </td>
            <td class="col-actions" @click.stop>
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
            </td>
          </tr>
        </tbody>
      </table>
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

    <!-- 删除确认对话框 -->
    <div v-if="deleteModalOpen" class="modal-overlay" @click="closeDeleteModal">
      <div class="modal-box" @click.stop>
        <h3>{{ t('browser.deleteConfirmTitle') }}</h3>
        <p>
          {{ t('browser.deleteConfirmDesc', { count: pendingDeleteFiles.length }) }}
          <ul class="file-list-preview">
            <li v-for="(file, idx) in displayedDeleteFiles" :key="file.session_id">
              {{ file.name }}
            </li>
            <li v-if="pendingDeleteFiles.length > 5" class="more-files">
              ... 等 {{ pendingDeleteFiles.length }} 个文件
            </li>
          </ul>
        </p>
        <div class="modal-actions">
          <button class="btn btn-cancel" @click="closeDeleteModal">{{ t('browser.deleteConfirmCancel') }}</button>
          <button class="btn btn-danger" :disabled="deleting" @click="executeDelete">
            {{ deleting ? '删除中...' : t('browser.deleteConfirmDelete') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新建文件对话框 -->
    <div v-if="newFileModalOpen" class="modal-overlay" @click="closeNewFileModal">
      <div class="modal-box" @click.stop>
        <h3>{{ t('browser.newFileTitle') }}</h3>
        <p>{{ t('browser.newFileLabel') }}</p>
        <input
          ref="newFileInputRef"
          v-model="newFileName"
          class="new-file-input"
          :placeholder="t('browser.newFilePlaceholder')"
          @keydown.enter="executeNewFile"
          @keydown.escape="closeNewFileModal"
        />
        <p v-if="newFileError" class="new-file-error">{{ newFileError }}</p>
        <div class="modal-actions">
          <button class="btn btn-cancel" @click="closeNewFileModal">{{ t('browser.newFileCancel') }}</button>
          <button class="btn btn-confirm" :disabled="creatingFile" @click="executeNewFile">
            {{ creatingFile ? '创建中...' : t('browser.newFileCreate') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 底部版本栏 -->
    <div class="browser-footer">
      <span class="version-tag">{{ manualVersion }} {{ autoVersion }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { getSessionId } from '../api/client.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'
import { WsSyncClient } from '../utils/ws-client.js'

const manualVersion = typeof __MANUAL_VERSION__ !== 'undefined' ? __MANUAL_VERSION__ : 'dev'
const autoVersion = typeof __AUTO_VERSION__ !== 'undefined' ? __AUTO_VERSION__ : 'dev'

const emit = defineEmits(['open', 'new'])

const files = ref([])
const openingSessionId = ref(null)  // 防止重复点击
const stealModalOpen = ref(false)
const stealingFile = ref(null)
const deleteModalOpen = ref(false)
const pendingDeleteFiles = ref([])
const selectedFiles = ref([])  // 存储选中的 file_name
const deleting = ref(false)
const newFileModalOpen = ref(false)
const newFileName = ref('')
const newFileError = ref('')
const creatingFile = ref(false)
const newFileInputRef = ref(null)
let wsClient = null       // FileBrowser 独立 WS 连接
let refreshTimer = null   // 周期性刷新列表

// 计算属性：是否全选
const selectAll = computed(() => {
  const unlockableFiles = files.value.filter(f => !f.is_locked)
  return unlockableFiles.length > 0 && unlockableFiles.every(f => selectedFiles.value.includes(f.file_name))
})

// 计算属性：显示在删除弹窗中的文件列表（最多显示5个）
const displayedDeleteFiles = computed(() => {
  return pendingDeleteFiles.value.slice(0, 5)
})

async function loadFiles() {
  try {
    if (!wsClient?.connected) {
      // WS 未连接时跳过
      return
    }
    const result = await wsClient.request('get_sessions', {
      current_session_id: ''  // 文件浏览器不排除任何 session
    })
    files.value = result
    const validIds = new Set(files.value.map(f => f.file_name))
    selectedFiles.value = selectedFiles.value.filter(id => validIds.has(id))
  } catch (e) {
    const ui = useUiStore()
    ui.showToast(e.message, true)
  }
}

// 切换单个文件的选中状态
function toggleSelectFile(file) {
  if (file.is_locked) return  // 锁定的文件不能被选中
  
  const idx = selectedFiles.value.indexOf(file.file_name)
  if (idx === -1) {
    selectedFiles.value.push(file.file_name)
  } else {
    selectedFiles.value.splice(idx, 1)
  }
}

// 全选/取消全选
function toggleSelectAll() {
  if (selectAll.value) {
    // 取消全选
    selectedFiles.value = []
  } else {
    // 全选所有未锁定的文件
    selectedFiles.value = files.value
      .filter(f => !f.is_locked)
      .map(f => f.file_name)
  }
}

// 确认删除
function confirmDelete() {
  if (selectedFiles.value.length === 0) return
  
  // 获取选中的文件对象
  pendingDeleteFiles.value = files.value.filter(f => selectedFiles.value.includes(f.file_name))
  deleteModalOpen.value = true
}

// 关闭删除弹窗
function closeDeleteModal() {
  deleteModalOpen.value = false
  pendingDeleteFiles.value = []
}

// 执行批量删除
async function executeDelete() {
  if (pendingDeleteFiles.value.length === 0) return
  
  deleting.value = true
  const ui = useUiStore()
  let successCount = 0
  let failedCount = 0
  
  try {
    for (const file of pendingDeleteFiles.value) {
      try {
        await wsClient.request('delete_file', {
          file_name: file.file_name,
          current_session_id: getSessionId() || ''
        })
        successCount++
      } catch (e) {
        console.error(`Failed to delete ${file.name}:`, e)
        failedCount++
      }
    }
    
    if (successCount > 0) {
      ui.showToast(t('toast.filesDeleted', { count: successCount }))
    }
    if (failedCount > 0) {
      ui.showToast(`${t('toast.deleteFailed')}: ${failedCount} 个文件`, true)
    }
    
    selectedFiles.value = []
    await loadFiles()
  } catch (e) {
    ui.showToast(t('toast.deleteFailed') + ': ' + e.message, true)
  } finally {
    deleting.value = false
    closeDeleteModal()
  }
}

function open(file) {
  if (file.is_locked) {
    return
  }
  // 防止重复点击
  if (openingSessionId.value === file.file_name) return
  openingSessionId.value = file.file_name
  emit('open', file.file_name)
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
  const targetSid = stealingFile.value.session_id || ''
  const targetFileName = stealingFile.value.name
  
  try {
    const ui = useUiStore()
    
    await wsClient.request('steal_lock', {
      target_session_id: targetSid,
      current_session_id: getSessionId() || ''
    })
    
    ui.showToast(t('toast.stealSuccess') + ': ' + targetFileName)
    closeStealModal()
    await loadFiles()
    
    const updatedFile = files.value.find(f => f.name === targetFileName)
    if (updatedFile) {
      open(updatedFile)
    }
  } catch (e) {
    const ui = useUiStore()
    ui.showToast(t('toast.stealFailed') + ': ' + e.message, true)
    closeStealModal()
  }
}

async function createNew() {
  newFileName.value = 'Untitled'
  newFileError.value = ''
  newFileModalOpen.value = true
  nextTick(() => {
    newFileInputRef.value?.focus()
    newFileInputRef.value?.select()
  })
}

function closeNewFileModal() {
  newFileModalOpen.value = false
  newFileName.value = ''
  newFileError.value = ''
}

function executeNewFile() {
  let name = newFileName.value.trim()
  if (name.toLowerCase().endsWith('.properties')) {
    name = name.slice(0, -11)
  }
  if (!name) {
    name = 'Untitled'
  }
  closeNewFileModal()
  emit('new', name)
}

function formatTime(ts) {
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

onMounted(() => {
  // 建立 FileBrowser 独立 WS 连接
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsPort = parseInt(location.port) + 1
  const wsUrl = `${protocol}//${location.hostname}:${wsPort}/ws`

  wsClient = new WsSyncClient({
    url: wsUrl,
    getSessionId: () => '',  // 服务端自动创建 session
    onMessage: (msg) => {
      // 收到锁状态变更广播时立即刷新文件列表
      if (msg.type === 'lock_stolen' || msg.type === 'file_locked') loadFiles()
    },
    onStatusChange: (status) => {
      if (status === 'connected') {
        loadFiles()  // 连接成功后加载文件列表
      } else if (status === 'session_invalid' || status === 'permanent_failure') {
        // WS 永久断开，停止刷新并通知用户
        if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
        useUiStore().showToast(t('toast.sessionLost') || 'Session lost', true)
      }
    }
  })
  wsClient.connect()

  // 周期性刷新文件列表（3秒，比旧的 500ms 更宽松）
  refreshTimer = setInterval(loadFiles, 3000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (wsClient) {
    wsClient.disconnect()
    wsClient = null
  }
})
</script>

<style scoped>
.file-browser {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
  color: var(--text);
  overflow: hidden;
}

.browser-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  position: relative;
  z-index: 10;
}

.browser-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
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

.delete-btn {
  background: var(--danger);
  color: #fff;
  border: none;
  padding: 8px 16px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
}
.delete-btn:hover:not(:disabled) {
  opacity: 0.9;
}
.delete-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 表格容器 */
.table-container {
  flex: 1;
  overflow: auto;
  padding: 0 24px 16px;
  position: relative;
}

.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.file-table thead {
  position: sticky;
  top: 0;
  background: var(--bg-panel);
  z-index: 1;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.file-table th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  color: var(--text-dim);
  border-bottom: 2px solid var(--border);
  white-space: nowrap;
}

.file-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.file-row {
  cursor: pointer;
  transition: background 150ms;
}
.file-row:hover {
  background: var(--bg-hover);
}
.file-row.selected {
  background: var(--bg-active);
}
.file-row.selected:hover {
  background: var(--bg-hover);
}
.file-row.locked {
  opacity: 0.6;
}

.empty-state { text-align: center; padding: 80px 24px !important; }
.empty-state-content { max-width: 360px; margin: 0 auto; }
.empty-icon { font-size: 48px; margin-bottom: 16px; }
.empty-title { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.empty-desc { color: var(--text-muted); font-size: 13px; line-height: 1.6; margin-bottom: 24px; }
.empty-btn {
  background: var(--accent); color: #fff; border: none;
  padding: 12px 32px; border-radius: var(--radius);
  font-size: 15px; font-weight: 600; cursor: pointer;
  margin-bottom: 32px;
}
.empty-btn:hover { opacity: 0.9; }
.empty-hints {
  list-style: none; padding: 0; text-align: left;
  font-size: 12px; color: var(--text-dim); line-height: 2;
}
.empty-hints li::before { content: '→ '; color: var(--accent); }

/* 列宽控制 */
.col-checkbox {
  width: 40px;
  text-align: center;
}
.col-name {
  min-width: 200px;
  font-weight: 500;
}
.col-messages,
.col-signals {
  width: 80px;
  text-align: center;
}
.col-time {
  width: 180px;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 12px;
}
.col-status {
  width: 180px;
}
.col-actions {
  width: 120px;
  text-align: center;
}

.file-name-link {
  color: var(--accent);
  cursor: pointer;
}
.file-name-link:hover {
  text-decoration: underline;
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

.unsaved-badge {
  display: inline-block;
  padding: 2px 8px;
  background: var(--danger);
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

.file-list-preview {
  margin: 12px 0 0 0;
  padding-left: 20px;
  font-size: 13px;
}

.file-list-preview li {
  margin: 4px 0;
  color: var(--text);
}

.more-files {
  color: var(--text-muted);
  font-style: italic;
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

.btn-danger {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
}
.btn-danger:hover:not(:disabled) {
  opacity: 0.9;
}
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 底部版本栏 */
.browser-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 24px;
  height: 26px;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.version-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.6;
}

.new-file-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  margin-bottom: 12px;
  outline: none;
}
.new-file-input:focus {
  border-color: var(--accent);
}
.new-file-error {
  color: var(--danger);
  font-size: 12px;
  margin: -8px 0 12px;
}
</style>
