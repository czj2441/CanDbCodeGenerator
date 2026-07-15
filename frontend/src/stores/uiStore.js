import { defineStore } from 'pinia'
import { useEditorStore } from './editor.js'

export const useUiStore = defineStore('ui', {
  state: () => ({
    // Toast 提示
    toast: { text: '', isError: false, visible: false },
    _toastTimer: null,
    // 上下文菜单
    contextMenu: { visible: false, x: 0, y: 0, target: null, idx: null },
    // Modal 状态
    batchModalOpen: false,
    newConfirmOpen: false,
    // 视图状态
    layoutViewMode: false,
    selectedSignalUuid: null,
    // 主题
    theme: localStorage.getItem('canmatrix_theme') || 'dark',
    // 日志面板
    showLogPanel: false,
    // 列可见性 + 列宽
    hiddenColumns: JSON.parse(localStorage.getItem('canmatrix_hidden_cols') || '[]'),
    columnWidths: JSON.parse(localStorage.getItem('canmatrix_col_widths') || '{}'),
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
      if (this.layoutViewMode) {
        this.showLogPanel = true
      }
    },

    selectLayoutSignal(uuid) {
      this.selectedSignalUuid = this.selectedSignalUuid === uuid ? null : uuid
    },

    // ── 列可见性 ──
    toggleColumnVisibility(key) {
      const idx = this.hiddenColumns.indexOf(key)
      if (idx >= 0) this.hiddenColumns.splice(idx, 1)
      else this.hiddenColumns.push(key)
      localStorage.setItem('canmatrix_hidden_cols', JSON.stringify(this.hiddenColumns))
    },
    isColumnVisible(key) {
      return !this.hiddenColumns.includes(key)
    },
    resetColumnVisibility() {
      this.hiddenColumns = []
      localStorage.setItem('canmatrix_hidden_cols', '[]')
    },
    // ── 列宽（百分比） ──
    setColumnWidths(widths) {
      this.columnWidths = widths
      localStorage.setItem('canmatrix_col_widths', JSON.stringify(widths))
    },
    getColumnWidth(key, defaultPct) {
      return this.columnWidths[key] ?? defaultPct
    },
    resetColumnWidths() {
      this.columnWidths = {}
      localStorage.setItem('canmatrix_col_widths', '{}')
    },

    setLoading(val) {
      useEditorStore().isLoading = val
    },
  },
})
