<script setup>
/**
 * OnlineUsersModal — 管理员查看在线用户。
 *
 * 显示所有活跃 WS 连接：编辑器、查看器、文件浏览器。
 * 同一用户可能出现在多行（多标签页/多设备）。
 * 一次性 HTTP 获取，用户可手动刷新。
 */
import { ref, watch } from 'vue'
import { useAuthStore } from '../stores/authStore.js'
import { useUiStore } from '../stores/uiStore.js'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible'])

const authStore = useAuthStore()
const ui = useUiStore()

const sessions = ref([])
const loading = ref(false)

async function fetchData() {
  loading.value = true
  try {
    sessions.value = await authStore.fetchOnlineUsers()
  } catch (e) {
    ui.showToast('获取在线用户失败: ' + e.message, true)
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
}

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  })
}

function sessionTypeLabel(type) {
  const map = { editor: '编辑器', viewer: '查看器', '浏览文件': '浏览文件' }
  return map[type] || type
}

function sessionTypeClass(type) {
  const map = { editor: 'type-editor', viewer: 'type-viewer', '浏览文件': 'type-browser' }
  return map[type] || ''
}

watch(() => props.visible, (val) => {
  if (val) fetchData()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="modal-overlay" @mousedown.self="close">
        <div class="modal-box online-users-modal" @click.stop>
          <div class="modal-header">
            <h3>在线用户</h3>
            <button class="modal-close" @click="close">✕</button>
          </div>

          <div class="session-count">共 {{ sessions.length }} 个活跃连接</div>

          <div v-if="loading" class="loading-hint">加载中...</div>
          <div v-else-if="sessions.length === 0" class="empty-hint">当前无在线用户</div>

          <table v-else class="online-table">
            <thead>
              <tr>
                <th>用户名</th>
                <th>IP 地址</th>
                <th>最后活跃</th>
                <th>当前文件</th>
                <th>类型</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in sessions" :key="s.session_id">
                <td class="col-username">{{ s.username || '—' }}</td>
                <td class="col-ip">{{ s.ip || '—' }}</td>
                <td class="col-time">{{ formatTime(s.last_activity) }}</td>
                <td class="col-file">{{ s.file_name }}</td>
                <td class="col-type">
                  <span class="type-badge" :class="sessionTypeClass(s.session_type)">
                    {{ sessionTypeLabel(s.session_type) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="modal-footer">
            <button class="btn-refresh" @click="fetchData" :disabled="loading">
              刷新
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex; align-items: center; justify-content: center;
  z-index: 1600;
}
.modal-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  max-width: 680px; width: 90%;
  box-shadow: var(--shadow);
}
.online-users-modal { max-height: 80vh; overflow-y: auto; }
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 8px;
}
.modal-header h3 { margin: 0; font-size: 18px; }
.modal-close {
  background: none; border: none; color: var(--text-muted);
  cursor: pointer; font-size: 18px; padding: 4px 8px;
}
.modal-close:hover { color: var(--text); }

.session-count { font-size: 12px; color: var(--text-muted); margin-bottom: 12px; }
.loading-hint, .empty-hint {
  color: var(--text-muted); font-size: 13px;
  padding: 24px 0; text-align: center;
}

.online-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
.online-table th {
  text-align: left; padding: 8px 10px;
  border-bottom: 2px solid var(--border);
  color: var(--text-dim); font-weight: 600;
  white-space: nowrap;
}
.online-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
.col-username { font-weight: 500; }
.col-ip { color: var(--text-muted); font-size: 12px; font-family: monospace; }
.col-time { color: var(--text-muted); font-size: 12px; white-space: nowrap; }
.col-file { color: var(--text); }

.type-badge {
  display: inline-block; padding: 2px 8px;
  border-radius: var(--radius-sm); font-size: 11px; font-weight: 500;
  white-space: nowrap;
}
.type-editor { background: var(--accent); color: #fff; }
.type-viewer { background: var(--bg-hover); color: var(--text-dim); }
.type-browser { background: var(--bg-raised); color: var(--text-muted); }

.modal-footer {
  margin-top: 12px; display: flex; justify-content: flex-end;
}
.btn-refresh {
  background: transparent; border: 1px solid var(--border);
  color: var(--text); padding: 6px 14px; border-radius: var(--radius);
  font-size: 13px; cursor: pointer;
}
.btn-refresh:hover:not(:disabled) { background: var(--bg-hover); }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
