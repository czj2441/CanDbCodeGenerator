<template>
  <div class="app" @contextmenu="onContextMenu">
    <!-- 文件浏览器模式 -->
    <FileBrowser v-if="mode === 'browser'" @open="openFile" @new="createNewFile" @import="importFileFromBrowser" />
    <!-- 编辑器模式 -->
    <template v-else>
      <TopBar @back="goBack" />
      <!-- Tab 导航栏：全宽，优先级高于报文列表和属性面板 -->
      <div class="nav-tabs">
        <button class="nav-tab" :class="{ active: ui.centerTab === 'messages' }"
                @click="ui.switchCenterTab('messages')">
          {{ t('tab.messages') }}
        </button>
        <button class="nav-tab" :class="{ active: ui.centerTab === 'signals' }"
                @click="ui.switchCenterTab('signals')">{{ t('tab.signals') }}</button>
        <button class="nav-tab" :class="{ active: ui.centerTab === 'valtables' }"
                @click="ui.switchCenterTab('valtables')">{{ t('tab.valtables') }}</button>
      </div>
      <div class="main">
        <MessageList v-if="ui.centerTab === 'signals'" />
        <div class="center">
          <template v-if="ui.centerTab === 'signals'">
            <SignalLayoutVisualizer v-if="ui.layoutViewMode" />
            <SignalTable v-else />
          </template>
          <MessageTable v-else-if="ui.centerTab === 'messages'" />
          <ValueTableList v-else-if="ui.centerTab === 'valtables'" />
          <DataErrorList />
          <LogPanel />
        </div>
        <ValueTablePanel v-if="ui.centerTab === 'valtables'" />
        <MessagePanel v-else />
      </div>
      <StatusBar /> 
      <!-- 离线编辑遮罩：覆盖编辑区域，不遮挡 TopBar -->
      <div v-if="hasBeenConnected && connectionStatus !== 'connected' && connectionStatus !== 'dead'" class="offline-overlay">
        <div class="dead-overlay-box" style="border-color: var(--warn);">
          <div class="offline-spinner"></div>
          <p>{{ t('overlay.reconnectTitle') }}</p>
          <p class="dead-overlay-sub">{{ t('overlay.reconnectSub') }}</p>
        </div>
      </div>
      <BatchModal v-model:visible="ui.batchModalOpen" />

      <LoadingOverlay /> 
      <ContextMenu :items="contextMenuItems" />
    </template>
    <!-- 版本不匹配浮动提示：非阻断，可拖动，用户可继续编辑 -->
    <div v-if="versionMismatch" ref="versionCardRef" class="version-mismatch-card"
         :style="{ top: vmPos.top + 'px', left: vmPos.left + 'px' }">
      <div class="vm-drag-handle" @mousedown="onVmDragStart">
        <span class="version-mismatch-icon">🔄</span>
        <div class="version-mismatch-text">
          <p class="version-mismatch-title">{{ t('overlay.versionMismatchTitle') }}</p>
          <p class="version-mismatch-sub">{{ t('overlay.versionMismatchSub') }}</p>
        </div>
      </div>
      <button class="btn btn-accent" @click="reloadPage">
        {{ t('overlay.versionReload') }}
      </button>
    </div>
    <!-- 死遮罩：全局覆盖所有模式 -->
    <div v-if="connectionStatus === 'dead'" class="dead-overlay">
      <div class="dead-overlay-box">
        <span class="dead-overlay-icon">⚠️</span>
        <p>{{ t('overlay.deadTitle') }}</p>
        <p class="dead-overlay-sub">{{ t('overlay.deadSub') }}</p>
      </div>
    </div>
    <!-- Toast 在所有模式下都渲染 -->
    <Toast />
    <!-- 返回确认对话框（未保存更改） -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="backDirtyOpen" class="confirm-overlay" @click="backDirtyOpen = false">
          <div class="confirm-box" @click.stop>
            <h4>{{ t('backConfirm.title') }}</h4>
            <p>{{ t('backConfirm.desc') }}</p>
            <div class="confirm-actions">
              <button class="btn" @click="backDirtyOpen = false">{{ t('backConfirm.cancel') }}</button>
              <button class="btn" @click="backAfterDiscard">{{ t('backConfirm.discard') }}</button>
              <button class="btn btn-accent" @click="backAfterSave">{{ t('backConfirm.save') }}</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
    <!-- 保存失败警告对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="saveFailedOpen" class="confirm-overlay" @click="dismissSaveFailed">
          <div class="confirm-box" @click.stop>
            <h4>{{ t('backConfirm.saveFailedTitle') }}</h4>
            <p>{{ t('backConfirm.saveFailedDesc') }}</p>
            <p v-if="store.lastSaveError" class="error-detail">{{ store.lastSaveError }}</p>
            <div class="confirm-actions">
              <button class="btn" @click="dismissSaveFailed">{{ t('backConfirm.stayEditing') }}</button>
              <button class="btn btn-accent" @click="exportAndStay">{{ t('backConfirm.exportBackup') }}</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed, watchEffect, nextTick } from 'vue'
import { useEditorStore } from './stores/editor.js'
import { useFileOperationsStore } from './stores/fileOperations.js'
import { useClipboardStore } from './stores/clipboard.js'
import { useSignalsStore } from './stores/signals.js'
import { useMessagesStore } from './stores/messages.js'
import { useUiStore } from './stores/uiStore.js'
import { connectionStatus, hasBeenConnected, resetConnection } from './stores/connectionHealth.js'
import { t } from './i18n.js'
import { getSessionId, setSessionId } from './api/client.js'
import FileBrowser from './components/FileBrowser.vue'
import TopBar from './components/TopBar.vue'
import MessageList from './components/MessageList.vue'
import SignalTable from './components/SignalTable.vue'
import MessageTable from './components/MessageTable.vue'
import SignalLayoutVisualizer from './components/SignalLayoutVisualizer.vue'
import MessagePanel from './components/MessagePanel.vue'
import StatusBar from './components/StatusBar.vue'
import BatchModal from './components/BatchModal.vue'
import LoadingOverlay from './components/LoadingOverlay.vue'
import Toast from './components/Toast.vue'
import ContextMenu from './components/ContextMenu.vue'
import LogPanel from './components/LogPanel.vue'
import DataErrorList from './components/DataErrorList.vue'
import ValueTableList from './components/ValueTableList.vue'
import ValueTablePanel from './components/ValueTablePanel.vue'
import { versionMismatch } from './utils/version-check.js'

const store = useEditorStore()
const fileOps = useFileOperationsStore()
const clipboard = useClipboardStore()
const signals = useSignalsStore()
const messages = useMessagesStore()
const ui = useUiStore()

// 浏览器标题栏动态脏标记
watchEffect(() => {
  const base = 'CAN Matrix Editor'
  document.title = store.backendDirty ? `● ${base}` : base
})

let beforeUnloadHandler = null  // beforeunload 事件处理器
let navigateHandler = null     // navigate-browser 事件处理器
let pageshowHandler = null     // bfcache 恢复检测处理器

// 模块级标志：版本刷新时跳过 abort，保留快照保护未保存变更
let _isVersionReload = false

function reloadPage() {
  _isVersionReload = true
  window.location.reload()
}

// ── 版本不匹配卡片：可拖动定位 ──
const versionCardRef = ref(null)
const vmPos = reactive({ top: 40, left: -1 })  // left=-1 表示待初始化（居中）

function _initVmPos() {
  // 首次出现时水平居中（需等 DOM 渲染）
  nextTick(() => {
    const el = versionCardRef.value
    if (el && vmPos.left < 0) {
      vmPos.left = Math.max(0, (window.innerWidth - el.offsetWidth) / 2)
    }
  })
}

let _vmDragState = null
function onVmDragStart(e) {
  // 仅主键拖动，阻止冒泡避免触发外层 contextmenu
  if (e.button !== 0) return
  e.preventDefault()
  _vmDragState = {
    startX: e.clientX,
    startY: e.clientY,
    origTop: vmPos.top,
    origLeft: vmPos.left,
  }
  window.addEventListener('mousemove', _onVmDragMove)
  window.addEventListener('mouseup', _onVmDragEnd)
}
function _onVmDragMove(e) {
  if (!_vmDragState) return
  const dx = e.clientX - _vmDragState.startX
  const dy = e.clientY - _vmDragState.startY
  vmPos.left = Math.max(0, _vmDragState.origLeft + dx)
  vmPos.top = Math.max(0, _vmDragState.origTop + dy)
}
function _onVmDragEnd() {
  _vmDragState = null
  window.removeEventListener('mousemove', _onVmDragMove)
  window.removeEventListener('mouseup', _onVmDragEnd)
}
// versionMismatch 变化时初始化位置
watchEffect(() => { if (versionMismatch.value) _initVmPos() })

// 应用模式：'browser' | 'editor'
const mode = ref('browser')

function handleSessionStolen(stolenSessionId) {
  // WS lock_stolen 事件触发时调用
  // 锁已被抢，保存无意义，跳过脏检查直接返回
  console.warn(`[LockStolen] session ${stolenSessionId} was stolen`)
  ui.showToast(t('toast.sessionStolen'), true)
  doGoBack()
}

onMounted(() => {
  mode.value = 'browser'
  document.addEventListener('click', hideMenu)
  document.documentElement.setAttribute('data-theme', ui.theme)

  // 监听 WS lock_stolen 导航事件
  navigateHandler = () => {
    if (mode.value === 'editor') {
      doGoBack()  // 锁已被抢/会话失效，跳过脏检查直接返回
    }
  }
  window.addEventListener('navigate-browser', navigateHandler)

  // bfcache 恢复检测：浏览器前进/后退缓存恢复页面时，
  // Vue 状态被冻结保留（mode='editor'），但服务端 session 已被 beforeunload 释放。
  // 必须立即切回文件浏览器，避免断连遮罩闪烁和"会话不存在"错误。
  pageshowHandler = (e) => {
    if (e.persisted && mode.value === 'editor') {
      console.warn('[bfcache] page restored from cache, switching to browser')
      store.stopEditorSync()   // 停止 WS + 健康检查（防止离线遮罩闪烁）
      setSessionId('')         // 清除残留 session_id
      resetConnection()        // 重置连接状态
      store.resetEditorState() // 清理编辑器数据
      mode.value = 'browser'   // 切回文件浏览器
      // 等 FileBrowser 挂载后再提示，复用已有的 sessionLost 文案
      nextTick(() => ui.showToast(t('toast.sessionLost'), false))
    }
  }
  window.addEventListener('pageshow', pageshowHandler)

  // 页面关闭/刷新时：释放文件锁 + 确认对话框
  beforeUnloadHandler = (e) => {
    const sid = getSessionId()
    if (sid) {
      if (_isVersionReload) {
        // 版本刷新：不带 abort=1，后端写快照保护未保存变更
        navigator.sendBeacon('/api/release?sid=' + encodeURIComponent(sid))
        setSessionId('')  // 清除旧 ID，防止新页面 WS hello 携带已销毁的 session_id
      } else {
        // 正常关闭/刷新：放弃变更
        navigator.sendBeacon('/api/release?sid=' + encodeURIComponent(sid) + '&abort=1')
        setSessionId('')  // 清除 sessionStorage，防止 Ctrl+F5 后旧 ID 残留
      }
    }
    if (sid && store.backendDirty && !_isVersionReload) {
      e.preventDefault()
      e.returnValue = '您有未保存的更改，确定要离开吗？'
      return e.returnValue
    }
  }
  window.addEventListener('beforeunload', beforeUnloadHandler)

  // 初始版本检查（REST），后续通过 WS ping/pong 被动接收服务端版本
  store.checkVersion()
})

onUnmounted(() => {
  document.removeEventListener('click', hideMenu)
  if (navigateHandler) {
    window.removeEventListener('navigate-browser', navigateHandler)
    navigateHandler = null
  }
  if (pageshowHandler) {
    window.removeEventListener('pageshow', pageshowHandler)
    pageshowHandler = null
  }
  if (beforeUnloadHandler) {
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    beforeUnloadHandler = null
  }
  // 清理拖拽监听（若组件卸载时正在拖拽）
  window.removeEventListener('mousemove', _onVmDragMove)
  window.removeEventListener('mouseup', _onVmDragEnd)
})

// 打开文件
async function openFile(fileName) {
  try {
    await fileOps.loadHistoryFile(fileName)
    mode.value = 'editor'
    // WS 连接已在 loadHistoryFile 中启动
  } catch (e) {
    console.error('Failed to open file:', e)
    if (e.code === 'FILE_LOCKED') {
      ui.showToast(e.message, true)
    }
  }
}

// 新建文件
async function createNewFile(name) {
  try {
    await fileOps.newFile(name)
    mode.value = 'editor'
    // WS 连接已在 newFile 中启动
  } catch (e) {
    console.error('Failed to create new file:', e)
    if (e.code === 'FILE_NAME_EXISTS') {
      ui.showToast(t('browser.newFileExistsError'), true)
    } else {
      ui.showToast(e.message, true)
    }
  }
}

// 从 FileBrowser 导入文件
async function importFileFromBrowser({ format, content, filename }) {
  try {
    await fileOps.importFile({ format, content, filename })
    mode.value = 'editor'
  } catch (e) {
    console.error('Failed to import file:', e)
  }
}

// 返回文件浏览器
const backDirtyOpen = ref(false)
const saveFailedOpen = ref(false)

async function goBack() {
  // 有未保存更改时弹出确认对话框
  if (store.backendDirty) {
    backDirtyOpen.value = true
    return
  }
  await doGoBack()
}

async function backAfterSave() {
  backDirtyOpen.value = false
  const ok = await fileOps.saveSession()
  if (!ok) {
    saveFailedOpen.value = true
    return
  }
  await doGoBack()
}

function dismissSaveFailed() {
  saveFailedOpen.value = false
  // 留在编辑器，用户可重试保存或继续编辑
}

function exportAndStay() {
  saveFailedOpen.value = false
  // 复用 TopBar 已有的导出逻辑：触发 TopBar 的 saveAndExport
  window.dispatchEvent(new CustomEvent('trigger-export'))
}

function backAfterDiscard() {
  backDirtyOpen.value = false
  doGoBack()
}

async function doGoBack() {
  // 先释放文件锁（需要 WS 连接），再断开 WS
  await fileOps.releaseSession()
  // sendBeacon 兆底（WS 可能已断开）
  const sid = getSessionId()
  if (sid) {
    navigator.sendBeacon('/api/release?sid=' + encodeURIComponent(sid) + '&abort=1')
  }
  // 统一拆卸：停止 WS + 清除 sessionStorage + 重置状态 + 导航回文件列表
  store._teardownSession('go_back')
  mode.value = 'browser'
}


function hideMenu() {
  ui.hideContextMenu()
}

const contextMenuItems = computed(() => {
  const target = ui.contextMenu.target
  const idx = ui.contextMenu.idx
  if (target === 'signal' && idx !== null) {
    return [
      { label: t('ctx.copySignal'), action: () => clipboard.copySignal(idx) },
      { label: t('ctx.cutSignal'), action: () => clipboard.cutSignal(idx) },
      { label: t('ctx.pasteSignal'), action: () => clipboard.pasteSignal(), disabled: !clipboard.clipboard || clipboard.clipboard.type !== 'signal' },
      { label: t('ctx.deleteSignal'), action: () => signals.deleteSignal(idx), danger: true },
    ]
  }
  if (target === 'message') {
    return [
      { label: t('ctx.copyMessage'), action: () => clipboard.copyMessage() },
      { label: t('ctx.pasteMessage'), action: () => clipboard.pasteMessage(), disabled: !clipboard.clipboard || clipboard.clipboard.type !== 'message' },
      { label: t('ctx.duplicateMessage'), action: () => clipboard.duplicateMessage() },
      { label: t('ctx.deleteMessage'), action: () => messages.deleteMessage(store.selectedMsgId), danger: true },
    ]
  }
  return []
})

function onContextMenu(e) {
  const row = e.target.closest('tr[data-sig-id]')
  const msgItem = e.target.closest('.message-item')
  if (row) {
    e.preventDefault()
    ui.showContextMenu(
      Math.min(e.clientX, window.innerWidth - 180),
      Math.min(e.clientY, window.innerHeight - 200),
      'signal',
      row.dataset.sigId
    )
  } else if (msgItem) {
    e.preventDefault()
    ui.showContextMenu(
      Math.min(e.clientX, window.innerWidth - 180),
      Math.min(e.clientY, window.innerHeight - 200),
      'message',
      null
    )
  }
}
</script>

<style>
:root {
  --radius-sm: 3px;
  --radius: 6px;
  --radius-lg: 10px;
  --font-sans: 'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'DM Mono', 'Cascadia Code', 'Fira Code', monospace;
  --transition: 150ms cubic-bezier(0.4, 0, 0.2, 1);
}

[data-theme="dark"] {
  --bg: oklch(0.15 0.005 260);
  --bg-panel: oklch(0.18 0.005 260);
  --bg-raised: oklch(0.22 0.005 260);
  --bg-hover: oklch(0.26 0.005 260);
  --bg-active: oklch(0.30 0.01 260);
  --border: oklch(0.30 0.005 260);
  --border-light: oklch(0.33 0.005 260);
  --text: oklch(0.92 0.005 260);
  --text-dim: oklch(0.60 0.005 260);
  --text-muted: oklch(0.45 0.005 260);
  --accent: oklch(0.68 0.18 155);
  --accent-dim: oklch(0.45 0.12 155);
  --warn: oklch(0.72 0.17 80);
  --danger: oklch(0.60 0.20 25);
  --info: oklch(0.72 0.14 240);
  --signal-bg: oklch(0.20 0.02 155 / 0.15);
  --signal-bg-alt: oklch(0.20 0.02 155 / 0.08);
  --shadow-sm: 0 1px 2px oklch(0 0 0 / 0.3);
  --shadow: 0 4px 12px oklch(0 0 0 / 0.4);
  --layout-grid: oklch(0.28 0.005 260);
  --layout-oob: oklch(0.25 0.08 25 / 0.3);
}

[data-theme="light"] {
  --bg: oklch(0.97 0.005 260);
  --bg-panel: oklch(0.95 0.005 260);
  --bg-raised: oklch(0.92 0.005 260);
  --bg-hover: oklch(0.88 0.005 260);
  --bg-active: oklch(0.85 0.01 260);
  --border: oklch(0.80 0.005 260);
  --border-light: oklch(0.75 0.005 260);
  --text: oklch(0.20 0.005 260);
  --text-dim: oklch(0.45 0.005 260);
  --text-muted: oklch(0.55 0.005 260);
  --accent: oklch(0.55 0.18 155);
  --accent-dim: oklch(0.40 0.12 155);
  --warn: oklch(0.60 0.17 80);
  --danger: oklch(0.55 0.20 25);
  --info: oklch(0.55 0.14 240);
  --signal-bg: oklch(0.55 0.02 155 / 0.08);
  --signal-bg-alt: oklch(0.55 0.02 155 / 0.04);
  --shadow-sm: 0 1px 2px oklch(0 0 0 / 0.08);
  --shadow: 0 4px 12px oklch(0 0 0 / 0.12);
  --layout-grid: oklch(0.78 0.005 260);
  --layout-oob: oklch(0.88 0.08 25 / 0.25);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font-sans);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  line-height: 1.5;
  overflow: hidden;
}

.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.main {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.center {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
}

/* ── Tab 导航栏（全宽，高于报文列表和属性面板） ── */
.nav-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  flex-shrink: 0;
}
.nav-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 16px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  transition: color 150ms, border-color 150ms;
}
.nav-tab:hover { color: var(--text); background: var(--bg-hover); }
.nav-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}

/* ── 连接中断遮罩 ── */
.dead-overlay {
  position: fixed;
  inset: 0;
  z-index: 500;
  background: oklch(0 0 0 / 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: not-allowed;
}
.dead-overlay-box {
  background: var(--bg-raised);
  border: 1px solid var(--danger);
  border-radius: var(--radius-lg);
  padding: 32px 48px;
  text-align: center;
  max-width: 400px;
}
.dead-overlay-icon {
  font-size: 36px;
  display: block;
  margin-bottom: 12px;
}
.dead-overlay-box p {
  margin: 4px 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.dead-overlay-sub {
  font-size: 12px !important;
  font-weight: 400 !important;
  color: var(--text-dim) !important;
}
.dead-overlay-box .btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 16px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
}
.dead-overlay-box .btn:hover { background: var(--bg-hover); }
.dead-overlay-box .btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}
.dead-overlay-box .btn-accent:hover { filter: brightness(1.1); }

/* ── 版本不匹配浮动提示（非阻断，可拖动） ── */
.version-mismatch-card {
  position: fixed;
  z-index: 498;
  background: var(--bg-raised);
  border: 1px solid var(--info);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  max-width: 480px;
}

.vm-drag-handle {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: grab;
  user-select: none;
  flex: 1;
}
.vm-drag-handle:active { cursor: grabbing; }

.version-mismatch-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.version-mismatch-text {
  flex: 1;
}

.version-mismatch-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.version-mismatch-sub {
  margin: 3px 0 0;
  font-size: 11px;
  color: var(--text-dim);
}

.version-mismatch-card .btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
  flex-shrink: 0;
}
.version-mismatch-card .btn:hover { background: var(--bg-hover); }
.version-mismatch-card .btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}
.version-mismatch-card .btn-accent:hover { filter: brightness(1.1); }

/* ── 离线编辑遮罩 ── */
.offline-overlay {
  position: fixed;
  inset: 0;
  z-index: 499;  /* 低于 dead-overlay(500)，高于 LoadingOverlay(150) */
  background: oklch(0 0 0 / 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: not-allowed;
}
.offline-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-light);
  border-top-color: var(--warn);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 确认对话框 ── */
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

.confirm-box .error-detail {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #e57373;
  background: rgba(229, 115, 115, 0.08);
  padding: 6px 10px;
  border-radius: 4px;
  margin-top: -10px;
  word-break: break-all;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.confirm-actions .btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
}
.confirm-actions .btn:hover { background: var(--bg-hover); }
.confirm-actions .btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}
.confirm-actions .btn-accent:hover { filter: brightness(1.1); }

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
