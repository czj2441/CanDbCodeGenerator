<template>
  <div class="data-error-list" :class="{ collapsed: isCollapsed }">
    <div class="error-list-header" @click="isCollapsed = !isCollapsed">
      <span class="error-list-title">
        ⚠ {{ t('dataErrors.title') }} ({{ totalCount }})
      </span>
      <span class="collapse-icon">{{ isCollapsed ? '▸' : '▾' }}</span>
    </div>

    <div v-if="!isCollapsed && totalCount > 0" class="error-list-body">
      <div v-for="group in groupedErrors" :key="group.msg_id" class="error-group">
        <div class="group-header" @click="toggleGroup(group.msg_id)">
          <span class="expand-icon">{{ group.expanded ? '▼' : '▶' }}</span>
          <span class="msg-id">{{ group.msg_id_hex }}</span>
          <span class="msg-name">{{ group.msg_name }}</span>
          <span class="error-count">({{ group.errors.length }})</span>
        </div>
        <template v-if="group.expanded">
          <div
            v-for="(err, idx) in group.errors"
            :key="idx"
            class="error-row"
            @click="navigateToError(err)"
          >
            <span class="error-icon">{{ errorIcon(err.type) }}</span>
            <span class="error-desc">{{ errorDescription(err) }}</span>
            <span class="error-arrow">→</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { useMessagesStore } from '../stores/messages.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

const editor = useEditorStore()
const messages = useMessagesStore()
const ui = useUiStore()

const isCollapsed = ref(true)  // 默认折叠

// 导出被拦截时自动展开错误面板
watch(() => ui.expandDataErrors, (val) => {
  if (val) {
    isCollapsed.value = false
    ui.expandDataErrors = false
  }
})

// ── 错误图标和描述 ──
const ERROR_ICONS = {
  out_of_bounds: '⚠', overlap: '⚠', factor_zero: '⚠',
  signal_name_empty: '❌', signal_name_duplicate: '⚠',
  signal_length_zero: '❌', message_name_empty: '❌',
}
function errorIcon(type) { return ERROR_ICONS[type] || '⚠' }

function errorDescription(err) {
  const key = `dataErrors.type.${err.type}`
  return t(key, {
    name: err.signal_name || '',
    other: err.conflicts_name || '',
    bits: (err.out_of_bounds_bits || err.overlapping_bits || []).join(','),
    max: err.max_bit ?? '',
  })
}

// ── 分组（响应式，支持折叠/展开）──
const expandedGroups = ref(new Set())

const groupedErrors = computed(() => {
  const errors = editor.dataErrors || []
  const map = new Map()
  for (const err of errors) {
    if (!map.has(err.msg_id)) {
      const msg = editor.messages.find(m => m.id === err.msg_id)
      map.set(err.msg_id, {
        msg_id: err.msg_id,
        msg_id_hex: '0x' + err.msg_id.toString(16).toUpperCase(),
        msg_name: msg?.name || '(unknown)',
        errors: [],
        expanded: expandedGroups.value.has(err.msg_id),
      })
    }
    map.get(err.msg_id).errors.push(err)
  }
  return [...map.values()]
})

function toggleGroup(msgId) {
  const next = new Set(expandedGroups.value)
  if (next.has(msgId)) next.delete(msgId)
  else next.add(msgId)
  expandedGroups.value = next  // 触发响应式
}

const totalCount = computed(() => (editor.dataErrors || []).length)

// ── 跳转逻辑 ──
async function navigateToError(err) {
  // Step 1: 选中目标报文并等待数据加载
  messages.selectMessage(err.msg_id)
  await nextTick()
  const MAX_WAIT_MS = 5000
  const start = Date.now()
  while (editor.messageCache[err.msg_id] == null) {
    if (Date.now() - start > MAX_WAIT_MS) {
      ui.showToast('报文加载失败，无法跳转', true)
      return
    }
    await new Promise(r => setTimeout(r, 50))
  }
  await nextTick()

  // Step 2: 定位并高亮信号行
  if (err.signal_uuid) {
    ui.selectedSignalUuid = err.signal_uuid
    await nextTick()
    const row = document.querySelector(`[data-sig-id="${err.signal_uuid}"]`)
    row?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    row?.classList.add('highlight-flash')
    setTimeout(() => row?.classList.remove('highlight-flash'), 2000)
  }
}
</script>

<style scoped>
.data-error-list {
  flex-shrink: 0;
  max-height: 200px;
  overflow-y: auto;
  border-top: 1px solid var(--border);
  font-size: 12px;
}
.data-error-list.collapsed {
  max-height: unset;
  overflow-y: hidden;
}

.error-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  cursor: pointer;
  user-select: none;
  background: var(--bg-panel);
  color: var(--text-dim);
  font-weight: 600;
}
.error-list-header:hover {
  background: var(--bg-hover);
}

.error-list-title {
  font-size: 12px;
}
.collapse-icon {
  font-size: 10px;
  color: var(--text-muted);
}

.error-list-body {
  background: var(--bg);
}

.error-group {
  border-bottom: 1px solid var(--border);
}
.error-group:last-child {
  border-bottom: none;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 16px;
  cursor: pointer;
  user-select: none;
  color: var(--text-dim);
  font-weight: 500;
}
.group-header:hover {
  background: var(--bg-hover);
}

.expand-icon {
  font-size: 9px;
  width: 12px;
  text-align: center;
  color: var(--text-muted);
}
.msg-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
}
.msg-name {
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.error-count {
  color: var(--warn);
  font-size: 11px;
  margin-left: auto;
  flex-shrink: 0;
}

.error-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px 2px 34px;
  cursor: pointer;
  color: var(--text-dim);
}
.error-row:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.error-icon {
  flex-shrink: 0;
  font-size: 11px;
}
.error-desc {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.error-arrow {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 11px;
}
</style>
