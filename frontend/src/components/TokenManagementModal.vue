<script setup>
/**
 * TokenManagementModal — 个人访问令牌 (PAT) 管理 Modal。
 *
 * 功能：令牌列表（名称/创建时间/过期时间/最后使用）、创建令牌（备注名 + 过期时间）、
 * 创建后一次性展示明文（含复制按钮）、逐条吊销。
 * 所有用户可用，在 FileBrowser 用户下拉菜单中提供入口。
 */
import { ref, watch } from 'vue'
import { useAuthStore } from '../stores/authStore.js'
import { useUiStore } from '../stores/uiStore.js'
import { t } from '../i18n.js'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible'])

const authStore = useAuthStore()
const ui = useUiStore()

const tokens = ref([])
const loading = ref(false)

// 创建表单
const newName = ref('')
const expiryMode = ref('never')   // 'never' | '30' | '90' | 'custom'
const customDays = ref('')
const creating = ref(false)

// 创建后一次性明文（关闭弹窗即销毁，无法再次获取）
const justCreated = ref(null)     // { name, token }

const revoking = ref(false)

async function fetchTokens() {
  loading.value = true
  try {
    tokens.value = await authStore.listTokens()
  } catch (e) {
    ui.showToast(t('tokens.loadFailed') + ': ' + e.message, true)
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
  justCreated.value = null
  newName.value = ''
  expiryMode.value = 'never'
  customDays.value = ''
}

function formatTime(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

async function copyToken() {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(justCreated.value.token)
    } else {
      // 非安全上下文无 Clipboard API，退回 execCommand
      const ta = document.createElement('textarea')
      ta.value = justCreated.value.token
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    ui.showToast(t('tokens.copied'))
  } catch {
    ui.showToast(t('tokens.copyFailed'), true)
  }
}

async function doCreate() {
  const name = newName.value.trim()
  if (!name) {
    ui.showToast(t('tokens.nameRequired'), true)
    return
  }
  if (name.length > 64) {
    ui.showToast(t('tokens.nameTooLong'), true)
    return
  }
  let expiresDays = null
  if (expiryMode.value === 'custom') {
    expiresDays = Number(customDays.value)
    if (!Number.isInteger(expiresDays) || expiresDays < 1 || expiresDays > 3650) {
      ui.showToast(t('tokens.customDaysInvalid'), true)
      return
    }
  } else if (expiryMode.value !== 'never') {
    expiresDays = Number(expiryMode.value)
  }
  creating.value = true
  try {
    const data = await authStore.createToken(name, expiresDays)
    justCreated.value = { name: data.name, token: data.token }
    newName.value = ''
    expiryMode.value = 'never'
    customDays.value = ''
    ui.showToast(t('tokens.createdToast', { name: data.name }))
    await fetchTokens()
  } catch (e) {
    ui.showToast(t('tokens.createFailed') + ': ' + e.message, true)
  } finally {
    creating.value = false
  }
}

async function doRevoke(tok) {
  revoking.value = true
  try {
    await authStore.revokeToken(tok.id)
    ui.showToast(t('tokens.revokeSuccess', { name: tok.name }))
    await fetchTokens()
  } catch (e) {
    ui.showToast(t('tokens.revokeFailed') + ': ' + e.message, true)
  } finally {
    revoking.value = false
  }
}

watch(() => props.visible, (val) => {
  if (val) fetchTokens()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="modal-overlay" @mousedown.self="close">
        <div class="modal-box token-modal" @click.stop>
          <div class="modal-header">
            <h3>{{ t('tokens.title') }}</h3>
            <button class="modal-close" @click="close">✕</button>
          </div>

          <!-- 创建后一次性明文展示 -->
          <div v-if="justCreated" class="token-once">
            <div class="token-once-warn">{{ t('tokens.onceWarning') }}</div>
            <div class="token-once-row">
              <input class="form-input token-plain" :value="justCreated.token" readonly
                     @focus="$event.target.select()" />
              <button class="btn-sm btn-sm-confirm" @click="copyToken">{{ t('tokens.copy') }}</button>
            </div>
          </div>

          <!-- 令牌列表 -->
          <div class="token-list">
            <div v-if="loading" class="loading-hint">{{ t('tokens.loading') }}</div>
            <div v-else-if="tokens.length === 0" class="empty-hint">{{ t('tokens.empty') }}</div>
            <table v-else class="token-table">
              <thead>
                <tr>
                  <th>{{ t('tokens.colName') }}</th>
                  <th>{{ t('tokens.colCreated') }}</th>
                  <th>{{ t('tokens.colExpires') }}</th>
                  <th>{{ t('tokens.colLastUsed') }}</th>
                  <th>{{ t('tokens.colActions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="tok in tokens" :key="tok.id">
                  <td>{{ tok.name }}</td>
                  <td>{{ formatTime(tok.created_at) }}</td>
                  <td>{{ tok.expires_at == null ? t('tokens.neverExpires') : formatTime(tok.expires_at) }}</td>
                  <td>{{ tok.last_used_at == null ? t('tokens.neverUsed') : formatTime(tok.last_used_at) }}</td>
                  <td>
                    <button class="btn-sm btn-sm-danger" :disabled="revoking" @click="doRevoke(tok)">
                      {{ t('tokens.revoke') }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 创建表单 -->
          <div class="create-section">
            <div class="field">
              <label>{{ t('tokens.nameLabel') }}</label>
              <input v-model="newName" class="form-input" :placeholder="t('tokens.namePlaceholder')"
                     maxlength="64" @keydown.enter="doCreate" />
            </div>
            <div class="field">
              <label>{{ t('tokens.expiryLabel') }}</label>
              <div class="expiry-row">
                <select v-model="expiryMode" class="form-input">
                  <option value="never">{{ t('tokens.expiryNever') }}</option>
                  <option value="30">{{ t('tokens.expiry30') }}</option>
                  <option value="90">{{ t('tokens.expiry90') }}</option>
                  <option value="custom">{{ t('tokens.expiryCustom') }}</option>
                </select>
                <input v-if="expiryMode === 'custom'" v-model="customDays" type="number"
                       min="1" max="3650" class="form-input days-input"
                       :placeholder="t('tokens.customDaysPlaceholder')" />
              </div>
            </div>
            <div class="create-actions">
              <button class="btn-sm btn-sm-confirm" :disabled="creating" @click="doCreate">
                {{ creating ? t('tokens.creating') : t('tokens.create') }}
              </button>
            </div>
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
  max-width: 640px; width: 90%;
  box-shadow: var(--shadow);
}
.token-modal { max-height: 80vh; overflow-y: auto; }
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.modal-header h3 { margin: 0; font-size: 18px; }
.modal-close {
  background: none; border: none; color: var(--text-muted);
  cursor: pointer; font-size: 18px; padding: 4px 8px;
}
.modal-close:hover { color: var(--text); }

/* 一次性明文展示 */
.token-once {
  margin-bottom: 16px; padding: 12px;
  background: var(--bg); border: 1px solid var(--accent);
  border-radius: var(--radius);
}
.token-once-warn {
  color: var(--danger); font-size: 12px; margin-bottom: 8px;
}
.token-once-row { display: flex; gap: 8px; }
.token-plain {
  flex: 1; font-family: monospace; font-size: 12px;
  user-select: all;
}

/* 令牌列表 */
.token-list { margin-bottom: 16px; }
.loading-hint, .empty-hint { color: var(--text-muted); font-size: 13px; padding: 8px 0; }
.token-table {
  width: 100%; border-collapse: collapse; font-size: 12px;
}
.token-table th, .token-table td {
  padding: 6px 8px; border-bottom: 1px solid var(--border);
  text-align: left; white-space: nowrap;
}
.token-table th {
  color: var(--text-muted); font-weight: 500; font-size: 11px;
}

/* 创建表单 */
.create-section {
  padding-top: 12px; border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 10px;
}
.field label {
  display: block; font-size: 12px; color: var(--text-muted);
  margin-bottom: 4px;
}
.form-input {
  width: 100%; padding: 6px 10px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--bg);
  color: var(--text); font-size: 13px;
}
.form-input:focus { border-color: var(--accent); outline: none; }
.expiry-row { display: flex; gap: 8px; }
.days-input { width: 120px; }
.create-actions { display: flex; gap: 8px; justify-content: flex-end; }

.btn-sm {
  background: var(--bg-raised); border: 1px solid var(--border);
  color: var(--text); padding: 4px 10px; border-radius: var(--radius-sm);
  font-size: 12px; cursor: pointer;
}
.btn-sm:hover:not(:disabled) { background: var(--bg-hover); }
.btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-sm-confirm { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-sm-confirm:hover:not(:disabled) { opacity: 0.9; }
.btn-sm-danger { color: var(--danger); border-color: var(--danger); }
.btn-sm-danger:hover:not(:disabled) { background: var(--danger); color: #fff; }

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
