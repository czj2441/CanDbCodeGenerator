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
      <BatchModal v-model:visible="ui.batchModalOpen" />
      <LoadingOverlay />
      <ContextMenu :items="contextMenuItems" />
    </template>
    <!-- Toast 在所有模式下都渲染 -->
    <Toast />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useEditorStore } from './stores/editor.js'
import { useUiStore } from './stores/uiStore.js'
import { t } from './i18n.js'
import { api, initTabSync, cleanupTabSync, getSessionId, clearSession } from './api/client.js'
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
let healthTimer = null
let lockCheckTimer = null  // 文件锁状态检查定时器
let heartbeatTimer = null  // 心跳定时器
let beforeUnloadHandler = null  // beforeunload 事件处理器

// 应用模式：'browser' | 'editor'
const mode = ref('browser')

function handleSessionStolen(stolenSessionId) {
  // 当前 session 被其他标签页抢占，自动返回文件浏览器
  console.warn(`[TabSync] handleSessionStolen called: session ${stolenSessionId} was stolen by another tab`)
  ui.showToast(t('toast.sessionStolen'), true)
  goBack()
}

onMounted(() => {
  // 默认进入文件浏览器模式
  mode.value = 'browser'
  document.addEventListener('click', hideMenu)
  document.documentElement.setAttribute('data-theme', ui.theme)

  // 初始化多标签页同步（steal 通知）
  initTabSync(
    (stolenSessionId) => {
      handleSessionStolen(stolenSessionId)
    }
  )

  // 页面关闭/刷新时：保存数据 + 释放文件锁 + 确认对话框
  beforeUnloadHandler = (e) => {
    const sid = getSessionId()
    
    // 无论是否有修改，都释放文件锁（必须优先执行）
    if (sid) {
      navigator.sendBeacon('/api/release?sid=' + encodeURIComponent(sid))
    }
    
    // 如果有未保存的修改，弹出确认对话框
    if (sid && store.modified) {
      // 尝试保存数据（sendBeacon 不支持自定义请求头，使用 URL 参数）
      navigator.sendBeacon('/api/save?sid=' + encodeURIComponent(sid))
      
      // 弹出确认对话框（防止误关闭/刷新）
      e.preventDefault()
      e.returnValue = '您有未保存的更改，确定要离开吗？'
      return e.returnValue
    }
  }
  window.addEventListener('beforeunload', beforeUnloadHandler)
})

onUnmounted(() => {
  clearInterval(healthTimer)
  document.removeEventListener('click', hideMenu)
  cleanupTabSync()
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
    startHealthCheck()
    startLockCheck()  // 启动文件锁状态检查
    startHeartbeat()  // 启动心跳
  } catch (e) {
    // 加载失败，保持在浏览器模式
    console.error('Failed to open file:', e)
    // 409 错误显示提示
    if (e.status === 409) {
      ui.showToast(e.message, true)
    }
  }
}

// 新建文件
async function createNewFile() {
  try {
    await store.newFile()
    mode.value = 'editor'
    startHealthCheck()
    startLockCheck()  // 启动文件锁状态检查
    startHeartbeat()  // 启动心跳
  } catch (e) {
    // 创建失败，保持在浏览器模式
    console.error('Failed to create new file:', e)
  }
}

// 返回文件浏览器
function goBack() {
  // 释放文件锁
  store.releaseSession()
  // 清理编辑器状态
  store.clearUndoStack()
  store.selectedMsgId = null
  store.messageCache = {}
  store.messages = []
  store.signalErrors = []
  store.editorState = null
  // 停止健康检查
  stopHealthCheck()
  stopLockCheck()  // 停止文件锁状态检查
  stopHeartbeat()  // 停止心跳
  mode.value = 'browser'
}

// 健康检查定时器管理
function startHealthCheck() {
  stopHealthCheck()
  healthTimer = setInterval(() => store.checkApiHealth(), 15000)
}

function stopHealthCheck() {
  if (healthTimer) {
    clearInterval(healthTimer)
    healthTimer = null
  }
}

// 文件锁状态检查定时器管理
function startLockCheck() {
  stopLockCheck()
  lockCheckTimer = setInterval(async () => {
    if (mode.value !== 'editor') return
    const currentSid = getSessionId()
    if (!currentSid) return
    
    try {
      // 请求当前 session 的信息，后端会检查文件锁状态
      const res = await api('GET', `/api/session/${currentSid}/info`)
      // 如果后端返回 session 信息，说明当前标签页仍有权限
    } catch (e) {
      // 409 Conflict 表示文件已被其他标签页抢占
      if (e.message && e.message.includes('409')) {
        console.warn('[LockCheck] Session stolen by another tab')
        ui.showToast(t('toast.noEditPermission'), true)
        goBack()
      }
    }
  }, 500)
}

function stopLockCheck() {
  if (lockCheckTimer) {
    clearInterval(lockCheckTimer)
    lockCheckTimer = null
  }
}

// 心跳定时器管理（每 10 秒发送一次，通知后端该标签页仍在编辑）
function startHeartbeat() {
  stopHeartbeat()
  heartbeatTimer = setInterval(async () => {
    const sid = getSessionId()
    if (!sid) return
    try {
      await api('POST', '/api/heartbeat', { session_id: sid })
    } catch (e) {
      // 心跳失败不提示用户，静默处理
      console.warn('[Heartbeat] failed:', e.message)
    }
  }, 10000)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
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
</style>
