import { defineStore } from 'pinia'
import { setSessionId, getSessionId } from '../api/client.js'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { WsSyncClient, ApiError as WsApiError, WsFrontendDiag } from '../utils/ws-client.js'

/**
 * 将后端校验错误翻译为 i18n 文本。
 * 若 error_code 对应的翻译不存在，则 fallback 到原始 e.message。
 */
function _translateError(e) {
  const errorCode = e.details?.error_code
  if (!errorCode) return e.message
  const i18nKey = `toast.validation.${errorCode}`
  const translated = t(i18nKey, e.details || {})
  return translated !== i18nKey ? translated : e.message
}

// ── WS 防抖 Map（信号编辑 300ms 合并）──
const PENDING_EDITS = new Map()  // key → { timer, reject }

// 暴露到全局便于调试
if (typeof window !== 'undefined') {
  window.__pendingEdits__ = PENDING_EDITS
}

// ── 信号位布局计算（与后端 models.py 保持一致） ──

/**
 * 计算信号占用的 bit 位置集合
 * @param {number} startBit - 起始位
 * @param {number} length - 信号长度
 * @param {string} byteOrder - 'motorola' | 'intel'
 * @returns {Set<number>} 占用的 bit 位置
 */
function getSignalBits(startBit, length, byteOrder) {
  const bits = new Set()
  const bo = (byteOrder || 'motorola').toLowerCase()
  if (bo === 'motorola') {
    let current = startBit
    for (let i = 0; i < length; i++) {
      bits.add(current)
      if (current % 8 === 0) {
        current += 15 // 回绕到下一字节 MSB
      } else {
        current -= 1  // 字节内向低位递减
      }
    }
  } else {
    for (let i = 0; i < length; i++) {
      bits.add(startBit + i)
    }
  }
  return bits
}

/**
 * 在报文中寻找第一个足够大的空闲区间
 * @param {Array} signals - 当前报文的信号列表
 * @param {number} dlc - 报文 DLC
 * @param {number} length - 新信号长度
 * @param {string} byteOrder - 新信号字节序
 * @returns {number|null} 推荐的 start_bit，无空闲位置返回 null
 */
function findNextAvailableStartBit(signals, dlc, length, byteOrder) {
  const maxBits = dlc * 8
  if (length > maxBits) return null

  const used = new Set()
  for (const s of signals) {
    for (const b of getSignalBits(s.start_bit, s.length, s.byte_order)) {
      used.add(b)
    }
  }

  // Intel: 从 bit 0 开始连续填充
  if (byteOrder !== 'motorola') {
    for (let candidate = 0; candidate < maxBits; candidate++) {
      const candidateBits = getSignalBits(candidate, length, byteOrder)
      let valid = true
      for (const b of candidateBits) {
        if (b < 0 || b >= maxBits || used.has(b)) {
          valid = false
          break
        }
      }
      if (valid) return candidate
    }
    return null
  }

  // Motorola: 三轮扫描策略
  // 第一轮：按字节遍历，优先尝试字节内紧凑位置（不跨字节）
  // 例: length=2 时顺序为 7,5,3,1,15,13,11,9,23,...
  for (let byteIdx = 0; byteIdx < dlc; byteIdx++) {
    const byteBase = byteIdx * 8
    for (let offset = 7; offset >= length - 1 && offset >= 0; offset -= length) {
      const candidate = byteBase + offset
      if (candidate >= maxBits) continue
      const candidateBits = getSignalBits(candidate, length, byteOrder)
      let valid = true
      for (const b of candidateBits) {
        if (b < 0 || b >= maxBits || used.has(b)) {
          valid = false
          break
        }
      }
      if (valid) return candidate
    }
  }

  // 第二轮：优先尝试字节边界 MSB（7,15,23...），长信号通常从此开始
  for (let candidate = 7; candidate < maxBits; candidate += 8) {
    const candidateBits = getSignalBits(candidate, length, byteOrder)
    let valid = true
    for (const b of candidateBits) {
      if (b < 0 || b >= maxBits || used.has(b)) {
        valid = false
        break
      }
    }
    if (valid) return candidate
  }

  // 第三轮：全位扫描兜底（与后端保持一致），确保不遗漏任何有效位置
  for (let candidate = 0; candidate < maxBits; candidate++) {
    const candidateBits = getSignalBits(candidate, length, byteOrder)
    let valid = true
    for (const b of candidateBits) {
      if (b < 0 || b >= maxBits || used.has(b)) {
        valid = false
        break
      }
    }
    if (valid) return candidate
  }
  return null
}

export const useEditorStore = defineStore('editor', {
  state: () => ({
    // ── 核心数据 ──
    messages: [],
    selectedMsgId: null,
    messageCache: {},

    // ── 会话与文件 ──
    currentFileName: '',

    // ── 运行时状态 ──
    isLoading: false,
    apiStatus: 'connecting',
    _localDirty: false,        // 前端本地自上次 save/load 后是否有过编辑（仅 beforeunload 使用）
    backendDirty: false,        // 后端 db.modified —— 是否还有未落盘数据（从 /api/status 同步）
    signalErrors: [],
    _healthFailCount: 0,
    _hasBeenConnected: false,  // 是否曾成功连接过后端（防止初始加载闪遮罩）
    _defaultSignalLength: 8,  // 新信号默认 length；用户修改某信号 length 后自动同步为该值
    logEntries: [],

    // ── WebSocket 状态 ──
    _dataVersion: 0,
    _wsConnected: false,
    _wsClient: null,
    _wsIntentionalClose: false,
    _healthTimer: null,          // 健康检查定时器（2s 间隔）

    // ── 剪贴板 ──
    clipboard: null,

    // ── 撤销/重做计数器（从后端同步） ──
    undoCount: 0,
    redoCount: 0,
  }),

  getters: {
    selectedMessage(state) {
      return state.messageCache[state.selectedMsgId] || null
    },
    messageCount(state) {
      return state.messages.length
    },
    signalCount(state) {
      return state.messages.reduce((sum, m) => sum + (m.signal_count || 0), 0)
    },
    // ✅ 使用响应式计数器，确保按钮状态正确更新
    canUndo: (state) => state.undoCount > 0,
    canRedo: (state) => state.redoCount > 0,
  },

  actions: {
    // ═══════════════════════════════════════════
    // 区域 WS：WebSocket 连接管理 + 消息分发
    // ═══════════════════════════════════════════

    /**
     * 进入编辑器模式时调用（openFile / createNewFile 成功后）
     */
    startEditorSync() {
      this._connectWebSocket()
      // 启动健康检查定时器（2s 间隔）
      if (this._healthTimer) clearInterval(this._healthTimer)
      this._healthTimer = setInterval(() => this.checkApiHealth(), 2000)
    },

    /**
     * 离开编辑器模式时调用（goBack / releaseSession 前）
     */
    stopEditorSync() {
      this._wsIntentionalClose = true
      if (this._healthTimer) { clearInterval(this._healthTimer); this._healthTimer = null }
      if (this._wsClient) {
        this._wsClient.disconnect()
        this._wsClient = null
      }
      this._wsConnected = false
    },

    /**
     * 建立 WebSocket 连接
     */
    _connectWebSocket() {
      if (this._wsClient?.connected) return

      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsPort = parseInt(location.port) + 1
      const wsUrl = `${protocol}//${location.hostname}:${wsPort}/ws`

      this._wsIntentionalClose = false
      this._dataVersion = 0

      this._wsClient = new WsSyncClient({
        url: wsUrl,
        sessionId: getSessionId() || '',
        onMessage: (msg) => { this._applyWsMessage(msg) },
        onStatusChange: (status) => {
          if (status === 'connected') {
            this._wsConnected = true
          } else if (status === 'disconnected') {
            this._wsConnected = false
          }
        }
      })
      this._wsClient.connect()
    },

    /**
     * WS 请求助手：自动注入 session_id，返回 Promise。
     * @param {string} type 消息类型
     * @param {object} data 消息数据（session_id 自动注入）
     * @returns {Promise<object>}
     */
    _wsRequest(type, data = {}) {
      if (!this._wsClient) {
        return Promise.reject(new Error('WebSocket not connected'))
      }
      return this._wsClient.request(type, {
        ...data,
        session_id: getSessionId() || '',
      })
    },

    /**
     * 等待 WS 连接就绪（最多 timeout ms）。
     * 如果已连接则立即返回，否则轮询等待。
     */
    _waitForWsReady(timeout = 5000) {
      if (this._wsClient?.connected) return Promise.resolve()
      return new Promise((resolve, reject) => {
        const start = Date.now()
        const check = () => {
          if (this._wsClient?.connected) {
            resolve()
          } else if (Date.now() - start > timeout) {
            reject(new Error('WS connection timeout'))
          } else {
            setTimeout(check, 100)
          }
        }
        setTimeout(check, 50)
      })
    },

    /**
     * 核心：WebSocket 广播消息分发
     * 版本号去重 + 按类型局部 patch / 全量替换
     */
    _applyWsMessage(msg) {
      const stopTimer = WsFrontendDiag.timeStart('apply_msg')

      // 版本号去重
      if (msg.data_version && msg.data_version <= this._dataVersion) {
        WsFrontendDiag.count('msg_dropped')
        stopTimer()
        return
      }
      if (msg.data_version) {
        this._dataVersion = msg.data_version
      }
      WsFrontendDiag.count('msg_received')

      switch (msg.type) {

        // ── 全量快照 ──
        case 'full_sync': {
          WsFrontendDiag.count('full_sync')
          const d = msg.data

          // WS 断线期间锁可能被抢
          if (d.lock_status === 'lost') {
            this._applyWsMessage({
              type: 'lock_stolen',
              data: { victim_session_id: getSessionId() }
            })
            break
          }

          this.messages = d.messages || []
          if (d.status) {
            this.backendDirty = d.status.modified || false
            this.undoCount = d.status.undo_count || 0
            this.redoCount = d.status.redo_count || 0
          }
          // 检查 selectedMsgId 是否仍存在于新数据中
          if (this.selectedMsgId != null &&
              !this.messages.some(m => m.id === this.selectedMsgId)) {
            this.selectedMsgId = null
            this.messageCache = {}
            this.signalErrors = []
          }
          break
        }

        // ── 信号更新：按 uuid 原地替换 ──
        case 'signal_updated': {
          WsFrontendDiag.count('signal_updated')
          const { msg_id, signal } = msg.data
          const cache = this.messageCache[msg_id]
          if (cache) {
            const idx = cache.signals.findIndex(s => s.uuid === signal.uuid)
            if (idx >= 0) {
              cache.signals[idx] = signal
            }
          }
          break
        }

        // ── 信号添加 ──
        case 'signal_added': {
          const { msg_id, signal } = msg.data
          const cache = this.messageCache[msg_id]
          if (cache) {
            cache.signals = [...cache.signals, signal]
          }
          const msgIdx = this.messages.findIndex(m => m.id === msg_id)
          if (msgIdx >= 0) {
            this.messages[msgIdx] = {
              ...this.messages[msgIdx],
              signal_count: cache ? cache.signals.length
                : this.messages[msgIdx].signal_count + 1
            }
          }
          break
        }

        // ── 信号删除 ──
        case 'signal_deleted': {
          const { msg_id, signal_uuid } = msg.data
          const cache = this.messageCache[msg_id]
          if (cache) {
            cache.signals = cache.signals.filter(s => s.uuid !== signal_uuid)
          }
          const msgIdx = this.messages.findIndex(m => m.id === msg_id)
          if (msgIdx >= 0) {
            this.messages[msgIdx] = {
              ...this.messages[msgIdx],
              signal_count: cache ? cache.signals.length
                : Math.max(0, this.messages[msgIdx].signal_count - 1)
            }
          }
          break
        }

        // ── 报文增/改/删 ──
        case 'message_added': {
          this.messages = [...this.messages, msg.data.message]
          break
        }
        case 'message_updated': {
          const m = msg.data.message
          const idx = this.messages.findIndex(x => x.id === m.id)
          if (idx >= 0) {
            this.messages[idx] = { ...this.messages[idx], ...m }
          }
          break
        }
        case 'message_deleted': {
          const deletedId = msg.data.msg_id
          this.messages = this.messages.filter(m => m.id !== deletedId)
          if (this.selectedMsgId === deletedId) {
            this.selectedMsgId = null
            this.signalErrors = []
          }
          delete this.messageCache[deletedId]
          break
        }

        // ── 撤销/重做：广播自带完整数据 ──
        case 'undo_applied':
        case 'redo_applied': {
          if (msg.data.status) {
            this.backendDirty = msg.data.status.modified
            this.undoCount = msg.data.status.undo_count
            this.redoCount = msg.data.status.redo_count
          }
          if (msg.data.messages) {
            this.messages = msg.data.messages
          }
          if (msg.data.message_details) {
            for (const [mid, detail] of Object.entries(msg.data.message_details)) {
              this.messageCache[parseInt(mid)] = detail
            }
          }
          break
        }

        // ── 状态变更 ──
        case 'status_changed': {
          const s = msg.data
          if ('modified' in s) this.backendDirty = s.modified
          if ('undo_count' in s) this.undoCount = s.undo_count
          if ('redo_count' in s) this.redoCount = s.redo_count
          if (s.save_error) {
            useUiStore().showToast(t('toast.autoSaveFailed', { error: s.save_error }), true)
          }
          break
        }

        case 'signal_errors_changed': {
          this.signalErrors = msg.data.errors || []
          break
        }

        // ── 锁被抢占 ──
        case 'lock_stolen': {
          WsFrontendDiag.count('lock_stolen')
          console.warn('[WS] lock stolen, victim:', msg.data?.victim_session_id,
                       msg.data?.stealer_session_id ? ', by: ' + msg.data.stealer_session_id : '')
          this._wsIntentionalClose = true
          // 先清理 pending 请求，再断开连接
          this._wsClient?._cleanupPendingRequests()
          this._wsClient?.disconnect()
          this._wsClient = null
          this._wsConnected = false
          // 清理编辑状态并导航回文件浏览器
          this.messages = []
          this.messageCache = {}
          this.selectedMsgId = null
          this.signalErrors = []
          this.clearUndoStack()
          window.dispatchEvent(new CustomEvent('navigate-browser'))
          useUiStore().showToast(t('toast.noEditPermission'), true)
          break
        }

        case 'pong':
          break
      }

      stopTimer()
    },

    // ═══════════════════════════════════════════
    // 区域 C：撤销/重做（Undo/Redo）- 后端管理
    // ═══════════════════════════════════════════

    /**
     * 执行撤销操作（调用后端 API）
     * API 成功后刷新数据
     * @returns {Promise<void>}
     */
    async undo() {
      try {
        await this._wsRequest('undo')
        // undo_applied 广播已更新 messages + status
        useUiStore().showToast('撤销成功', false)
        this.addLogEntry('undo', '撤销操作')
      } catch (e) {
        console.error('[STORE] undo() failed:', e)
        useUiStore().showToast(e.message || '撤销失败', true)
      }
    },

    /**
     * 执行重做操作（调用后端 API）
     * API 成功后刷新数据
     * @returns {Promise<void>}
     */
    async redo() {
      try {
        await this._wsRequest('redo')
        // redo_applied 广播已更新 messages + status
        useUiStore().showToast('重做成功', false)
        this.addLogEntry('redo', '重做操作')
      } catch (e) {
        console.error('[STORE] redo() failed:', e)
        useUiStore().showToast(e.message || '重做失败', true)
      }
    },

    /**
     * 清空撤销/重做栈（切换会话时调用）
     */
    clearUndoStack() {
      // WS 模式下撤销栈由后端管理，前端仅重置计数器
      this.undoCount = 0
      this.redoCount = 0
    },

    // ═══════════════════════════════════════════
    // 区域 B：会话管理（Session Management）
    // ═══════════════════════════════════════════

    // ═══════════════════════════════════════════
    // 区域 A：数据操作（Data Operations）
    // ═══════════════════════════════════════════

    // ── 报文加载与选择 ──

    /**
     * 手动保存当前会话
     * 调用后端 POST /api/save 立即保存数据到磁盘
     * @returns {Promise<boolean>} 保存是否成功
     */
    async saveSession() {
      try {
        await this._wsRequest('save')
        this._localDirty = false
        return true
      } catch (e) {
        console.error('Failed to save session:', e)
        return false
      }
    },

    /**
     * 加载所有报文列表
     * 如果已选择报文，则同时加载选中报文的详细信息
     * @returns {Promise<void>}
     */
    async loadMessages() {
      try {
        this.messages = await this._wsRequest('get_messages')
        if (this.selectedMsgId != null) {
          await this.loadSelectedMessage()
        }
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 选中报文（乐观更新模式）
     * 立即清空旧缓存让 UI 显示加载中，异步加载报文详情
     * @param {number} id - 报文 ID
     * @returns {Promise<void>}
     */
    async selectMessage(id) {
      this.selectedMsgId = id
      this.messageCache[id] = null
      this.loadSelectedMessage()
    },

    /**
     * 加载选中报文的详细信息（含信号列表）
     * 加载完成后检查信号错误状态
     * @returns {Promise<void>}
     */
    async loadSelectedMessage() {
      if (this.selectedMsgId == null) return
      try {
        this.messageCache[this.selectedMsgId] = await this._wsRequest('get_message', { msg_id: this.selectedMsgId })
        this.loadSignalErrors()
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 加载当前报文的信号错误列表
     * @returns {Promise<void>}
     */
    async loadSignalErrors() {
      if (this.selectedMsgId == null) return
      try {
        const errors = await this._wsRequest('get_signal_errors', { msg_id: this.selectedMsgId })
        this.signalErrors = errors || []
      } catch (_) {
        this.signalErrors = []
      }
    },

    // ── 报文 CRUD ──

    /**
     * 自动修复信号位置（布局视图调用）
     * @param {string} sigUuid - 信号 UUID
     * @param {number} newStartBit - 新的起始位
     * @returns {Promise<void>}
     */
    async autoFixSignal(sigUuid, newStartBit) {
      if (this.selectedMsgId == null) return
      await this.updateSignal(sigUuid, 'start_bit', newStartBit)
    },

    /**
     * 通过布局视图移动信号位置
     * @param {string} sigUuid - 信号 UUID
     * @param {number} newStartBit - 新的起始位
     * @returns {Promise<void>}
     */
    async moveSignalByLayout(sigUuid, newStartBit) {
      await this.updateSignal(sigUuid, 'start_bit', newStartBit)
    },

    /**
     * 通过布局视图调整信号长度
     * @param {string} sigUuid - 信号 UUID
     * @param {number} newLength - 新的长度
     * @returns {Promise<void>}
     */
    async resizeSignalByLayout(sigUuid, newLength) {
      await this.updateSignal(sigUuid, 'length', newLength)
    },

    /**
     * 添加报文（乐观更新模式）
     * 先更新本地状态再发送 API，失败时回滚。
     * 成功后重置 5s 轮询定时器，全量重载由定时器超时触发。
     * @returns {Promise<void>}
     */
    async addMessage() {
      const id = 0x300 + this.messages.length
      const name = `NewMessage${this.messages.length + 1}`

      // 乐观更新
      const newMsg = {
        id, name, dlc: 8, cycle_time: 0, sender: '',
        signal_count: 0, id_hex: `0x${id.toString(16).toUpperCase()}`
      }
      const oldMessages = [...this.messages]
      this.messages.push(newMsg)
      this.messageCache[id] = { id, name, dlc: 8, cycle_time: 0, sender: '', comment: '', signals: [] }
      this.selectedMsgId = id
      this._localDirty = true

      try {
        await this._wsRequest('add_message', {
          message: { id, name, dlc: 8, cycle_time: 0, sender: '', signals: [] }
        })
        useUiStore().showToast(t('toast.messageAdded'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
        this.messages = oldMessages
      }
    },

    /**
     * 删除报文（乐观更新模式）
     * 先更新本地状态再发送 API，失败时回滚。
     * 成功后重置 5s 轮询定时器，全量重载由定时器超时触发。
     * @param {number} id - 报文 ID
     * @returns {Promise<void>}
     */
    async deleteMessage(id) {
      // 乐观更新
      const oldMessages = [...this.messages]
      const oldCache = { ...this.messageCache[id] }
      this.messages = this.messages.filter(m => m.id !== id)
      delete this.messageCache[id]
      if (this.selectedMsgId === id) this.selectedMsgId = null
      this._localDirty = true

      try {
        await this._wsRequest('delete_message', { msg_id: id })
        useUiStore().showToast(t('toast.messageDeleted'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
        this.messages = oldMessages
        this.messageCache[id] = oldCache
      }
    },

    /**
     * 更新报文属性（乐观更新模式）
     * 值变化时先入撤销栈，再更新本地状态，异步发送 API。
     * 成功后重置 5s 轮询定时器，全量重载由定时器超时触发。
     * @param {string} field - 字段名
     * @param {any} value - 新值
     * @returns {Promise<void>}
     */
    async updateMessageField(field, value) {
      if (this.selectedMsgId == null) return
      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return

      const oldValue = msg[field]

      // 乐观更新
      const oldMessages = [...this.messages]
      const oldCache = { ...this.messageCache[this.selectedMsgId] }
      const idx = this.messages.findIndex(m => m.id === this.selectedMsgId)
      if (idx >= 0) {
        this.messages[idx] = { ...this.messages[idx], [field]: value }
      }
      this.messageCache[this.selectedMsgId] = { ...this.messageCache[this.selectedMsgId], [field]: value }
      this._localDirty = true

      const queueKey = `message_${this.selectedMsgId}_${field}`
      // 防抖：取消旧定时器
      const existing = PENDING_EDITS.get(queueKey)
      if (existing) clearTimeout(existing.timer)

      return new Promise((resolve, reject) => {
        const timer = setTimeout(async () => {
          PENDING_EDITS.delete(queueKey)
          try {
            await this._wsRequest('edit_message', {
              msg_id: this.selectedMsgId,
              fields: { [field]: value }
            })
            resolve()
          } catch (e) {
            if (!e.message?.includes?.('Connection lost')) {
              useUiStore().showToast(_translateError(e), true)
            }
            // 回滚
            this.messages = oldMessages
            this.messageCache[this.selectedMsgId] = oldCache
            reject(e)
          }
        }, 300)
        PENDING_EDITS.set(queueKey, { timer, reject })
      })
    },

    /**
     * 添加信号（乐观更新 + client UUID 替换）
     * 使用前端生成的临时 UUID 乐观更新 UI，API 成功后替换为后端真实 UUID。
     * 成功后重置 5s 轮询定时器，全量重载由定时器超时触发。
     * @param {Object} signalData - 信号初始数据
     * @returns {Promise<void>}
     */
    async addSignal(signalData) {
      if (this.selectedMsgId == null) return
      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return

      // 自动顺延
      let defaultStartBit = 0
      if (signalData?.start_bit == null) {
        const newLength = signalData?.length ?? this._defaultSignalLength
        const newByteOrder = signalData?.byte_order ?? 'motorola'
        const available = findNextAvailableStartBit(msg.signals, msg.dlc, newLength, newByteOrder)
        if (available != null) defaultStartBit = available
      }

      const fullData = {
        name: 'NewSignal', start_bit: defaultStartBit, length: this._defaultSignalLength,
        byte_order: 'motorola', factor: 1.0, offset: 0.0, min_val: 0.0, max_val: 0.0,
        unit: '', comment: '', ...signalData,
      }
      const clientUuid = crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(16).slice(2, 10)
      const newSig = { uuid: clientUuid, ...fullData }

      // 乐观更新
      msg.signals = [...msg.signals, newSig]
      const idx = this.messages.findIndex(m => m.id === this.selectedMsgId)
      if (idx >= 0) {
        this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
      }
      this._localDirty = true

      try {
        const result = await this._wsRequest('add_signal', { msg_id: this.selectedMsgId, signal: fullData })
        // 用后端返回的真实 UUID 替换临时 UUID
        const sigIdx = msg.signals.findIndex(s => s.uuid === clientUuid)
        if (sigIdx >= 0 && result) {
          msg.signals[sigIdx] = result
        }
        useUiStore().showToast(t('toast.signalAdded'))
        this.addLogEntry('signal_add', `添加信号: name=${fullData.name}, start_bit=${fullData.start_bit}, length=${fullData.length}`)
      } catch (e) {
        useUiStore().showToast(_translateError(e), true)
        // 回滚：移除乐观添加的信号
        msg.signals = msg.signals.filter(s => s.uuid !== clientUuid)
        if (idx >= 0) {
          this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
        }
      }
    },

    /**
     * 更新信号属性（乐观更新模式）
     * 值变化时先入撤销栈，再更新本地状态，异步发送 API。
     * 成功后重置 5s 轮询定时器，全量重载由定时器超时触发。
     * @param {string} sigUuid - 信号 UUID
     * @param {string} field - 字段名
     * @param {any} value - 新值
     * @returns {Promise<void>}
     */
    async updateSignal(sigUuid, field, value) {
      if (this.selectedMsgId == null) return
      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return
      const sig = msg.signals.find(s => s.uuid === sigUuid)
      if (!sig) return
      const oldVal = sig[field]

      // 记忆用户修改的 length
      if (field === 'length') {
        this._defaultSignalLength = value
      }

      // 乐观更新
      sig[field] = value
      this._localDirty = true

      // 防抖
      const queueKey = `signal_${sigUuid}_${field}`
      const existing = PENDING_EDITS.get(queueKey)
      if (existing) clearTimeout(existing.timer)

      return new Promise((resolve, reject) => {
        const timer = setTimeout(async () => {
          PENDING_EDITS.delete(queueKey)
          try {
            await this._wsRequest('edit_signal', {
              msg_id: this.selectedMsgId,
              sig_uuid: sigUuid,
              field: field,
              value: value
            })
            resolve()
          } catch (e) {
            if (!e.message?.includes?.('Connection lost')) {
              useUiStore().showToast(_translateError(e), true)
            }
            sig[field] = oldVal  // 回滚
            reject(e)
          }
        }, 300)
        PENDING_EDITS.set(queueKey, { timer, reject })
      })
    },

    /**
     * 删除信号（乐观更新模式）
     * 先更新本地状态再发送 API，失败时回滚。
     * 成功后重置 5s 轮询定时器，全量重载由定时器超时触发。
     * @param {string} sigUuid - 信号 UUID
     * @returns {Promise<void>}
     */
    async deleteSignal(sigUuid) {
      if (this.selectedMsgId == null) return
      const msg = this.selectedMessage

      // 乐观更新
      const oldSignals = msg ? [...msg.signals] : []
      if (msg) {
        msg.signals = msg.signals.filter(s => s.uuid !== sigUuid)
      }
      const idx = this.messages.findIndex(m => m.id === this.selectedMsgId)
      if (idx >= 0 && msg) {
        this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
      }
      this._localDirty = true

      try {
        await this._wsRequest('delete_signal', { msg_id: this.selectedMsgId, sig_uuid: sigUuid })
        useUiStore().showToast(t('toast.signalDeleted'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
        // 回滚
        if (msg) msg.signals = oldSignals
        if (idx >= 0 && msg) {
          this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
        }
      }
    },

    /**
     * 批量添加信号（乐观更新 + 并发 API）
     * 所有信号先本地乐观更新，然后并发发送 API 请求
     * API 成功后替换 clientUuid 为真实 UUID，并入撤销栈
     * 成功后重置 5s 轮询定时器，全量重载由定时器超时触发。
     * @param {Object} params - 批量参数
     * @param {string} params.nameTemplate - 名称模板（如 "Signal_{n}"）
     * @param {number} params.count - 信号数量
     * @param {number} params.startNum - 起始编号
     * @param {number} params.startBit - 起始位
     * @param {number} params.bitStep - 位步长
     * @param {number} params.length - 信号长度
     * @param {string} params.byteOrder - 字节序（motorola/intel）
     * @param {number} params.factor - 因子
     * @param {number} params.offset - 偏移
     * @param {number} params.minVal - 最小值
     * @param {number} params.maxVal - 最大值
     * @param {string} params.unit - 单位
     * @param {string} params.commentTemplate - 注释模板
     * @returns {Promise<void>}
     */
    async batchAddSignals({ nameTemplate, count, startNum, startBit, bitStep, length, byteOrder, factor, offset, minVal, maxVal, unit, commentTemplate }) {
      if (this.selectedMsgId == null) return
      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return
      const { expandTemplate } = await import('../utils/format.js')
      const maxBits = msg.dlc * 8
      const lastEnd = startBit + (count - 1) * bitStep + length
      // 简单预检查（Intel 格式估算；Motorola 的实际边界由后端验证）
      if (lastEnd > maxBits) {
        useUiStore().showToast(`Last signal ends at bit ${lastEnd - 1}, exceeds ${maxBits - 1}`, true)
        return
      }

      // 乐观更新：先构建所有新信号
      const newSigs = []
      for (let i = 0; i < count; i++) {
        const n = startNum + i
        const name = expandTemplate(nameTemplate, n)
        const comment = commentTemplate ? expandTemplate(commentTemplate, n) : ''
        const sb = startBit + i * bitStep
        const sig = {
          uuid: crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(16).slice(2, 10),
          name, start_bit: sb, length, byte_order: byteOrder,
          factor, offset, min_val: minVal, max_val: maxVal, unit, comment,
        }
        newSigs.push(sig)
      }

      // 立即更新 UI
      msg.signals = [...msg.signals, ...newSigs]
      const idx = this.messages.findIndex(m => m.id === this.selectedMsgId)
      if (idx >= 0) {
        this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
      }
      this._localDirty = true
      this.isLoading = true

      // 异步批量发送
      let created = 0
      try {
        const result = await this._wsRequest('batch_add_signals', {
          msg_id: this.selectedMsgId,
          signals: newSigs.map(sig => ({
            name: sig.name, start_bit: sig.start_bit, length: sig.length,
            byte_order: sig.byte_order, factor: sig.factor, offset: sig.offset,
            min_val: sig.min_val, max_val: sig.max_val, unit: sig.unit, comment: sig.comment,
          }))
        })

        if (result && result.created) {
          created = result.created.length
          for (const serverSig of result.created) {
            const clientSig = newSigs.find(s => s.name === serverSig.name)
            if (clientSig) {
              const idxInMsg = msg.signals.findIndex(s => s.uuid === clientSig.uuid)
              if (idxInMsg >= 0) {
                msg.signals[idxInMsg] = serverSig
              }
            }
          }
        }

        if (result && result.errors && result.errors.length > 0) {
          console.warn('[STORE] batchAddSignals() 部分信号创建失败:', result.errors)
        }

        useUiStore().showToast(t('toast.batchCreated', { count: created }))
      } catch (e) {
        useUiStore().showToast(t('toast.batchFailed', { idx: 1, msg: e.message }), true)
        // 回滚：移除乐观添加的信号
        const newNames = newSigs.map(s => s.name)
        msg.signals = msg.signals.filter(s => !newNames.includes(s.name))
        const msgIdx = this.messages.findIndex(m => m.id === this.selectedMsgId)
        if (msgIdx >= 0) {
          this.messages[msgIdx] = { ...this.messages[msgIdx], signal_count: msg.signals.length }
        }
      } finally {
        this.isLoading = false
      }
    },

    /**
     * 检查 WS 连接健康状态
     * 由 App.vue 定时调用
     * @returns {void}
     */
    checkApiHealth() {
      if (this._wsClient?.connected) {
        this._healthFailCount = 0
        this.apiStatus = 'connected'
        this._hasBeenConnected = true
      } else {
        this._healthFailCount++
        if (this._healthFailCount >= 2) {
          this.apiStatus = 'dead'
        } else {
          this.apiStatus = 'offline'
        }
      }
    },

    // ── 操作日志 ──

    addLogEntry(type, description) {
      const time = new Date().toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      this.logEntries.unshift({ time, type, description })
      if (this.logEntries.length > 500) {
        this.logEntries.pop()
      }
    },

    clearLog() {
      this.logEntries = []
    },

    /**
     * 加载会话
     * @param {string} sessionId - 会话 ID
     * @returns {Promise<void>}
     */
    async loadHistorySession(sessionId) {
      this.selectedMsgId = null
      this.messageCache = {}
      this.messages = []
      this.signalErrors = []
      this._localDirty = false
      this._defaultSignalLength = 8
      this._healthFailCount = 0
      this.clearUndoStack()
      this.isLoading = true

      try {
        const currentSid = getSessionId()

        // 先停止旧 WS 连接，再启动新连接
        this.stopEditorSync()
        this.startEditorSync()
        await this._waitForWsReady()

        // WS 已连接，发送 load_session 请求（服务端 restore + session 切换 + full_sync）
        const data = await this._wsRequest('load_session', {
          session_id: sessionId,
          current_session_id: currentSid
        })
        const sid = data.session_id
        setSessionId(sid)
        this.currentFileName = data.file_name || ''
        useUiStore().showToast(t('toast.sessionLoaded'))
      } catch (e) {
        if (e.code === 'FILE_LOCKED') {
          e.message = t('toast.noEditPermission')
        } else {
          useUiStore().showToast(e.message, true)
        }
        throw e
      } finally {
        this.isLoading = false
      }
    },

    async renameSession(name) {
      try {
        const data = await this._wsRequest('rename_session', { name })
        this.currentFileName = data.file_name || ''
        this._localDirty = true
        useUiStore().showToast(t('toast.renamed'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    async createNewSession(name = 'Untitled') {
      try {
        // 先停止旧 WS 连接，再启动新连接
        this.stopEditorSync()
        this.startEditorSync()
        await this._waitForWsReady()

        const data = await this._wsRequest('new_file', { name })
        const sid = data.session_id
        setSessionId(sid)
        this.currentFileName = data.name + '.toml'
        this.selectedMsgId = null
        this.messageCache = {}
        this.messages = []
        this.signalErrors = []
        this._localDirty = false
        this._defaultSignalLength = 8
        this.clearUndoStack()
        useUiStore().showToast(t('toast.newSessionCreated'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 新建文件（从 FileBrowser 调用）
     * 与 createNewSession 类似，但不显示 Toast（由 FileBrowser 处理）
     */
    async newFile(name = 'Untitled') {
      // 先停止旧 WS 连接，再启动新连接
      this.stopEditorSync()
      this.startEditorSync()
      await this._waitForWsReady()

      const data = await this._wsRequest('new_file', { name })
      const sid = data.session_id
      setSessionId(sid)
      this.currentFileName = data.name + '.toml'
      this.selectedMsgId = null
      this.messageCache = {}
      this.messages = []
      this.signalErrors = []
      this._localDirty = false
      this._defaultSignalLength = 8
      this.clearUndoStack()
      return sid
    },

    /**
     * 释放当前 session 的文件锁（返回文件浏览器时调用）。
     * 传递 abort=true 同时销毁 session，丢弃未保存的变更。
     */
    async releaseSession() {
      const sid = getSessionId()
      if (sid) {
        try {
          await this._wsRequest('release_lock', { abort: true })
        } catch (_) {
          // 忽略释放失败
        }
      }
    },

    // ═══════════════════════════════════════════
    // 区域 D：剪贴板（Clipboard）
    // ═══════════════════════════════════════════

    /**
     * 复制信号到剪贴板
     * @param {string} sigUuid - 信号 UUID
     */
    copySignal(sigUuid) {
      const msg = this.selectedMessage
      if (!msg) return
      const sig = msg.signals.find(s => s.uuid === sigUuid)
      if (!sig) return
      this.clipboard = { type: 'signal', data: JSON.parse(JSON.stringify(sig)) }
      useUiStore().showToast(t('toast.signalCopied'))
    },

    /**
     * 剪切信号到剪贴板（复制 + 删除）
     * @param {string} sigUuid - 信号 UUID
     * @returns {Promise<void>}
     */
    async cutSignal(sigUuid) {
      this.copySignal(sigUuid)
      await this.deleteSignal(sigUuid)
      useUiStore().showToast(t('toast.signalCut'))
    },

    /**
     * 从剪贴板粘贴信号
     * @returns {Promise<void>}
     */
    async pasteSignal() {
      if (!this.clipboard || this.clipboard.type !== 'signal' || this.selectedMsgId == null) return
      const sig = JSON.parse(JSON.stringify(this.clipboard.data))
      sig.name = sig.name ? sig.name + '_copy' : 'PastedSig'
      await this.addSignal(sig)
      useUiStore().showToast(t('toast.signalPasted'))
    },

    copyMessage() {
      const msg = this.selectedMessage
      if (!msg) return
      this.clipboard = { type: 'message', data: JSON.parse(JSON.stringify(msg)) }
      useUiStore().showToast(t('toast.messageCopied'))
    },

    async pasteMessage() {
      if (!this.clipboard || this.clipboard.type !== 'message') return
      const msg = JSON.parse(JSON.stringify(this.clipboard.data))
      const maxId = this.messages.length > 0
        ? Math.max(...this.messages.map(m => m.id)) + 0x10
        : msg.id + 0x10
      msg.id = maxId
      msg.name = (msg.name || 'PastedMsg') + '_copy'
      try {
        await this._wsRequest('add_message', { message: msg })
        this.selectedMsgId = maxId
        useUiStore().showToast(t('toast.messagePasted'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    async duplicateMessage() {
      const orig = this.selectedMessage
      if (!orig) return
      const maxId = this.messages.length > 0
        ? Math.max(...this.messages.map(m => m.id)) + 0x10
        : orig.id + 0x10
      try {
        await this._wsRequest('duplicate_message', { msg_id: orig.id, new_id: maxId })
        this.selectedMsgId = maxId
        useUiStore().showToast(t('toast.messageDuplicated'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },
  },
})
