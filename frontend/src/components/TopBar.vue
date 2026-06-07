<template>
  <div class="topbar">
    <button class="btn btn-icon btn-back" @click="$emit('back')" :title="t('topbar.back')">←</button>
    <div class="topbar-logo">Can<span>Matrix</span></div>
    <input class="topbar-filename" :value="store.currentFileName" spellcheck="false" @blur="rename">
    <span class="topbar-spacer"></span>
    <button class="btn" @click="store.undo()" :disabled="!store.canUndo" title="撤销 (Ctrl+Z)">{{ t('topbar.undo') }}</button>
    <button class="btn" @click="store.redo()" :disabled="!store.canRedo" title="重做 (Ctrl+Y)">{{ t('topbar.redo') || '重做' }}</button>
    <button class="btn" @click="onNew">{{ t('topbar.new') }}</button>
    <button class="btn" @click="openHistory">{{ t('topbar.history') }}</button>
    <button class="btn" @click="importFile">{{ t('topbar.import') }}</button>
    <button class="btn btn-accent" @click="exportFile('dbc')">{{ t('topbar.export') }}</button>
    <button class="btn" @click="save">{{ t('topbar.save') }}</button>
    <span class="topbar-spacer"></span>
    <button class="btn btn-icon" @click="ui.toggleLocale" title="切换语言">{{ ui.locale === 'zh' ? '中' : 'EN' }}</button>
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
      {{ store.apiStatus === 'connected' ? t('topbar.connected') : t('topbar.offline') }}
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
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

defineEmits(['back'])

const store = useEditorStore()
const ui = useUiStore()
const newSessionName = ref('')

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
      store.undo()
    } else if (event.key === 'y' || event.key === 'Y') {
      event.preventDefault()
      store.redo()
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})

watch(() => ui.newConfirmOpen, (open) => { if (open) newSessionName.value = '' })

function onNew() {
  ui.newConfirmOpen = true
}

function confirmNew() {
  ui.newConfirmOpen = false
  const name = newSessionName.value.trim() || 'Untitled'
  store.createNewSession(name)
}

function openHistory() {
  store.loadSessionHistory()
  ui.historyModalOpen = true
}

function rename(event) {
  let name = event.target.value.replace(/\.toml$/i, '').trim()
  name = name.replace(/^[a-f0-9]{12}_/i, '').trim()
  if (!name) return
  store.renameSession(name)
}

function importFile() {
  const ui = useUiStore()
  ui.showToast('导入功能开发中', true)
}

function exportFile(fmt) {
  const ui = useUiStore()
  ui.showToast('导出功能开发中', true)
}

function save() {
  const ui = useUiStore()
  ui.showToast('保存功能开发中', true)
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
  outline: none;
}
.topbar-filename:focus { border-color: var(--accent-dim); }

.topbar-spacer { flex: 1; }

.api-status {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.api-status.connected { color: var(--accent); }
.api-status.offline { color: var(--danger); }

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
</style>
