import { defineStore } from 'pinia'
import { useEditorStore } from './editor.js'

// ── Toast 队列（模块级闭包，避免 Pinia 深度代理） ──
const MAX_VISIBLE_TOASTS = 5
let _toastIdCounter = 0
// 单一下时器：始终只对队首 toast 倒计时
let _timer = null        // setTimeout 句柄
let _timerStartTime = 0  // 当前倒计时开始时间戳
let _timerRemaining = 0  // 当前倒计时剩余毫秒
let _timerTotal = 0      // 当前队首 toast 的总时长
let _paused = false      // 是否被用户交互暂停
let _rafId = null        // requestAnimationFrame 句柄

export const useUiStore = defineStore('ui', {
  state: () => ({
    // Toast 队列（内部无上限，UI 最多显示 MAX_VISIBLE_TOASTS 条）
    toasts: [],
    // 队首 toast 倒计时进度（1 → 0）
    headProgress: 1,
    // 上下文菜单
    contextMenu: { visible: false, x: 0, y: 0, target: null, idx: null },
    // Modal 状态
    batchModalOpen: false,
    // C 代码预览
    ccodePreview: {
      open: false,
      headerCode: '', headerFilename: '',
      sourceCode: '', sourceFilename: '',
    },
    // 视图状态
    layoutViewMode: false,
    selectedSignalName: null,
    // 主题
    theme: localStorage.getItem('canmatrix_theme') || 'dark',
    // 日志面板
    showLogPanel: false,
    // 导出拦截时自动展开 DataErrorList
    expandDataErrors: false,
    // 列可见性 + 列宽（SignalTable）
    hiddenColumns: JSON.parse(localStorage.getItem('canmatrix_hidden_cols') || '[]'),
    columnWidths: JSON.parse(localStorage.getItem('canmatrix_col_widths') || '{}'),
    // 中间区域 Tab 状态
    centerTab: 'signals',  // 'signals' | 'messages' | 'valtables'
    // 列可见性 + 列宽（MessageTable，独立 key 前缀 msg_）
    msgHiddenColumns: JSON.parse(localStorage.getItem('canmatrix_msg_hidden_cols') || '[]'),
    msgColumnWidths: JSON.parse(localStorage.getItem('canmatrix_msg_col_widths') || '{}'),
    // 列可见性 + 列宽（ValueTableList，独立 key 前缀 vt_）
    vtHiddenColumns: JSON.parse(localStorage.getItem('canmatrix_vt_hidden_cols') || '[]'),
    vtColumnWidths: JSON.parse(localStorage.getItem('canmatrix_vt_col_widths') || '{}'),
    // 值描述表选中状态 + 外部跳转焦点
    selectedVtName: null,
    valueTableFocusName: '',
    // 排序偏好（所有文件共享，localStorage 持久化）
    signalSortField: localStorage.getItem('canmatrix_sig_sort_field') || 'start_bit',
    signalSortDir: localStorage.getItem('canmatrix_sig_sort_dir') || 'asc',
    msgSortField: localStorage.getItem('canmatrix_msg_sort_field') || 'id',
    msgSortDir: localStorage.getItem('canmatrix_msg_sort_dir') || 'asc',
    vtSortField: localStorage.getItem('canmatrix_vt_sort_field') || 'name',
    vtSortDir: localStorage.getItem('canmatrix_vt_sort_dir') || 'asc',
  }),

  getters: {
    /** UI 层只渲染最老的 MAX_VISIBLE_TOASTS 条，队首始终可见 */
    visibleToasts(state) {
      return state.toasts.slice(0, MAX_VISIBLE_TOASTS)
    },
  },

  actions: {
    // ── Toast 队列（严格 FIFO，单一下时器，队列不限） ──
    showToast(text, isError = false) {
      const id = ++_toastIdCounter
      const duration = isError ? 5000 : 3000
      this.toasts.push({ id, text, isError, duration })
      // 队列为空时新增，启动倒计时
      if (this.toasts.length === 1) this._scheduleHead()
      return id
    },

    /** @internal 对队首 toast 启动倒计时
     *  注意：_scheduleHead 总是在 _paused === false 时被调用：
     *  - 新 toast 入队且队列为空时（无鼠标交互）
     *  - _popHead 自动触发时（队首到期才触发，而到期意味着未悬停——悬停会暂停计时器）
     *  - removeToast 手动关闭队首时（先显式 _paused = false） */
    _scheduleHead() {
      this._clearTimer()
      const head = this.toasts[0]
      if (!head) return
      _timerTotal = head.duration
      _timerRemaining = head.duration
      _paused = false
      this.headProgress = 1
      this._startTimer()
    },

    /** @internal 以 _timerRemaining 启动 setTimeout */
    _startTimer() {
      this._clearTimer()
      if (_timerRemaining <= 0 || !this.toasts.length) return
      _timerStartTime = Date.now()
      _timer = setTimeout(() => {
        _timer = null
        this._stopRaf()
        this._popHead()
      }, _timerRemaining)
      this._startRaf()
    },

    /** @internal 清除当前 setTimeout */
    _clearTimer() {
      if (_timer) { clearTimeout(_timer); _timer = null }
      this._stopRaf()
    },

    /** @internal 启动 RAF 循环更新进度 */
    _startRaf() {
      this._stopRaf()
      const tick = () => {
        if (!_timer) return
        const elapsed = Date.now() - _timerStartTime
        const remaining = Math.max(0, _timerRemaining - elapsed)
        this.headProgress = _timerTotal > 0 ? remaining / _timerTotal : 0
        _rafId = requestAnimationFrame(tick)
      }
      _rafId = requestAnimationFrame(tick)
    },

    /** @internal 停止 RAF */
    _stopRaf() {
      if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null }
    },

    /** @internal 移除队首并启动下一个 */
    _popHead() {
      this.toasts.shift()
      if (this.toasts.length > 0) {
        this._scheduleHead()
      }
    },

    /** 重置倒计时（鼠标悬停 / 页面失焦时调用）
     *  设计说明：页面失焦时调用 resetCountdown 是有意为之——
     *  用户返回页面后获得完整倒计时时间，不会因离开期间悄悄消耗而错过 toast。
     *  请勿改为「暂停并保留剩余时间」。 */
    resetCountdown() {
      if (!this.toasts.length) return
      this._clearTimer()
      _timerRemaining = _timerTotal
      _paused = true
      this.headProgress = 1
    },

    /** 恢复倒计时（鼠标移开 / 页面获焦时调用） */
    resumeCountdown() {
      if (!_paused || !this.toasts.length) return
      _paused = false
      this._startTimer()
    },

    /** 手动移除指定 toast */
    removeToast(id) {
      const wasHead = this.toasts.length > 0 && this.toasts[0].id === id
      this.toasts = this.toasts.filter(t => t.id !== id)
      if (wasHead) {
        // 队首被移除，启动下一个
        if (this.toasts.length > 0) this._scheduleHead()
        else this._clearTimer()
      }
    },

    /** 兼容旧 API：清空所有 toast */
    hideToast() {
      this._clearTimer()
      _paused = false
      this.headProgress = 1
      this.toasts = []
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
      this.selectedSignalName = null
    },

    // ── Tab 切换 ──
    switchCenterTab(tab) {
      this.centerTab = tab
    },

    // ── 列可见性（SignalTable） ──
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

    // ── 列可见性（MessageTable） ──
    toggleMsgColumnVisibility(key) {
      const idx = this.msgHiddenColumns.indexOf(key)
      if (idx >= 0) this.msgHiddenColumns.splice(idx, 1)
      else this.msgHiddenColumns.push(key)
      localStorage.setItem('canmatrix_msg_hidden_cols', JSON.stringify(this.msgHiddenColumns))
    },
    isMsgColumnVisible(key) {
      return !this.msgHiddenColumns.includes(key)
    },
    resetMsgColumnVisibility() {
      this.msgHiddenColumns = []
      localStorage.setItem('canmatrix_msg_hidden_cols', '[]')
    },
    // ── 列宽（MessageTable） ──
    setMsgColumnWidths(widths) {
      this.msgColumnWidths = widths
      localStorage.setItem('canmatrix_msg_col_widths', JSON.stringify(widths))
    },
    getMsgColumnWidth(key, defaultPct) {
      return this.msgColumnWidths[key] ?? defaultPct
    },
    resetMsgColumnWidths() {
      this.msgColumnWidths = {}
      localStorage.setItem('canmatrix_msg_col_widths', '{}')
    },

    // ── 列可见性（ValueTableList） ──
    toggleVtColumnVisibility(key) {
      const idx = this.vtHiddenColumns.indexOf(key)
      if (idx >= 0) this.vtHiddenColumns.splice(idx, 1)
      else this.vtHiddenColumns.push(key)
      localStorage.setItem('canmatrix_vt_hidden_cols', JSON.stringify(this.vtHiddenColumns))
    },
    isVtColumnVisible(key) {
      return !this.vtHiddenColumns.includes(key)
    },
    resetVtColumnVisibility() {
      this.vtHiddenColumns = []
      localStorage.setItem('canmatrix_vt_hidden_cols', '[]')
    },
    // ── 列宽（ValueTableList） ──
    setVtColumnWidths(widths) {
      this.vtColumnWidths = widths
      localStorage.setItem('canmatrix_vt_col_widths', JSON.stringify(widths))
    },
    getVtColumnWidth(key, defaultPct) {
      return this.vtColumnWidths[key] ?? defaultPct
    },
    resetVtColumnWidths() {
      this.vtColumnWidths = {}
      localStorage.setItem('canmatrix_vt_col_widths', '{}')
    },

    setLoading(val) {
      useEditorStore().isLoading = val
    },

    openCcodePreview({ headerCode, headerFilename, sourceCode, sourceFilename }) {
      this.ccodePreview = {
        open: true,
        headerCode, headerFilename,
        sourceCode, sourceFilename,
      }
    },
    closeCcodePreview() {
      this.ccodePreview.open = false
    },

    // ── 排序偏好 ──
    setSignalSort(field, dir) {
      this.signalSortField = field
      this.signalSortDir = dir
      localStorage.setItem('canmatrix_sig_sort_field', field)
      localStorage.setItem('canmatrix_sig_sort_dir', dir)
    },
    setMsgSort(field, dir) {
      this.msgSortField = field
      this.msgSortDir = dir
      localStorage.setItem('canmatrix_msg_sort_field', field)
      localStorage.setItem('canmatrix_msg_sort_dir', dir)
    },
    setVtSort(field, dir) {
      this.vtSortField = field
      this.vtSortDir = dir
      localStorage.setItem('canmatrix_vt_sort_field', field)
      localStorage.setItem('canmatrix_vt_sort_dir', dir)
    },
  },
})
