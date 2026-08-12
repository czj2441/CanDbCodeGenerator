<template>
  <div class="login-page">
    <div class="login-card">
      <h2 class="login-title">CanMatrix Editor</h2>
      <p class="login-subtitle">请登录以继续</p>

      <form @submit.prevent="handleLogin" class="login-form">
        <div class="field">
          <label for="username">用户名</label>
          <input id="username" v-model="username" type="text"
                 placeholder="请输入用户名" autocomplete="username"
                 autofocus :disabled="loading" />
        </div>
        <div class="field">
          <label for="password">密码</label>
          <input id="password" v-model="password" type="password"
                 placeholder="请输入密码" autocomplete="current-password"
                 :disabled="loading" />
        </div>

        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

        <button type="submit" class="login-btn" :disabled="loading || !username || !password">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '登录中...' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useAuthStore } from '../stores/authStore.js'

const emit = defineEmits(['login-success'])

const authStore = useAuthStore()
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin() {
  if (!username.value || !password.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await authStore.login(username.value, password.value)
    emit('login-success', data)
  } catch (e) {
    errorMsg.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: var(--bg);
}

.login-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 40px;
  width: 380px;
  box-shadow: var(--shadow);
}

.login-title {
  text-align: center;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}

.login-subtitle {
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
  margin-bottom: 28px;
}

.login-form {
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

.login-btn {
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

.login-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.login-btn:disabled {
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
