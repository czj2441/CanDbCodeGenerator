import { defineStore } from 'pinia'

export const useUiStore = defineStore('ui', {
  state: () => ({
    // Toast 提示
    toast: { text: '', isError: false, visible: false },
    // 上下文菜单
    contextMenu: { visible: false, x: 0, y: 0, target: null, idx: null },
    // Modal 状态
    batchModalOpen: false,
    historyModalOpen: false,
    newConfirmOpen: false,
    // 主题与语言
    theme: localStorage.getItem('canmatrix_theme') || 'dark',
    locale: localStorage.getItem('canmatrix_locale') || 'zh',
    // 日志面板
    showLogPanel: false,
    logEntries: [],
  }),

  actions: {
    showToast(text, isError = false) {
      this.toast = { text, isError, visible: true }
      setTimeout(() => { this.toast.visible = false }, 2000)
    },

    hideToast() {
      this.toast.visible = false
    },

    showContextMenu(x, y, target, idx) {
      this.contextMenu = { visible: true, x, y, target, idx }
    },

    hideContextMenu() {
      this.contextMenu.visible = false
    },

    setTheme(theme) {
      this.theme = theme
      localStorage.setItem('canmatrix_theme', theme)
      document.documentElement.setAttribute('data-theme', theme)
    },

    toggleTheme() {
      const next = this.theme === 'dark' ? 'light' : 'dark'
      this.setTheme(next)
    },

    setLocale(locale) {
      this.locale = locale
      localStorage.setItem('canmatrix_locale', locale)
      location.reload()
    },

    toggleLocale() {
      const next = this.locale === 'zh' ? 'en' : 'zh'
      this.setLocale(next)
    },

    addLogEntry(type, description) {
      const now = new Date()
      const time = now.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      this.logEntries.unshift({ time, type, description })
      if (this.logEntries.length > 200) {
        this.logEntries.pop()
      }
    },

    clearLog() {
      this.logEntries = []
    },
  },
})
