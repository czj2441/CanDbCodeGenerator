import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import { setSessionId, getSessionId } from '../api/client.js'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useUndoRedoStore } from './undoRedo.js'
import { WsSyncClient, WsFrontendDiag } from '../utils/ws-client.js'
import { checkVersionHash } from '../utils/version-check.js'
import { resetMessageIdGenerator } from '../utils/storeHelpers.js'

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
    backendDirty: false,
    lastSaveError: null,
    signalErrors: [],
    _healthFailCount: 0,
    _hasBeenConnected: false,
    _defaultSignalLength: 8,
    logEntries: [],

    // ── WebSocket 状态 ──
    _dataVersion: 0,
    _wsConnected: false,
    _wsClient: null,
    _wsIntentionalClose: false,
    _healthTimer: null,
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
  },

  actions: {
    // ═══════════════════════════════════════════
    // WebSocket 连接管理 + 消息分发
    // ═══════════════════════════════════════════

    startEditorSync() {
      this._connectWebSocket()
      if (this._healthTimer) clearInterval(this._healthTimer)
      this._healthTimer = setInterval(() => this.checkApiHealth(), 2000)
    },

    stopEditorSync() {
      this._wsIntentionalClose = true
      if (this._healthTimer) { clearInterval(this._healthTimer); this._healthTimer = null }
      if (this._wsClient) {
        this._wsClient.disconnect()
        this._wsClient = null
      }
      this._wsConnected = false
    },

    _resetOnSessionFailure() {
      this.stopEditorSync()
      setSessionId('')
      this.currentFileName = ''
    },

    resetEditorState() {
      this.messages = []
      this.selectedMsgId = null
      this.messageCache = {}
      this.currentFileName = ''
      this.backendDirty = false
      this.lastSaveError = null
      this.signalErrors = []
      this.logEntries = []
      this._dataVersion = 0
      // 通过拆分 store 清理
      const undoRedo = useUndoRedoStore()
      undoRedo.clearUndoStack()
    },

    _connectWebSocket() {
      if (this._wsClient?.connected) return

      // 断开旧的 WS 客户端（可能正在重连中），防止僵尸实例
      if (this._wsClient) {
        this._wsClient.disconnect()
        this._wsClient = null
      }

      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsPort = parseInt(location.port) + 1
      const wsUrl = `${protocol}//${location.hostname}:${wsPort}/ws`

      this._wsIntentionalClose = false
      this._dataVersion = 0

      const client = new WsSyncClient({
        url: wsUrl,
        getSessionId: () => getSessionId() || '',
        onMessage: (msg) => { this._applyWsMessage(msg) },
        onStatusChange: (status) => {
          // 守卫：如果不是当前活跃的 client，忽略此回调
          if (this._wsClient !== client) return

          if (status === 'connected') {
            this._wsConnected = true
          } else if (status === 'disconnected') {
            this._wsConnected = false
          } else if (status === 'session_invalid') {
            // 4003: 后端重启或 session 超时，当前 session 已失效
            this._resetOnSessionFailure()
            useUiStore().showToast(t('toast.sessionLost') || 'Session lost, please return to file list', true)
            window.dispatchEvent(new CustomEvent('navigate-browser'))
          } else if (status === 'permanent_failure') {
            // 真正的协议级错误（4001 hello timeout / 4002 bad protocol）
            this._resetOnSessionFailure()
            useUiStore().showToast(t('toast.sessionLost') || 'Session lost, please return to file list', true)
            window.dispatchEvent(new CustomEvent('navigate-browser'))
          }
        }
      })
      this._wsClient = markRaw(client)
      client.connect()
    },

    /**
     * WS 请求助手
     */
    _wsRequest(type, data = {}, timeout) {
      if (!this._wsClient) {
        return Promise.reject(new Error('WebSocket not connected'))
      }
      return this._wsClient.request(type, {
        ...data,
        session_id: getSessionId() || '',
      }, timeout)
    },

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
     */
    _applyWsMessage(msg) {
      const stopTimer = WsFrontendDiag.timeStart('apply_msg')
      const undoRedo = useUndoRedoStore()

      if (msg.data_version && msg.data_version < this._dataVersion) {
        WsFrontendDiag.count('msg_dropped')
        stopTimer()
        return
      }
      if (msg.data_version) {
        this._dataVersion = msg.data_version
      }
      WsFrontendDiag.count('msg_received')

      switch (msg.type) {
        case 'full_sync': {
          WsFrontendDiag.count('full_sync')
          this._dataVersion = msg.data_version ?? 0
          const d = msg.data

          if (d.lock_status === 'lost') {
            this._applyWsMessage({
              type: 'lock_stolen',
              data: { victim_session_id: getSessionId() }
            })
            break
          }

          this.messages = d.messages || []
          resetMessageIdGenerator()
          if (d.status) {
            this.backendDirty = d.status.modified || false
            undoRedo.syncCounts(d.status)
          }
          if (this.selectedMsgId != null &&
              !this.messages.some(m => m.id === this.selectedMsgId)) {
            this.selectedMsgId = null
            this.messageCache = {}
            this.signalErrors = []
          }
          break
        }

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

        case 'message_added': {
          this.messages = [...this.messages, msg.data.message]
          break
        }
        case 'message_updated': {
          const m = msg.data.message
          const oldId = msg.data.old_id
          const lookupId = oldId != null ? oldId : m.id
          const idx = this.messages.findIndex(x => x.id === lookupId)
          if (idx >= 0) {
            this.messages[idx] = { ...this.messages[idx], ...m }
          }
          if (oldId != null && oldId !== m.id) {
            // ID 变更：re-key cache
            const oldCache = this.messageCache[oldId]
            if (oldCache) {
              Object.assign(oldCache, m)
              this.messageCache[m.id] = oldCache
              delete this.messageCache[oldId]
            }
            // 同步 selectedMsgId
            if (this.selectedMsgId === oldId) {
              this.selectedMsgId = m.id
            }
          } else {
            const cache = this.messageCache[m.id]
            if (cache) {
              Object.assign(cache, m)
            }
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

        case 'undo_applied':
        case 'redo_applied': {
          if (msg.data.status) {
            this.backendDirty = msg.data.status.modified
            undoRedo.syncCounts(msg.data.status)
          }
          if (msg.data.messages) {
            this.messages = msg.data.messages
          }
          if (msg.data.message_details) {
            // 全量替换：后端发送的是完整快照，消除旧 ID 残留
            const newCache = {}
            for (const [mid, detail] of Object.entries(msg.data.message_details)) {
              newCache[parseInt(mid)] = detail
            }
            this.messageCache = newCache
          }
          // selectedMsgId 可能在 undo/redo ID 变更后失效（复用 full_sync 模式）
          if (this.selectedMsgId != null &&
              !this.messages.some(m => m.id === this.selectedMsgId)) {
            this.selectedMsgId = null
            this.signalErrors = []
          }
          break
        }

        case 'status_changed': {
          const s = msg.data
          if ('modified' in s) this.backendDirty = s.modified
          if ('undo_count' in s) undoRedo.undoCount = s.undo_count
          if ('redo_count' in s) undoRedo.redoCount = s.redo_count
          if (s.save_error) {
            useUiStore().showToast(t('toast.autoSaveFailed', { error: s.save_error }), true)
          }
          break
        }

        case 'signal_errors_changed': {
          this.signalErrors = msg.data.errors || []
          break
        }

        case 'lock_stolen': {
          const victimSid = msg.data?.victim_session_id
          if (victimSid && victimSid !== getSessionId()) break

          WsFrontendDiag.count('lock_stolen')
          console.warn('[WS] lock stolen, victim:', victimSid,
                       msg.data?.stealer_session_id ? ', by: ' + msg.data.stealer_session_id : '')
          this._wsIntentionalClose = true
          this._wsClient?._cleanupPendingRequests()
          this._wsClient?.disconnect()
          this._wsClient = null
          this._wsConnected = false
          this.resetEditorState()
          window.dispatchEvent(new CustomEvent('navigate-browser'))
          useUiStore().showToast(t('toast.noEditPermission'), true)
          break
        }

        case 'pong':
          break

        case 'server_version':
          break
      }

      stopTimer()
    },

    /**
     * 检查前后端版本一致性
     */
    async checkVersion() {
      try {
        const resp = await fetch('/api/version')
        if (!resp.ok) return
        const data = await resp.json()
        if (data.success) {
          checkVersionHash(data.data)
        }
      } catch {
        /* 静默 */
      }
    },

    /**
     * 检查 WS 连接健康状态
     */
    checkApiHealth() {
      if (this._wsClient?.connected) {
        this._healthFailCount = 0
        this.apiStatus = 'connected'
        this._hasBeenConnected = true
        this.checkVersion()
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
  },
})
