<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="modal-overlay" @click.self="close">
        <div class="modal-panel">
          <div class="modal-header">
            <span class="modal-title">{{ t('ccode_preview.title') }} — {{ filename }}</span>
            <div class="header-actions">
              <button class="btn btn-accent" @click="download">{{ t('ccode_preview.download') }}</button>
              <button class="btn" @click="close">{{ t('ccode_preview.close') }}</button>
            </div>
          </div>
          <div class="modal-body">
            <pre class="ccode-preview-code"><code v-html="highlightedCode"></code></pre>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import hljs from 'highlight.js/lib/core'
import c from 'highlight.js/lib/languages/c'
import { t } from '../i18n.js'
import { useUiStore } from '../stores/uiStore.js'

hljs.registerLanguage('c', c)

const visible = defineModel('visible', { type: Boolean, default: false })

const props = defineProps({
  code: { type: String, default: '' },
  filename: { type: String, default: '' },
  format: { type: String, default: 'c_header' },
})

const uiStore = useUiStore()
const cachedCode = ref('')

const highlightedCode = computed(() => {
  if (!cachedCode.value) return ''
  try {
    return hljs.highlight(cachedCode.value, { language: 'c' }).value
  } catch {
    return escapeHtml(cachedCode.value)
  }
})

watch(visible, (val) => {
  if (val) {
    cachedCode.value = props.code
  }
})

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function download() {
  const blob = new Blob([cachedCode.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = props.filename || 'export.c'
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { URL.revokeObjectURL(url); a.remove() }, 100)
  uiStore.showToast(t('ccode_preview.toastDownloaded', { filename: props.filename }), false)
}

function close() {
  visible.value = false
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: oklch(0.08 0.01 260 / 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 110;
}

.modal-panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 720px;
  max-width: 92vw;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  font-size: 13px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}

.modal-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 12px;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.modal-body {
  padding: 0;
  overflow: auto;
  flex: 1;
}

.ccode-preview-code {
  margin: 0;
  padding: 16px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  background: transparent;
  white-space: pre;
  overflow-x: auto;
}

.ccode-preview-code code {
  font-family: inherit;
}

.btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.btn:hover { background: var(--bg-hover); }
.btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}
.btn-accent:hover { filter: brightness(1.1); }

.modal-enter-active, .modal-leave-active { transition: opacity 200ms; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>

<!-- highlight.js 语法高亮主题：非 scoped，通过组件类名限定作用域 -->
<style>
/* github-dark 基础配色（暗色主题） */
.ccode-preview-code .hljs-keyword,
.ccode-preview-code .hljs-selector-tag,
.ccode-preview-code .hljs-built_in { color: #f97583; }

.ccode-preview-code .hljs-string,
.ccode-preview-code .hljs-attr { color: #9ecbff; }

.ccode-preview-code .hljs-number,
.ccode-preview-code .hljs-literal { color: #79b8ff; }

.ccode-preview-code .hljs-comment { color: #6a737d; font-style: italic; }

.ccode-preview-code .hljs-title,
.ccode-preview-code .hljs-section { color: #b392f0; }

.ccode-preview-code .hljs-type,
.ccode-preview-code .hljs-class .hljs-title { color: #b392f0; }

.ccode-preview-code .hljs-meta,
.ccode-preview-code .hljs-preprocessor { color: #79b8ff; }

.ccode-preview-code .hljs-params { color: #e1e4e8; }

/* 亮色主题覆盖 */
[data-theme="light"] .ccode-preview-code .hljs-keyword,
[data-theme="light"] .ccode-preview-code .hljs-selector-tag,
[data-theme="light"] .ccode-preview-code .hljs-built_in { color: #d73a49; }

[data-theme="light"] .ccode-preview-code .hljs-string,
[data-theme="light"] .ccode-preview-code .hljs-attr { color: #032f62; }

[data-theme="light"] .ccode-preview-code .hljs-number,
[data-theme="light"] .ccode-preview-code .hljs-literal { color: #005cc5; }

[data-theme="light"] .ccode-preview-code .hljs-comment { color: #6a737d; }

[data-theme="light"] .ccode-preview-code .hljs-title,
[data-theme="light"] .ccode-preview-code .hljs-section { color: #6f42c1; }

[data-theme="light"] .ccode-preview-code .hljs-type,
[data-theme="light"] .ccode-preview-code .hljs-class .hljs-title { color: #6f42c1; }

[data-theme="light"] .ccode-preview-code .hljs-meta,
[data-theme="light"] .ccode-preview-code .hljs-preprocessor { color: #005cc5; }

[data-theme="light"] .ccode-preview-code .hljs-params { color: #24292e; }
</style>
