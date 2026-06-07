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
      <HistoryModal />
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
import { initTabSync, cleanupTabSync } from './api/client.js'
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
import HistoryModal from './components/HistoryModal.vue'
import LogPanel from './components/LogPanel.vue'

const store = useEditorStore()
const ui = useUiStore()
let healthTimer = null

// 应用模式：'browser' | 'editor'
const mode = ref('browser')

function handleTabConflict(e) {
  // 使用 alert 确保用户能看到警告（Toast 在 BroadcastChannel 回调中无法触发）
  alert(t('toast.multiTabConflict'))
  console.warn(`[TabSync] Event handled: current=${e.detail.currentSid}, other=${e.detail.otherSid}`)
}

onMounted(() => {
  // 默认进入文件浏览器模式
  mode.value = 'browser'
  document.addEventListener('click', hideMenu)
  document.documentElement.setAttribute('data-theme', ui.theme)

  // 初始化多标签页冲突检测（使用已获取的 ui 实例）
  initTabSync((currentSid, otherSid) => {
    window.dispatchEvent(new CustomEvent('tab-conflict', { detail: { currentSid, otherSid } }))
    console.warn(`[TabSync] Session conflict detected: current=${currentSid}, other=${otherSid}`)
  })

  // 监听多标签页冲突事件
  window.addEventListener('tab-conflict', handleTabConflict)
})

onUnmounted(() => {
  clearInterval(healthTimer)
  document.removeEventListener('click', hideMenu)
  window.removeEventListener('tab-conflict', handleTabConflict)
  cleanupTabSync()
})

// 打开文件
async function openFile(sessionId) {
  try {
    await store.loadHistorySession(sessionId)
    mode.value = 'editor'
    startHealthCheck()
  } catch (e) {
    // 加载失败，保持在浏览器模式
    console.error('Failed to open file:', e)
  }
}

// 新建文件
async function createNewFile() {
  try {
    await store.newFile()
    mode.value = 'editor'
    startHealthCheck()
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
