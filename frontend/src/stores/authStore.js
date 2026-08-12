/**
 * authStore — 用户认证状态管理。
 *
 * 管理登录/登出、Token 存储、用户角色、管理员操作。
 * Token 存储在 localStorage（跨标签页共享），与 session_id（sessionStorage）不冲突。
 */
import { defineStore } from 'pinia'

const TOKEN_KEY = 'canmatrix_auth_token'

function _apiBase() {
  // 与 ws-client 保持一致：开发时同域，生产时也同域
  return ''
}

async function _fetch(path, options = {}) {
  const token = localStorage.getItem(TOKEN_KEY) || ''
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const resp = await fetch(`${_apiBase()}${path}`, { ...options, headers })
  return resp
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    username: '',
    role: '',              // 'admin' | 'user' | ''
    authMustChangePassword: false,
  }),

  getters: {
    isLoggedIn: (state) => !!state.token,
    isAdmin: (state) => state.role === 'admin',
  },

  actions: {
    // ── 认证流程 ──

    async login(username, password) {
      const resp = await _fetch('/api/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      const json = await resp.json()
      if (!json.success) {
        throw new Error(json.error || '登录失败')
      }
      this.setAuth(json.data.token, json.data.username, json.data.role)
      this.authMustChangePassword = json.data.must_change_password || false
      return json.data
    },

    async logout() {
      try {
        await _fetch('/api/logout', { method: 'POST' })
      } catch {
        // 即使后端不可达也要清理本地状态
      }
      this.clearAuth()
    },

    async checkSession() {
      if (!this.token) return false
      try {
        const resp = await _fetch('/api/me')
        const json = await resp.json()
        if (json.success) {
          this.username = json.data.username
          this.role = json.data.role
          this.authMustChangePassword = json.data.must_change_password || false
          return true
        }
      } catch {
        // 网络错误
      }
      this.clearAuth()
      return false
    },

    async changePassword(oldPassword, newPassword) {
      const resp = await _fetch('/api/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      })
      const json = await resp.json()
      if (!json.success) {
        throw new Error(json.error || '修改密码失败')
      }
      // 更新 token
      if (json.data.token) {
        this.token = json.data.token
        localStorage.setItem(TOKEN_KEY, this.token)
      }
      this.authMustChangePassword = false
    },

    setAuth(token, username, role) {
      this.token = token
      this.username = username
      this.role = role
      localStorage.setItem(TOKEN_KEY, token)
    },

    clearAuth() {
      this.token = ''
      this.username = ''
      this.role = ''
      this.authMustChangePassword = false
      localStorage.removeItem(TOKEN_KEY)
    },

    // ── 管理员操作 ──

    async fetchUsers() {
      const resp = await _fetch('/api/admin/users')
      const json = await resp.json()
      if (!json.success) throw new Error(json.error || '获取用户列表失败')
      return json.data
    },

    async createUser(username, password, role) {
      const resp = await _fetch('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify({ username, password, role }),
      })
      const json = await resp.json()
      if (!json.success) throw new Error(json.error || '创建用户失败')
      return json.data
    },

    async deleteUser(username) {
      const resp = await _fetch(`/api/admin/users/${encodeURIComponent(username)}`, {
        method: 'DELETE',
      })
      const json = await resp.json()
      if (!json.success) {
        const err = new Error(json.error || '删除用户失败')
        err.files = json.details?.files || []
        throw err
      }
      return json.data
    },

    async updateUserRole(username, role) {
      const resp = await _fetch(`/api/admin/users/${encodeURIComponent(username)}/role`, {
        method: 'PUT',
        body: JSON.stringify({ role }),
      })
      const json = await resp.json()
      if (!json.success) throw new Error(json.error || '修改角色失败')
      return json.data
    },

    async resetUserPassword(username, password) {
      const resp = await _fetch(`/api/admin/users/${encodeURIComponent(username)}/password`, {
        method: 'PUT',
        body: JSON.stringify({ password }),
      })
      const json = await resp.json()
      if (!json.success) throw new Error(json.error || '重置密码失败')
      return json.data
    },

    async changeFileOwner(fileName, newOwner) {
      const resp = await _fetch('/api/admin/file-permission', {
        method: 'PUT',
        body: JSON.stringify({ file_name: fileName, new_owner: newOwner }),
      })
      const json = await resp.json()
      if (!json.success) throw new Error(json.error || '转移所有权失败')
      return json.data
    },

    async getFilePermission(fileName) {
      const resp = await _fetch(`/api/file-permission?file=${encodeURIComponent(fileName)}`)
      const json = await resp.json()
      if (!json.success) throw new Error(json.error || '获取文件权限失败')
      return json.data
    },
  },
})
