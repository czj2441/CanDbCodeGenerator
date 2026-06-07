import { defineStore } from 'pinia'

export const useUiStore = defineStore('ui', {
  state: () => ({
    // Toast 提示
    toast: { text: '', isError: false, visible: false },
    _toastTimer: null,
    // 上下文菜单
    contextMenu: { visible: false, x: 0, y: 0, target: null, idx: null },
    // Modal 状态
    batchModalOpen: false,
    historyModalOpen: false,
    newConfirmOpen: false,
    // 视图状态
    layoutViewMode: false,
    selectedSignalUuid: null,
    // 主题与语言
    theme: localStorage.getItem('canmatrix_theme') || 'dark',
    locale: localStorage.getItem('canmatrix_locale') || 'zh',
    // 日志面板
    showLogPanel: false,
  }),

  actions: {
    showToast(text, isError = false) {
      // 清除之前的定时器，避免快速连续调用时 Toast 被意外关闭
      if (this._toastTimer) clearTimeout(this._toastTimer)
      this.toast = { text, isError, visible: true }
      this._toastTimer = setTimeout(() => {
        this.toast.visible = false
        this._toastTimer = null
      }, 2000)
    },

    hideToast() {
      if (this._toastTimer) clearTimeout(this._toastTimer)
      this._toastTimer = null
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

    toggleLayoutView() {
      this.layoutViewMode = !this.layoutViewMode
      this.selectedSignalUuid = null
    },

    selectLayoutSignal(uuid) {
      this.selectedSignalUuid = this.selectedSignalUuid === uuid ? null : uuid
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
  },
})
