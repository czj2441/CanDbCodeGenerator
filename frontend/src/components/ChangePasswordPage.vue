<template>
  <div class="chpwd-page">
    <div class="chpwd-card">
      <h2 class="chpwd-title">修改密码</h2>
      <p class="chpwd-subtitle">首次登录或密码已被重置，请设置新密码</p>

      <form @submit.prevent="handleChange" class="chpwd-form">
        <div class="field">
          <label for="oldPwd">当前密码</label>
          <input id="oldPwd" v-model="oldPwd" type="password"
                 placeholder="请输入当前密码" autocomplete="current-password"
                 autofocus :disabled="loading" />
        </div>
        <div class="field">
          <label for="newPwd">新密码</label>
          <input id="newPwd" v-model="newPwd" type="password"
                 placeholder="至少 4 位" autocomplete="new-password"
                 :disabled="loading" />
        </div>
        <div class="field">
          <label for="confirmPwd">确认新密码</label>
          <input id="confirmPwd" v-model="confirmPwd" type="password"
                 placeholder="再次输入新密码" autocomplete="new-password"
                 :disabled="loading" />
        </div>

        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

        <button type="submit" class="chpwd-btn" :disabled="loading || !canSubmit">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '修改中...' : '确认修改' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/authStore.js'

const emit = defineEmits(['password-changed'])

const authStore = useAuthStore()
const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const loading = ref(false)
const errorMsg = ref('')

const canSubmit = computed(() =>
  oldPwd.value && newPwd.value.length >= 4 && newPwd.value === confirmPwd.value
)

async function handleChange() {
  if (!canSubmit.value) return
  if (newPwd.value !== confirmPwd.value) {
    errorMsg.value = '两次输入的密码不一致'
    return
  }
  if (newPwd.value.length < 4) {
    errorMsg.value = '新密码长度不能少于 4 位'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    await authStore.changePassword(oldPwd.value, newPwd.value)
    emit('password-changed')
  } catch (e) {
    errorMsg.value = e.message || '修改密码失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.chpwd-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: var(--bg);
}

.chpwd-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 40px;
  width: 400px;
  box-shadow: var(--shadow);
}

.chpwd-title {
  text-align: center;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}

.chpwd-subtitle {
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
  margin-bottom: 28px;
}

.chpwd-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-dim);
}

.field input {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  outline: none;
  transition: border-color var(--transition);
}

.field input:focus {
  border-color: var(--accent-dim);
}

.field input:disabled {
  opacity: 0.6;
}

.error-msg {
  color: var(--danger);
  font-size: 12px;
  padding: 6px 10px;
  background: color-mix(in oklch, var(--danger) 10%, transparent);
  border-radius: var(--radius-sm);
}

.chpwd-btn {
  padding: 10px;
  border: none;
  border-radius: var(--radius);
  background: var(--accent);
  color: oklch(0.15 0.005 260);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity var(--transition);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.chpwd-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.chpwd-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
