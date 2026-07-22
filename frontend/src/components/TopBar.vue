<template>
  <div class="topbar">
    <button class="btn btn-icon btn-back" @click="$emit('back')" :title="t('topbar.back')">←</button>
    <div class="topbar-logo">Can<span>Matrix</span></div>
    <span class="topbar-filename">{{ store.currentFileName }}</span>
    <select class="topbar-bus-type" v-model="store.busType" @change="setBusType($event.target.value)">
      <option value="CAN">CAN</option>
      <option value="CAN FD">CAN FD</option>
    </select>
    <span v-if="store.backendDirty" class="topbar-dirty-badge" :title="t('status.unsaved')">● {{ t('status.unsaved') }}</span>
    <span class="topbar-spacer"></span>
    <span class="topbar-divider"></span>
    <button class="btn" @click="undoRedo.undo()" :disabled="!undoRedo.canUndo" title="撤销 (Ctrl+Z)">{{ t('topbar.undo') }}</button>
    <button class="btn" @click="undoRedo.redo()" :disabled="!undoRedo.canRedo" title="重做 (Ctrl+Y)">{{ t('topbar.redo') || '重做' }}</button>
    <span class="topbar-divider"></span>
    <div class="export-wrapper" ref="exportWrapper">
      <button class="btn btn-accent" @click="exportDropdownOpen = !exportDropdownOpen">{{ t('topbar.export') }} ▾</button>
      <div v-if="exportDropdownOpen" class="export-menu">
        <button @click="exportFile('dbc'); exportDropdownOpen = false">DBC</button>
        <button @click="exportFile('properties'); exportDropdownOpen = false">Properties</button>
        <button @click="exportCcode(); exportDropdownOpen = false">C Code (.h + .c)</button>
      </div>
    </div>
    <button class="btn" :class="{ 'btn-dirty': store.backendDirty }" @click="save" :disabled="!store.backendDirty" title="保存 (Ctrl+S)">{{ t('topbar.save') }}</button>
    <button class="btn" @click="onSaveAs">{{ t('topbar.saveAs') }}</button>
    <span class="topbar-divider"></span>
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
            <button class="btn" @click="saveAsConfirmOpen = false">{{ t('topbar.saveAsCancel') }}</button>
            <button class="btn btn-accent" :disabled="saveAsLoading" @click="confirmSaveAs">{{ t('topbar.saveAsConfirm') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- C Code Preview Modal -->
  <CcodePreviewModal
    v-model:visible="ui.ccodePreview.open"
    :header-code="ui.ccodePreview.headerCode"
    :header-filename="ui.ccodePreview.headerFilename"
    :source-code="ui.ccodePreview.sourceCode"
    :source-filename="ui.ccodePreview.sourceFilename"
  />
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useUndoRedoStore } from '../stores/undoRedo.js'
import { useFileOperationsStore } from '../stores/fileOperations.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'
import { getSessionId } from '../api/client.js'
import CcodePreviewModal from './CcodePreviewModal.vue'

defineEmits(['back'])

const store = useEditorStore()
const undoRedo = useUndoRedoStore()
const fileOps = useFileOperationsStore()
const ui = useUiStore()
const exportDropdownOpen = ref(false)
const exportWrapper = ref(null)

function setBusType(value) {
  store._wsRequest('edit_database', { fields: { bus_type: value } })
    .catch(e => {
      // 后端拒绝时，用后端返回的权威值覆盖 store
      if (e.details?.bus_type) {
        store.busType = e.details.bus_type
      }
      ui.showToast(e.message, true)
    })
}

// 直接使用 store.currentFileName，避免本地 ref 与 store 状态不一致
function handleKeydown(event) {
  const tag = event.target.tagName
  const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || event.target.isContentEditable

  if (event.ctrlKey || event.metaKey) {
    // Ctrl+S 无论焦点在哪都应触发保存（阻止浏览器"保存网页"对话框）
    if (event.key === 's' || event.key === 'S') {
      event.preventDefault()
      save()
      return
    }
    // Ctrl+Z / Ctrl+Y 在输入框内跳过（避免与浏览器原生撤销/重做冲突）
    if (isInput) return
    if (event.key === 'z' || event.key === 'Z') {
      event.preventDefault()
      undoRedo.undo()
    } else if (event.key === 'y' || event.key === 'Y') {
      event.preventDefault()
      undoRedo.redo()
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

const saveAsConfirmOpen = ref(false)
const saveAsName = ref('')
const saveAsLoading = ref(false)

function onSaveAs() {
  saveAsName.value = store.currentFileName.replace(/\.properties$/i, '').trim() || ''
  saveAsConfirmOpen.value = true
}

async function confirmSaveAs() {
  if (saveAsLoading.value) return
  const name = saveAsName.value.trim() || 'Untitled'
  saveAsLoading.value = true
  try {
    await fileOps.saveAs(name)
    saveAsConfirmOpen.value = false
  } catch {
    // saveAs 已显示错误 toast，弹窗保持打开让用户修改文件名
  } finally {
    saveAsLoading.value = false
  }
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
    const mimeMap = { dbc: 'application/octet-stream', properties: 'text/plain' }
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

async function exportCcode() {
  try {
    ui.setLoading(true)
    const sid = getSessionId() || ''

    // ── pywebview 桌面模式：分别调用原生保存（不支持预览） ──
    if (window.pywebview?.api?.save_file) {
      ui.showToast('正在打开保存对话框...', false)
      const rawH = await window.pywebview.api.save_file('c_header', sid)
      const resultH = typeof rawH === 'string' ? JSON.parse(rawH) : rawH
      if (!resultH.success && resultH.error !== '用户取消') {
        ui.showToast(`导出失败: ${resultH.error}`, true)
      }
      const rawC = await window.pywebview.api.save_file('c_source', sid)
      const resultC = typeof rawC === 'string' ? JSON.parse(rawC) : rawC
      if (!resultC.success && resultC.error !== '用户取消') {
        ui.showToast(`导出失败: ${resultC.error}`, true)
      }
      return
    }

    // ── WS 断开降级：两次 HTTP 请求 ──
    if (!store._wsClient?.connected) {
      const [headerResp, sourceResp] = await Promise.all([
        fetch(`/api/export?sid=${encodeURIComponent(sid)}&fmt=c_header`),
        fetch(`/api/export?sid=${encodeURIComponent(sid)}&fmt=c_source`),
      ])
      if (!headerResp.ok || !sourceResp.ok) {
        const status = !headerResp.ok ? headerResp.status : sourceResp.status
        throw new Error(`HTTP ${status}`)
      }
      const parseFilename = (resp, fallback) => {
        const disposition = resp.headers.get('Content-Disposition') || ''
        const m = disposition.match(/filename="(.+)"/)
        return m ? m[1] : fallback
      }
      const headerCode = await headerResp.text()
      const sourceCode = await sourceResp.text()
      ui.openCcodePreview({
        headerCode, headerFilename: parseFilename(headerResp, 'export.h'),
        sourceCode, sourceFilename: parseFilename(sourceResp, 'export.c'),
      })
      return
    }

    // ── WS 在线：先保存一次，再并发请求两种格式 ──
    const saved = await fileOps.saveSession()
    if (!saved) {
      ui.showToast('保存失败，将导出内存中的最新数据', true)
    }

    const [headerData, sourceData] = await Promise.all([
      store._wsRequest('download_file', { format: 'c_header' }, 60000),
      store._wsRequest('download_file', { format: 'c_source' }, 60000),
    ])

    ui.openCcodePreview({
      headerCode: headerData.content, headerFilename: headerData.filename,
      sourceCode: sourceData.content, sourceFilename: sourceData.filename,
    })
  } catch (e) {
    ui.showToast(`导出失败: ${e.message}`, true)
  } finally {
    ui.setLoading(false)
  }
}

async function save() {
  const success = await fileOps.saveSession()
  if (success) {
    ui.showToast('保存成功', false)
  } else {
    ui.showToast(`保存失败: ${store.lastSaveError || '未知错误'}`, true)
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
  background: color-mix(in oklch, var(--accent) 8%, transparent);
  border: none;
  border-radius: var(--radius-sm);
  padding: 4px 12px;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 500;
  max-width: 280px;
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: 0.2px;
}

.topbar-spacer { flex: 1; }

.topbar-divider {
  width: 1px;
  height: 20px;
  background: var(--border);
  flex-shrink: 0;
}

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

.topbar-dirty-badge {
  color: var(--warn);
  font-size: 12px;
  font-weight: 600;
  animation: dirty-pulse 2s ease-in-out infinite;
  white-space: nowrap;
}
.btn-dirty {
  background: var(--warn);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}
.btn-dirty:hover {
  background: color-mix(in oklch, var(--warn) 85%, black);
}
@keyframes dirty-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.topbar-bus-type {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 600;
  border-radius: var(--radius-sm);
  cursor: pointer;
  outline: none;
}
.topbar-bus-type:focus { border-color: var(--accent-dim); }
</style>
