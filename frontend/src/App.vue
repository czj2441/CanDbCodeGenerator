<template>
  <div class="app" @contextmenu="onContextMenu">
    <!-- 文件浏览器模式 -->
    <FileBrowser v-if="mode === 'browser'" @open="openFile" @new="createNewFile" />
    <!-- 编辑器模式 -->
    <template v-else>
      <TopBar @back="goBack" />
      <div class="main">
        <MessageList />
        <div class="center">
          <SignalLayoutVisualizer v-if="ui.layoutViewMode" />
          <SignalTable v-else />
          <LogPanel />
        </div>
        <MessagePanel />
      </div>
      <StatusBar />
      <!-- 离线编辑遮罩：覆盖编辑区域，不遮挡 TopBar -->
      <div v-if="store._hasBeenConnected && store.apiStatus !== 'connected' && store.apiStatus !== 'dead'" class="offline-overlay">
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
    <!-- 死遮罩：全局覆盖所有模式 -->
    <div v-if="store.apiStatus === 'dead'" class="dead-overlay">
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
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useEditorStore } from './stores/editor.js'
import { useUiStore } from './stores/uiStore.js'
import { t } from './i18n.js'
import { getSessionId, setSessionId } from './api/client.js'
import FileBrowser from './components/FileBrowser.vue'
import TopBar from './components/TopBar.vue'
import MessageList from './components/MessageList.vue'
import SignalTable from './components/SignalTable.vue'
import SignalLayoutVisualizer from './components/SignalLayoutVisualizer.vue'
import MessagePanel from './components/MessagePanel.vue'
import StatusBar from './components/StatusBar.vue'
import BatchModal from './components/BatchModal.vue'
import LoadingOverlay from './components/LoadingOverlay.vue'
import Toast from './components/Toast.vue'
import ContextMenu from './components/ContextMenu.vue'
import LogPanel from './components/LogPanel.vue'

const store = useEditorStore()
const ui = useUiStore()
let beforeUnloadHandler = null  // beforeunload 事件处理器
let navigateHandler = null     // navigate-browser 事件处理器

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

  // 页面关闭/刷新时：释放文件锁 + 确认对话框
  beforeUnloadHandler = (e) => {
    const sid = getSessionId()
    if (sid) {
      navigator.sendBeacon('/api/release?sid=' + encodeURIComponent(sid))
    }
    if (sid && store.backendDirty) {
      e.preventDefault()
      e.returnValue = '您有未保存的更改，确定要离开吗？'
      return e.returnValue
    }
  }
  window.addEventListener('beforeunload', beforeUnloadHandler)
})

onUnmounted(() => {
  document.removeEventListener('click', hideMenu)
  if (navigateHandler) {
    window.removeEventListener('navigate-browser', navigateHandler)
    navigateHandler = null
  }
  if (beforeUnloadHandler) {
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    beforeUnloadHandler = null
  }
})

// 打开文件
async function openFile(sessionId) {
  try {
    await store.loadHistorySession(sessionId)
    mode.value = 'editor'
    // WS 连接已在 loadHistorySession 中启动
  } catch (e) {
    console.error('Failed to open file:', e)
    if (e.code === 'FILE_LOCKED') {
      ui.showToast(e.message, true)
    }
  }
}

// 新建文件
async function createNewFile() {
  try {
    await store.newFile()
    mode.value = 'editor'
    // WS 连接已在 newFile 中启动
  } catch (e) {
    console.error('Failed to create new file:', e)
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
  const ok = await store.saveSession()
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
  await store.releaseSession()
  // sendBeacon 兆底（WS 可能已断开）
  const sid = getSessionId()
  if (sid) {
    navigator.sendBeacon('/api/release?sid=' + encodeURIComponent(sid) + '&abort=1')
  }
  // 停止 WS 连接
  store.stopEditorSync()
  setSessionId('')   // 清除已销毁的 session ID，防止幻影恢复
  // 清理编辑器所有状态（包含 clipboard 等）
  store.resetEditorState()
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
      { label: t('ctx.copySignal'), action: () => store.copySignal(idx) },
      { label: t('ctx.cutSignal'), action: () => store.cutSignal(idx) },
      { label: t('ctx.pasteSignal'), action: () => store.pasteSignal(), disabled: !store.clipboard || store.clipboard.type !== 'signal' },
      { label: t('ctx.deleteSignal'), action: () => store.deleteSignal(idx), danger: true },
    ]
  }
  if (target === 'message') {
    return [
      { label: t('ctx.copyMessage'), action: () => store.copyMessage() },
      { label: t('ctx.pasteMessage'), action: () => store.pasteMessage(), disabled: !store.clipboard || store.clipboard.type !== 'message' },
      { label: t('ctx.duplicateMessage'), action: () => store.duplicateMessage() },
      { label: t('ctx.deleteMessage'), action: () => store.deleteMessage(store.selectedMsgId), danger: true },
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
