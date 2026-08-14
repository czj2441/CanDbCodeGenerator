<script setup>
/**
 * UserManagementModal — 管理员用户管理 Modal。
 *
 * 功能：用户列表、创建用户、删除用户、修改角色、重置密码。
 * 仅 admin 角色可见入口。
 */
import { ref, watch } from 'vue'
import { useAuthStore } from '../stores/authStore.js'
import { useUiStore } from '../stores/uiStore.js'

const props = defineProps({
  visible: Boolean,
})
const emit = defineEmits(['update:visible'])

const authStore = useAuthStore()
const ui = useUiStore()

const users = ref([])
const loading = ref(false)

// 创建用户表单
const showCreateForm = ref(false)
const newUsername = ref('')
const newPassword = ref('')
const newRole = ref('user')

// 重置密码表单
const resetTarget = ref(null)
const resetPassword = ref('')

async function fetchUsers() {
  loading.value = true
  try {
    users.value = await authStore.fetchUsers()
  } catch (e) {
    ui.showToast('获取用户列表失败: ' + e.message, true)
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
  showCreateForm.value = false
  resetTarget.value = null
}

async function createUser() {
  if (!newUsername.value.trim() || !newPassword.value) {
    ui.showToast('用户名和密码不能为空', true)
    return
  }
  try {
    await authStore.createUser(newUsername.value.trim(), newPassword.value, newRole.value)
    ui.showToast(`用户 ${newUsername.value} 创建成功`)
    showCreateForm.value = false
    newUsername.value = ''
    newPassword.value = ''
    newRole.value = 'user'
    await fetchUsers()
  } catch (e) {
    ui.showToast('创建用户失败: ' + e.message, true)
  }
}

async function deleteUser(username) {
  if (username === authStore.username) {
    ui.showToast('不能删除自己', true)
    return
  }
  try {
    await authStore.deleteUser(username)
    ui.showToast(`用户 ${username} 已删除`)
    await fetchUsers()
  } catch (e) {
    if (e.files && e.files.length > 0) {
      ui.showToast(`删除失败：用户拥有 ${e.files.length} 个文件，请先转移所有权`, true)
    } else {
      ui.showToast('删除失败: ' + e.message, true)
    }
  }
}

async function changeRole(username, currentRole) {
  const newRole = currentRole === 'admin' ? 'user' : 'admin'
  try {
    await authStore.updateUserRole(username, newRole)
    ui.showToast(`${username} 角色已改为 ${newRole}`)
    await fetchUsers()
  } catch (e) {
    ui.showToast('修改角色失败: ' + e.message, true)
  }
}

function openResetPassword(username) {
  resetTarget.value = username
  resetPassword.value = ''
}

async function doResetPassword() {
  if (!resetPassword.value) {
    ui.showToast('新密码不能为空', true)
    return
  }
  try {
    await authStore.resetUserPassword(resetTarget.value, resetPassword.value)
    ui.showToast(`${resetTarget.value} 密码已重置`)
    resetTarget.value = null
    resetPassword.value = ''
  } catch (e) {
    ui.showToast('重置密码失败: ' + e.message, true)
  }
}

watch(() => props.visible, (val) => {
  if (val) fetchUsers()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="modal-overlay" @mousedown.self="close">
        <div class="modal-box user-mgmt-modal" @click.stop>
          <div class="modal-header">
            <h3>用户管理</h3>
            <button class="modal-close" @click="close">✕</button>
          </div>

          <!-- 用户列表 -->
          <div class="user-list">
            <div v-if="loading" class="loading-hint">加载中...</div>
            <div v-for="u in users" :key="u.username" class="user-row">
              <div class="user-info">
                <span class="user-name">{{ u.username }}</span>
                <span class="user-role" :class="{ 'role-admin': u.role === 'admin' }">
                  {{ u.role }}
                </span>
              </div>
              <div class="user-actions">
                <button class="btn-sm" @click="changeRole(u.username, u.role)"
                        :disabled="u.username === authStore.username"
                        :title="u.role === 'admin' ? '降级为 user' : '升级为 admin'">
                  {{ u.role === 'admin' ? '降级' : '升级' }}
                </button>
                <button class="btn-sm" @click="openResetPassword(u.username)">重置密码</button>
                <button class="btn-sm btn-sm-danger" @click="deleteUser(u.username)"
                        :disabled="u.username === authStore.username">
                  删除
                </button>
              </div>
            </div>
          </div>

          <!-- 创建用户 -->
          <div class="create-section">
            <button v-if="!showCreateForm" class="btn-create" @click="showCreateForm = true">
              + 创建新用户
            </button>
            <div v-else class="create-form">
              <input v-model="newUsername" placeholder="用户名" class="form-input" />
              <input v-model="newPassword" type="password" placeholder="初始密码" class="form-input" />
              <select v-model="newRole" class="form-input">
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
              <div class="create-actions">
                <button class="btn-sm" @click="showCreateForm = false">取消</button>
                <button class="btn-sm btn-sm-confirm" @click="createUser">创建</button>
              </div>
            </div>
          </div>

          <!-- 重置密码对话框 -->
          <div v-if="resetTarget" class="reset-section">
            <p>重置 <strong>{{ resetTarget }}</strong> 的密码：</p>
            <input v-model="resetPassword" type="password" placeholder="新密码" class="form-input" />
            <div class="create-actions">
              <button class="btn-sm" @click="resetTarget = null">取消</button>
              <button class="btn-sm btn-sm-confirm" @click="doResetPassword">确认重置</button>
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
  max-width: 520px; width: 90%;
  box-shadow: var(--shadow);
}
.user-mgmt-modal { max-height: 80vh; overflow-y: auto; }
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

.user-list { margin-bottom: 16px; }
.loading-hint { color: var(--text-muted); font-size: 13px; padding: 8px 0; }
.user-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; border-bottom: 1px solid var(--border);
}
.user-info { display: flex; align-items: center; gap: 8px; }
.user-name { font-weight: 500; font-size: 14px; }
.user-role {
  display: inline-block; padding: 2px 8px;
  background: var(--bg-hover); border-radius: var(--radius-sm);
  font-size: 11px; color: var(--text-dim);
}
.user-role.role-admin { background: var(--accent); color: #fff; }
.user-actions { display: flex; gap: 6px; }

.btn-sm {
  background: var(--bg-raised); border: 1px solid var(--border);
  color: var(--text); padding: 4px 10px; border-radius: var(--radius-sm);
  font-size: 12px; cursor: pointer;
}
.btn-sm:hover:not(:disabled) { background: var(--bg-hover); }
.btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-sm-confirm { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-sm-confirm:hover { opacity: 0.9; }
.btn-sm-danger { color: var(--danger); border-color: var(--danger); }
.btn-sm-danger:hover:not(:disabled) { background: var(--danger); color: #fff; }

.create-section { margin-top: 12px; }
.btn-create {
  background: transparent; border: 1px dashed var(--border);
  color: var(--text-dim); padding: 8px 16px; border-radius: var(--radius);
  font-size: 13px; cursor: pointer; width: 100%;
}
.btn-create:hover { border-color: var(--accent); color: var(--accent); }
.create-form { display: flex; flex-direction: column; gap: 8px; }
.form-input {
  padding: 6px 10px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--bg);
  color: var(--text); font-size: 13px;
}
.form-input:focus { border-color: var(--accent); outline: none; }
.create-actions { display: flex; gap: 8px; justify-content: flex-end; }

.reset-section {
  margin-top: 12px; padding: 12px;
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius);
}
.reset-section p { margin: 0 0 8px; font-size: 13px; }

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
