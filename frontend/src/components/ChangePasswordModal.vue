<script setup>
/**
 * ChangePasswordModal — 普通用户修改密码 Modal。
 *
 * 所有用户可用，在 FileBrowser 用户下拉菜单中提供入口。
 */
import { ref } from 'vue'
import { useAuthStore } from '../stores/authStore.js'
import { useUiStore } from '../stores/uiStore.js'

defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible'])

const authStore = useAuthStore()
const ui = useUiStore()

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const submitting = ref(false)

function close() {
  emit('update:visible', false)
  oldPassword.value = ''
  newPassword.value = ''
  confirmPassword.value = ''
}

async function submit() {
  if (!oldPassword.value || !newPassword.value) {
    ui.showToast('请填写所有字段', true)
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    ui.showToast('两次输入的新密码不一致', true)
    return
  }
  if (newPassword.value.length < 4) {
    ui.showToast('新密码至少 4 个字符', true)
    return
  }
  submitting.value = true
  try {
    await authStore.changePassword(oldPassword.value, newPassword.value)
    ui.showToast('密码修改成功')
    close()
  } catch (e) {
    ui.showToast('修改密码失败: ' + e.message, true)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="modal-overlay" @mousedown.self="close">
        <div class="modal-box" @click.stop>
          <div class="modal-header">
            <h3>修改密码</h3>
            <button class="modal-close" @click="close">✕</button>
          </div>
          <div class="form-fields">
            <div class="field">
              <label>当前密码</label>
              <input v-model="oldPassword" type="password" class="form-input" placeholder="输入当前密码" />
            </div>
            <div class="field">
              <label>新密码</label>
              <input v-model="newPassword" type="password" class="form-input" placeholder="输入新密码（至少4位）" />
            </div>
            <div class="field">
              <label>确认新密码</label>
              <input v-model="confirmPassword" type="password" class="form-input" placeholder="再次输入新密码"
                     @keydown.enter="submit" />
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn-cancel" @click="close">取消</button>
            <button class="btn-confirm" :disabled="submitting" @click="submit">
              {{ submitting ? '提交中...' : '确认修改' }}
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
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 24px;
  max-width: 400px; width: 90%; box-shadow: var(--shadow);
}
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

.form-fields { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; }
.field label {
  display: block; font-size: 12px; color: var(--text-muted);
  margin-bottom: 4px;
}
.form-input {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--bg);
  color: var(--text); font-size: 13px;
}
.form-input:focus { border-color: var(--accent); outline: none; }

.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.btn-cancel {
  background: transparent; border: 1px solid var(--border);
  color: var(--text); padding: 8px 16px; border-radius: var(--radius);
  font-size: 13px; cursor: pointer;
}
.btn-cancel:hover { background: var(--bg-hover); }
.btn-confirm {
  background: var(--accent); border: 1px solid var(--accent);
  color: #fff; padding: 8px 16px; border-radius: var(--radius);
  font-size: 13px; cursor: pointer; font-weight: 500;
}
.btn-confirm:hover:not(:disabled) { opacity: 0.9; }
.btn-confirm:disabled { opacity: 0.5; cursor: not-allowed; }

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
