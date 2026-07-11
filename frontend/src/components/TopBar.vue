<template>
  <div class="topbar">
    <button class="btn btn-icon btn-back" @click="$emit('back')" :title="t('topbar.back')">←</button>
    <div class="topbar-logo">Can<span>Matrix</span></div>
    <span class="topbar-filename">{{ store.currentFileName }}</span>
    <span class="topbar-spacer"></span>
    <button class="btn" @click="undoRedo.undo()" :disabled="!undoRedo.canUndo" title="撤销 (Ctrl+Z)">{{ t('topbar.undo') }}</button>
    <button class="btn" @click="undoRedo.redo()" :disabled="!undoRedo.canRedo" title="重做 (Ctrl+Y)">{{ t('topbar.redo') || '重做' }}</button>
    <button class="btn" @click="onNew">{{ t('topbar.new') }}</button>
    <button class="btn" @click="importFile">{{ t('topbar.import') }}</button>
    <div class="export-wrapper" ref="exportWrapper">
      <button class="btn btn-accent" @click="exportDropdownOpen = !exportDropdownOpen">{{ t('topbar.export') }} ▾</button>
      <div v-if="exportDropdownOpen" class="export-menu">
        <button @click="exportFile('dbc'); exportDropdownOpen = false">DBC</button>
        <button @click="exportFile('properties'); exportDropdownOpen = false">Properties</button>
        <button @click="exportFile('c_header'); exportDropdownOpen = false">C Header (.h)</button>
        <button @click="exportFile('c_source'); exportDropdownOpen = false">C Source (.c)</button>
      </div>
    </div>
    <button class="btn" @click="save" :disabled="!store.backendDirty" title="保存 (Ctrl+S)">{{ t('topbar.save') }}</button>
    <button class="btn" @click="onSaveAs">{{ t('topbar.saveAs') }}</button>
    <span class="topbar-spacer"></span>
    <button class="btn btn-icon" @click="ui.toggleTheme" title="切换主题">{{ ui.theme === 'dark' ? '☀' : '☾' }}</button>
    <button
      class="btn btn-icon"
      :class="{ active: ui.showLogPanel }"
      @click="ui.showLogPanel = !ui.showLogPanel"
      :title="t('topbar.log')"
    >
      {{ ui.showLogPanel ? '📋' : '📄' }}
    </button>
    <span class="api-status" :class="store.apiStatus">
      <span class="dot"></span>
      <template v-if="store.apiStatus === 'connected'">{{ t('topbar.connected') }}</template>
      <template v-else-if="store.apiStatus === 'dead'">{{ t('topbar.dead') }}</template>
      <template v-else>{{ t('topbar.offline') }}</template>
    </span>
  </div>

  <!-- New Confirm Dialog -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="ui.newConfirmOpen" class="confirm-overlay" @click="ui.newConfirmOpen = false">
        <div class="confirm-box" @click.stop>
          <h4>{{ t('topbar.newConfirmTitle') }}</h4>
          <p>{{ t('topbar.newConfirmDesc') }}</p>
          <input
            v-model="newSessionName"
            class="confirm-input"
            :placeholder="t('topbar.newNamePlaceholder')"
            spellcheck="false"
            @keyup.enter="confirmNew"
          />
          <div class="confirm-actions">
            <button class="btn" @click="ui.newConfirmOpen = false">{{ t('topbar.newConfirmCancel') }}</button>
            <button class="btn btn-accent" @click="confirmNew">{{ t('topbar.newConfirmCreate') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- Import Confirm Dialog -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="importConfirmOpen" class="confirm-overlay" @click="importConfirmOpen = false">
        <div class="confirm-box" @click.stop>
          <h4>{{ t('topbar.importConfirmTitle') || '确认导入' }}</h4>
          <p>{{ t('topbar.importConfirmDesc') || '导入将替换当前会话的所有数据，是否继续？' }}</p>
          <div class="confirm-actions">
            <button class="btn" @click="importConfirmOpen = false">{{ t('topbar.importConfirmCancel') || '取消' }}</button>
            <button class="btn btn-accent" @click="confirmImport">{{ t('topbar.importConfirmImport') || '导入' }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- Import Unsaved Changes Dialog -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="importDirtyOpen" class="confirm-overlay" @click="importDirtyOpen = false">
        <div class="confirm-box" @click.stop>
          <h4>{{ t('topbar.importUnsavedTitle') }}</h4>
          <p>{{ t('topbar.importUnsavedDesc') }}</p>
          <div class="confirm-actions">
            <button class="btn" @click="importDirtyOpen = false">{{ t('topbar.importUnsavedCancel') || '取消' }}</button>
            <button class="btn" @click="importAfterDiscard">{{ t('topbar.importUnsavedDiscard') || '放弃更改并导入' }}</button>
            <button class="btn btn-accent" @click="importAfterSave">{{ t('topbar.importUnsavedSave') || '保存后导入' }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- Hidden file input -->
  <input
    ref="fileInput"
    type="file"
    accept=".dbc,.properties,.json"
    style="display: none"
    @change="handleFileSelect"
  />

  <!-- SaveAs Confirm Dialog -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="saveAsConfirmOpen" class="confirm-overlay" @click="saveAsConfirmOpen = false">
        <div class="confirm-box" @click.stop>
          <h4>{{ t('topbar.saveAsConfirmTitle') }}</h4>
          <input
            v-model="saveAsName"
            class="confirm-input"
            :placeholder="t('topbar.saveAsPlaceholder')"
            spellcheck="false"
            @keyup.enter="confirmSaveAs"
          />
          <div class="confirm-actions">
            <button class="btn" @click="saveAsConfirmOpen = false">{{ t('topbar.newConfirmCancel') }}</button>
            <button class="btn btn-accent" @click="confirmSaveAs">{{ t('topbar.saveAsConfirm') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useUndoRedoStore } from '../stores/undoRedo.js'
import { useFileOperationsStore } from '../stores/fileOperations.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'
import { getSessionId } from '../api/client.js'

defineEmits(['back'])

const store = useEditorStore()
const undoRedo = useUndoRedoStore()
const fileOps = useFileOperationsStore()
const ui = useUiStore()
const newSessionName = ref('')
const fileInput = ref(null)
const importConfirmOpen = ref(false)
const pendingFile = ref(null)
const importDirtyOpen = ref(false)
const exportDropdownOpen = ref(false)
const exportWrapper = ref(null)

// 直接使用 store.currentFileName，避免本地 ref 与 store 状态不一致
function handleKeydown(event) {
  // ⚠️ 维护注意：跳过输入框内的快捷键，避免与浏览器原生撤销冲突
  const tag = event.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || event.target.isContentEditable) {
    return
  }

  if (event.ctrlKey || event.metaKey) {
    if (event.key === 'z' || event.key === 'Z') {
      event.preventDefault()
      undoRedo.undo()
    } else if (event.key === 'y' || event.key === 'Y') {
      event.preventDefault()
      undoRedo.redo()
    } else if (event.key === 's' || event.key === 'S') {
      event.preventDefault()
      save()
    }
  }
}

function handleExportClickOutside(e) {
  if (exportWrapper.value && !exportWrapper.value.contains(e.target)) {
    exportDropdownOpen.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  document.addEventListener('click', handleExportClickOutside)
  window.addEventListener('trigger-export', handleTriggerExport)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('click', handleExportClickOutside)
  window.removeEventListener('trigger-export', handleTriggerExport)
})

// App.vue 保存失败时通过此事件触发导出备份（跳过冗余的 saveSession）
function handleTriggerExport() {
  exportFile('properties', { skipSave: true })
}

watch(() => ui.newConfirmOpen, (open) => { if (open) newSessionName.value = '' })

function onNew() {
  ui.newConfirmOpen = true
}

function confirmNew() {
  ui.newConfirmOpen = false
  const name = newSessionName.value.trim() || 'Untitled'
  fileOps.createNewSession(name)
}

const saveAsConfirmOpen = ref(false)
const saveAsName = ref('')

function onSaveAs() {
  saveAsName.value = store.currentFileName.replace(/\.properties$/i, '').trim() || ''
  saveAsConfirmOpen.value = true
}

function confirmSaveAs() {
  saveAsConfirmOpen.value = false
  const name = saveAsName.value.trim() || 'Untitled'
  fileOps.saveAs(name)
}

async function importFile() {
  // 检查是否有未保存的更改
  if (store.backendDirty) {
    importDirtyOpen.value = true
    return
  }
  // 无未保存更改 → 直接打开文件选择
  if (fileInput.value) {
    fileInput.value.click()
  }
}

async function handleFileSelect(event) {
  const file = event.target.files[0]
  if (!file) return

  // 重置 file input，允许重复选择同一文件
  event.target.value = ''

  // 检测文件格式
  const ext = file.name.split('.').pop().toLowerCase()
  const supportedFormats = ['dbc', 'properties', 'json']
  
  if (!supportedFormats.includes(ext)) {
    ui.showToast(`不支持的文件格式: .${ext}，支持 .dbc, .properties, .json`, true)
    return
  }

  // 保存待导入文件信息
  pendingFile.value = { file, format: ext }
  
  // 显示确认对话框
  importConfirmOpen.value = true
}

async function confirmImport() {
  if (!pendingFile.value) return
  
  const { file, format } = pendingFile.value
  importConfirmOpen.value = false
  
  try {
    ui.setLoading(true)
    
    // 读取文件内容
    const content = await file.text()
    
    // 通过 store action 导入文件（内部处理 session 切换）
    const data = await fileOps.importFile({
      format: format,
      content: content,
      filename: file.name
    })
    
    ui.showToast(`成功导入 ${file.name}（${data.message_count || 0} 个报文）`, false)
  } catch (e) {
    ui.showToast(`导入失败: ${e.message}`, true)
  } finally {
    ui.setLoading(false)
    pendingFile.value = null
  }
}

// “保存后导入”按钮
async function importAfterSave() {
  importDirtyOpen.value = false
  const success = await fileOps.saveSession()
  if (!success) {
    ui.showToast('保存失败，导入已取消', true)
    return
  }
  // 保存成功 → 打开文件选择
  if (fileInput.value) fileInput.value.click()
}

// “放弃更改并导入”按钮
function importAfterDiscard() {
  importDirtyOpen.value = false
  if (fileInput.value) fileInput.value.click()
}

async function exportFile(fmt, options = {}) {
  const ui = useUiStore()
  try {
    ui.setLoading(true)
    const sid = getSessionId() || ''

    // ── pywebview 桌面模式：调用原生保存对话框（不受 WS 状态影响） ──
    if (window.pywebview?.api?.save_file) {
      ui.showToast('正在打开保存对话框...', false)
      const raw = await window.pywebview.api.save_file(fmt, sid)
      const result = typeof raw === 'string' ? JSON.parse(raw) : raw
      if (result.success) {
        ui.showToast(`已保存到: ${result.path}`, false)
      } else if (result.error !== '用户取消') {
        ui.showToast(`导出失败: ${result.error}`, true)
      }
      return
    }

    // ── WS 断开降级：走 HTTP 导出端点 ──
    if (!store._wsClient?.connected) {
      const url = `/api/export?sid=${encodeURIComponent(sid)}&fmt=${encodeURIComponent(fmt)}`
      const resp = await fetch(url)
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }))
        throw new Error(err.error || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const disposition = resp.headers.get('Content-Disposition') || ''
      const filenameMatch = disposition.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : `export.${fmt}`
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      setTimeout(() => { URL.revokeObjectURL(blobUrl); a.remove() }, 100)
      ui.showToast(`已通过 HTTP 导出备份: ${filename}`, false)
      return
    }

    // ── 正常路径（WS 在线）──
    // 先保存当前会话确保数据最新（skipSave: 保存失败后导出备份时跳过冗余保存）
    if (!options.skipSave) {
      const saved = await fileOps.saveSession()
      if (!saved) {
        ui.showToast('保存失败，将导出内存中的最新数据', true)
      }
    }

    // ── 浏览器模式：WS 获取内容 + Blob 下载 ──
    const data = await store._wsRequest('download_file', { format: fmt }, 60000)
    const mimeMap = { dbc: 'application/octet-stream', properties: 'text/plain', c_header: 'text/plain', c_source: 'text/plain' }
    const blob = new Blob([data.content], { type: `${mimeMap[fmt] || 'text/plain'};charset=utf-8` })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = data.filename || `export.${fmt}`
    document.body.appendChild(a)
    a.click()
    setTimeout(() => { URL.revokeObjectURL(url); a.remove() }, 100)
    ui.showToast(`已导出: ${data.filename}`, false)
  } catch (e) {
    ui.showToast(`导出失败: ${e.message}`, true)
  } finally {
    ui.setLoading(false)
  }
}

async function save() {
  try {
    ui.setLoading(true)
    const success = await fileOps.saveSession()
    if (success) {
      ui.showToast('保存成功', false)
    } else {
      ui.showToast(`保存失败: ${store.lastSaveError || '未知错误'}`, true)
    }
  } finally {
    ui.setLoading(false)
  }
}
</script>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  height: 48px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.topbar-logo {
  font-size: 15px;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: -0.3px;
  margin-right: 8px;
}
.topbar-logo span { color: var(--text); }

.topbar-filename {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px 10px;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 12px;
  width: 220px;
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-spacer { flex: 1; }

.api-status {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.api-status.connected { color: var(--accent); }
.api-status.offline,
.api-status.dead { color: var(--danger); }

.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: currentColor;
  display: inline-block;
}

.btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
}
.btn:hover { background: var(--bg-hover); }
.btn-back {
  font-size: 18px;
  padding: 5px 10px;
  margin-right: 4px;
}
.btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}
.btn-accent:hover { filter: brightness(1.1); }

.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1600;
}

.confirm-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 360px;
  max-width: 90vw;
  box-shadow: var(--shadow);
}

.confirm-box h4 {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
}

.confirm-box p {
  margin: 0 0 18px;
  font-size: 13px;
  color: var(--text-dim);
  line-height: 1.5;
}

.confirm-input {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 13px;
  margin-bottom: 16px;
  outline: none;
  box-sizing: border-box;
}
.confirm-input:focus { border-color: var(--accent-dim); }

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.export-wrapper {
  position: relative;
}

.export-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
  z-index: 100;
  min-width: 120px;
  overflow: hidden;
}

.export-menu button {
  display: block;
  width: 100%;
  padding: 6px 14px;
  background: none;
  border: none;
  color: var(--text);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition: var(--transition);
}

.export-menu button:hover {
  background: var(--bg-hover);
}
</style>
