import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import { setSessionId, getSessionId } from '../api/client.js'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useUndoRedoStore } from './undoRedo.js'
import { WsSyncClient, WsFrontendDiag } from '../utils/ws-client.js'
import { checkVersionHash } from '../utils/version-check.js'
import { resetMessageIdGenerator } from '../utils/storeHelpers.js'
import { setConnectionStatus, resetConnection } from './connectionHealth.js'
import { useAuthStore } from './authStore.js'

export const useCoreStore = defineStore('core', {
  state: () => ({
    // ── 核心数据 ──
    messages: {},
    selectedMsgId: null,
    messageCache: {},

    // ── 会话与文件 ──
    currentFileName: '',
    busType: 'CAN',  // 全局总线类型，用户显式配置
    readOnly: false,  // 只读模式：当前用户非文件 owner

    // ── 全局值描述表 ──
    valueTables: {},

    // ── 运行时状态 ──
    isLoading: false,
    backendDirty: false,
    lastSaveError: null,
    saveStatus: 'idle',   // 'idle' | 'saving' | 'saved' | 'modified'
    _saveStatusTimer: null,
    dataErrors: [],
    _healthFailCount: 0,
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
      return Object.keys(state.messages).length
    },
    signalCount(state) {
      return Object.values(state.messages).reduce((sum, m) => sum + (m.signal_count || 0), 0)
    },
    signalErrors(state) {
      if (state.selectedMsgId == null) return []
      return (state.dataErrors || []).filter(e => e.msg_id === state.selectedMsgId)
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

    /**
     * 统一的会话拆卸入口。所有退出路径必须通过此方法。
     * @param {'go_back'|'lock_stolen'|'session_invalid'|'permanent_failure'|'session_failure'|'lock_lost_on_reconnect'} reason
     */
    _teardownSession(reason) {
      console.warn(`[Session] teardown: reason=${reason}`)
      this.stopEditorSync()
      setSessionId('')
      this.currentFileName = ''
      resetConnection()
      this.resetEditorState()
      // 关闭所有模态框，避免残留弹出
      const uiStore = useUiStore()
      uiStore.closeCcodePreview()
      uiStore.batchModalOpen = false
      window.dispatchEvent(new CustomEvent('navigate-browser'))
    },

    _resetOnSessionFailure() {
      this._teardownSession('session_failure')
    },

    resetEditorState() {
      this.messages = {}
      this.selectedMsgId = null
      this.messageCache = {}
      this.currentFileName = ''
      this.busType = 'CAN'
      this.readOnly = false
      this.backendDirty = false
      this.lastSaveError = null
      this.saveStatus = 'idle'
      if (this._saveStatusTimer) { clearTimeout(this._saveStatusTimer); this._saveStatusTimer = null }
      this.dataErrors = []
      this.logEntries = []
      this.valueTables = {}
      this._dataVersion = 0
      // 通过拆分 store 清理
      const undoRedo = useUndoRedoStore()
      undoRedo.clearUndoStack()
      // 关闭所有动态标签页
      useUiStore().closeAllMessageTabs()
    },

    _startSaveFadeTimer() {
      if (this._saveStatusTimer) clearTimeout(this._saveStatusTimer)
      this._saveStatusTimer = setTimeout(() => {
        if (this.saveStatus === 'saved' && !this.backendDirty) {
          this.saveStatus = 'idle'
        }
        this._saveStatusTimer = null
      }, 3000)
    },

    /**
     * 统一的后端状态同步入口。
     * status_changed / undo_applied / redo_applied / full_sync 均通过此方法
     * 更新 backendDirty、saveStatus、undo/redo 计数。
     */
    _syncBackendStatus(status) {
      if (!status) return
      if ('modified' in status) {
        this.backendDirty = !!status.modified
        if (status.modified && this.saveStatus !== 'saving') {
          this.saveStatus = 'modified'
          if (this._saveStatusTimer) { clearTimeout(this._saveStatusTimer); this._saveStatusTimer = null }
        } else if (!status.modified && this.saveStatus === 'saving') {
          this.saveStatus = 'saved'
          this._startSaveFadeTimer()
        }
      }
      const undoRedo = useUndoRedoStore()
      if ('undo_count' in status) undoRedo.undoCount = status.undo_count || 0
      if ('redo_count' in status) undoRedo.redoCount = status.redo_count || 0
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
        getToken: () => useAuthStore().token,
        onMessage: (msg) => { this._applyWsMessage(msg) },
        onStatusChange: (status) => {
          // 守卫：如果不是当前活跃的 client，忽略此回调
          if (this._wsClient !== client) return

          if (status === 'connected') {
            this._wsConnected = true
          } else if (status === 'disconnected') {
            this._wsConnected = false
          } else if (status === 'auth_required') {
            // 4010: token 失效，清除认证并跳转登录页
            const auth = useAuthStore()
            auth.clearAuth()
            window.dispatchEvent(new CustomEvent('auth-expired'))
          } else if (status === 'session_invalid') {
            // 4003: 后端重启或 session 超时，当前 session 已失效
            this._teardownSession('session_invalid')
            useUiStore().showToast(t('toast.sessionLost') || 'Session lost, please return to file list', true)
          } else if (status === 'permanent_failure') {
            // 真正的协议级错误（4001 hello timeout / 4002 bad protocol）
            this._teardownSession('permanent_failure')
            useUiStore().showToast(t('toast.sessionLost') || 'Session lost, please return to file list', true)
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

          if (d.lock_status === 'lost' && !this.readOnly) {
            console.warn('[WS] full_sync: lock lost on reconnect, navigating to file list')
            this._teardownSession('lock_lost_on_reconnect')
            useUiStore().showToast(t('toast.sessionLost') || 'Session lost', true)
            break
          }

          this.messages = d.messages || {}
          this.valueTables = d.value_tables || {}
          if (d.bus_type) this.busType = d.bus_type
          resetMessageIdGenerator()
          if (d.status) {
            this._syncBackendStatus(d.status)
          }
          if (this.selectedMsgId != null &&
              !this.messages[String(this.selectedMsgId)]) {
            this.selectedMsgId = null
            this.messageCache = {}
          }
          // 关闭指向已不存在报文的动态标签页
          useUiStore().openTabs
            .filter(t => !this.messages[String(t.msgId)])
            .forEach(t => useUiStore().closeMessageTab(t.msgId))
          // full_sync 完成后自动拉取全局错误列表
          this._wsRequest('get_data_errors').then(errors => {
            this.dataErrors = errors || []
          }).catch(() => {})
          break
        }

        case 'signal_updated': {
          WsFrontendDiag.count('signal_updated')
          const { msg_id, signal, old_name, total_signal_bits } = msg.data
          const cache = this.messageCache[msg_id]
          if (cache && cache.signals) {
            if (old_name && old_name !== signal.name) {
              delete cache.signals[old_name]
            }
            cache.signals[signal.name] = signal
          }
          if (total_signal_bits != null) {
            const summary = this.messages[String(msg_id)]
            if (summary) {
              this.messages[String(msg_id)] = { ...summary, total_signal_bits }
            }
          }
          break
        }

        case 'signal_added': {
          const { msg_id, signal, total_signal_bits } = msg.data
          const cache = this.messageCache[msg_id]
          if (cache) {
            cache.signals = { ...cache.signals, [signal.name]: signal }
          }
          const msgSummary = this.messages[String(msg_id)]
          if (msgSummary) {
            this.messages[String(msg_id)] = {
              ...msgSummary,
              signal_count: cache ? Object.keys(cache.signals).length
                : msgSummary.signal_count + 1,
              ...(total_signal_bits != null ? { total_signal_bits } : {})
            }
          }
          break
        }

        case 'signal_deleted': {
          const { msg_id, signal_name, total_signal_bits } = msg.data
          const cache = this.messageCache[msg_id]
          if (cache && cache.signals) {
            const newSignals = { ...cache.signals }
            delete newSignals[signal_name]
            cache.signals = newSignals
          }
          const msgSummary2 = this.messages[String(msg_id)]
          if (msgSummary2) {
            this.messages[String(msg_id)] = {
              ...msgSummary2,
              signal_count: cache ? Object.keys(cache.signals).length
                : Math.max(0, msgSummary2.signal_count - 1),
              ...(total_signal_bits != null ? { total_signal_bits } : {})
            }
          }
          // 删除的信号若正在选中，清空 selectedSignalName
          if (useUiStore().selectedSignalName === signal_name) {
            useUiStore().selectedSignalName = null
          }
          break
        }

        case 'message_added': {
          const addedMsg = msg.data.message
          this.messages = { ...this.messages, [String(addedMsg.id)]: addedMsg }
          break
        }
        case 'message_updated': {
          const m = msg.data.message
          const oldId = msg.data.old_id
          const lookupKey = oldId != null ? String(oldId) : String(m.id)
          if (this.messages[lookupKey]) {
            this.messages[lookupKey] = { ...this.messages[lookupKey], ...m }
          }
          if (oldId != null && oldId !== m.id) {
            // ID 变更：re-key summary + cache
            delete this.messages[String(oldId)]
            this.messages[String(m.id)] = { ...m }
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
            // 更新动态标签页的 msgId
            const uiForTab = useUiStore()
            const tab = uiForTab.openTabs.find(t => t.msgId === oldId)
            if (tab) {
              tab.msgId = m.id
              if (uiForTab.activeTabId === oldId) {
                uiForTab.activeTabId = m.id
                uiForTab.centerTab = `msg_${m.id}`
              }
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
          const delKey = String(deletedId)
          const newMessages = { ...this.messages }
          delete newMessages[delKey]
          this.messages = newMessages
          if (this.selectedMsgId === deletedId) {
            this.selectedMsgId = null
          }
          delete this.messageCache[deletedId]
          // 关闭引用此报文的动态标签页
          useUiStore().closeMessageTab(deletedId)
          break
        }

        case 'undo_applied':
        case 'redo_applied': {
          this._syncBackendStatus(msg.data.status)
          if (msg.data.bus_type) {
            this.busType = msg.data.bus_type
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
          if (msg.data.value_tables) {
            this.valueTables = msg.data.value_tables
          }
          // selectedMsgId 可能在 undo/redo ID 变更后失效（复用 full_sync 模式）
          if (this.selectedMsgId != null &&
              !this.messages[String(this.selectedMsgId)]) {
            this.selectedMsgId = null
          }
          // 关闭指向已不存在报文的动态标签页
          useUiStore().openTabs
            .filter(t => !this.messages[String(t.msgId)])
            .forEach(t => useUiStore().closeMessageTab(t.msgId))
          break
        }

        case 'status_changed': {
          this._syncBackendStatus(msg.data)
          if (msg.data.save_error) {
            useUiStore().showToast(t('toast.autoSaveFailed', { error: msg.data.save_error }), true)
          }
          break
        }

        case 'database_updated': {
          if (msg.data.bus_type) {
            this.busType = msg.data.bus_type
          }
          break
        }

        case 'value_table_added': {
          const { name, entries } = msg.data
          this.valueTables[name] = entries
          break
        }
        case 'value_table_updated': {
          const { name, entries } = msg.data
          this.valueTables[name] = entries
          break
        }
        case 'value_table_deleted': {
          const { name } = msg.data
          delete this.valueTables[name]
          break
        }
        case 'value_table_renamed': {
          const { old_name, new_name } = msg.data
          if (this.valueTables[old_name]) {
            this.valueTables[new_name] = this.valueTables[old_name]
            delete this.valueTables[old_name]
          }
          // 级联更新 messageCache 中信号的 value_table_name 引用
          for (const cache of Object.values(this.messageCache)) {
            if (cache?.signals) {
              for (const sig of Object.values(cache.signals)) {
                if (sig.value_table_name === old_name) {
                  sig.value_table_name = new_name
                }
              }
            }
          }
          break
        }

        case 'data_errors_changed': {
          this.dataErrors = msg.data.errors || []
          break
        }

        case 'lock_stolen': {
          // read-only 用户不受抢占事件影响
          if (this.readOnly) break

          const victimSid = msg.data?.victim_session_id
          if (victimSid && victimSid !== getSessionId()) break

          WsFrontendDiag.count('lock_stolen')
          console.warn('[WS] lock stolen, victim:', victimSid)
          this._teardownSession('lock_stolen')
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
        setConnectionStatus('connected')
        // 版本信息已通过 WS pong/server_version 推送（ws-client.js），无需 HTTP 轮询
      } else {
        this._healthFailCount++
        if (this._healthFailCount >= 2) {
          setConnectionStatus('dead')
        } else {
          setConnectionStatus('offline')
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
