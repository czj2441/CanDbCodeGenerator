import { defineStore } from 'pinia'
import { api, setSessionId, clearSession, addRecentSession, removeRecentSession } from '../api/client.js'
import { t } from '../i18n.js'
import { createUndoRedoManager } from '../utils/useUndoRedo.js'
import { markModified } from '../utils/storeHelpers.js'
import { useUiStore } from './uiStore.js'

export const useEditorStore = defineStore('editor', {
  state: () => ({
    // ── 核心数据 ──
    messages: [],
    selectedMsgId: null,
    messageCache: {},

    // ── 会话与文件 ──
    currentFileName: '',
    sessionHistory: [],

    // ── 运行时状态 ──
    isLoading: false,
    apiStatus: 'connecting',
    modified: false,
    modifiedAt: 0,
    signalErrors: [],

    // ── 视图状态 ──
    layoutViewMode: false,
    selectedSignalUuid: null,

    // ── 剪贴板 ──
    clipboard: null,

    // ── 撤销/重做 ──
    _undoRedo: null,
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
    // 区域 C：撤销/重做（Undo/Redo）
    // ═══════════════════════════════════════════

    /**
     * 初始化撤销/重做管理器
     * 懒加载模式：首次调用时创建 createUndoRedoManager 实例
     */
    initUndoRedo() {
      if (this._undoRedo) return // 已初始化
      this._undoRedo = createUndoRedoManager({
        maxSize: 50,
        onReload: async () => {
          await this.loadMessages()
          if (this.selectedMsgId != null) await this.loadSelectedMessage()
        },
        onToast: (text, isError) => useUiStore().showToast(text, isError),
        onLog: (type, description) => useUiStore().addLogEntry(type, description),
      })
    },

    pushUndo(snapshot) {
      this.initUndoRedo()
      this._undoRedo.pushUndo(snapshot)
      // ✅ 同步响应式计数器（pushUndo 会清空 redoStack）
      this.undoCount = this._undoRedo.undoCount
      this.redoCount = 0
    },

    async undo() {
      this.initUndoRedo()
      await this._undoRedo.undo()
      // ✅ 同步响应式计数器
      this.undoCount = this._undoRedo.undoCount
      this.redoCount = this._undoRedo.redoCount
    },

    async redo() {
      this.initUndoRedo()
      await this._undoRedo.redo()
      // ✅ 同步响应式计数器
      this.undoCount = this._undoRedo.undoCount
      this.redoCount = this._undoRedo.redoCount
    },

    clearUndoStack() {
      if (this._undoRedo) {
        this._undoRedo.clear()
        // ✅ 同步响应式计数器
        this.undoCount = 0
        this.redoCount = 0
      }
    },

    // ═══════════════════════════════════════════
    // 区域 B：会话管理（Session Management）
    // ═══════════════════════════════════════════

    async initSession() {
      const sid = sessionStorage.getItem('canmatrix_session_id')
      if (sid) {
        try {
          const data = await api('GET', `/api/session/${sid}`)
          if (data && data.session_id) {
            this.currentFileName = data.file_name || ''
            this.clearUndoStack() // 切换会话时清空撤销栈
            await this.loadMessages()
            this.apiStatus = 'connected'
            useUiStore().showToast(t('toast.restored', { name: data.file_name }))
            return
          }
        } catch (_) {
          clearSession()
        }
      }
      await this.createDemoSession()
    },

    async createDemoSession() {
      try {
        const session = await api('POST', '/api/session', { name: 'DemoCAN' })
        setSessionId(session.session_id)
        addRecentSession(session.session_id, session.file_name || '')
        this.currentFileName = session.file_name || ''
        this.clearUndoStack() // 新会话初始化时清空撤销栈

        await api('POST', '/api/messages', {
          id: '0x100', name: 'EngineStatus', dlc: 8, cycle_time: 10, sender: 'ECU1',
          signals: [
            { name: 'RPM', start_bit: 0, length: 16, factor: 0.25, unit: 'rpm', min_val: 0, max_val: 16000 },
            { name: 'Speed', start_bit: 16, length: 16, factor: 0.1, unit: 'km/h', min_val: 0, max_val: 300 },
            { name: 'Temp', start_bit: 32, length: 8, factor: 1.0, offset: -40, unit: '°C', min_val: -40, max_val: 215 },
          ],
        })

        await api('POST', '/api/messages', {
          id: '0x200', name: 'BatteryInfo', dlc: 6, cycle_time: 100, sender: 'BMS',
          signals: [
            { name: 'Voltage', start_bit: 0, length: 12, factor: 0.01, unit: 'V', min_val: 0, max_val: 500 },
            { name: 'Current', start_bit: 12, length: 12, factor: -0.1, offset: 204.7, unit: 'A', min_val: -200, max_val: 200 },
            { name: 'SoC', start_bit: 24, length: 8, factor: 0.5, unit: '%', min_val: 0, max_val: 100 },
          ],
        })

        this.selectedMsgId = 0x100
        await this.loadMessages()
        this.apiStatus = 'connected'
      } catch (e) {
        this.apiStatus = 'offline'
        useUiStore().showToast(t('toast.serverOffline'), true)
      }
    },

    // ═══════════════════════════════════════════
    // 区域 A：数据操作（Data Operations）
    // ═══════════════════════════════════════════

    // ── 报文加载与选择 ──

    async loadMessages() {
      const t0 = performance.now()
      try {
        this.messages = await api('GET', '/api/messages')
        if (this.selectedMsgId != null) {
          await this.loadSelectedMessage()
        }
        await this._checkModifiedStatus()
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    async _checkModifiedStatus() {
      try {
        const status = await api('GET', '/api/status')
        const elapsed = Date.now() - this.modifiedAt
        if (elapsed > 1500) {
          this.modified = status.modified || false
        }
      } catch (_) {
        /* ignore */
      }
    },

    _scheduleModifiedCheck() {
      this.modified = true
      this.modifiedAt = Date.now()
      setTimeout(() => this._checkModifiedStatus(), 2000)
    },

    async selectMessage(id) {
      this.selectedMsgId = id
      // 乐观更新：立即清空旧缓存，让 UI 显示加载中
      this.messageCache[id] = null
      // 异步加载，不阻塞 UI
      this.loadSelectedMessage()
    },

    async loadSelectedMessage() {
      if (this.selectedMsgId == null) return
      try {
        const msg = await api('GET', `/api/messages/${this.selectedMsgId}`)
        this.messageCache[this.selectedMsgId] = msg
        this.loadSignalErrors()
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    async loadSignalErrors() {
      if (this.selectedMsgId == null) return
      try {
        const errors = await api('GET', `/api/messages/${this.selectedMsgId}/signal-errors`)
        this.signalErrors = errors || []
      } catch (_) {
        this.signalErrors = []
      }
    },

    // ── 报文 CRUD ──

    async autoFixSignal(sigUuid, newStartBit) {
      if (this.selectedMsgId == null) return
      await this.updateSignal(sigUuid, 'start_bit', newStartBit)
    },

    toggleLayoutView() {
      this.layoutViewMode = !this.layoutViewMode
      this.selectedSignalUuid = null
    },

    selectLayoutSignal(uuid) {
      this.selectedSignalUuid = this.selectedSignalUuid === uuid ? null : uuid
    },

    async moveSignalByLayout(sigUuid, newStartBit) {
      await this.updateSignal(sigUuid, 'start_bit', newStartBit)
    },

    async resizeSignalByLayout(sigUuid, newLength) {
      await this.updateSignal(sigUuid, 'length', newLength)
    },

    /**
     * 添加报文（乐观更新模式）
     * 先更新本地状态再发送 API，失败时回滚
     * @returns {Promise<void>}
     */
    async addMessage() {
      const id = 0x300 + this.messages.length
      const name = `NewMessage${this.messages.length + 1}`

      // 乐观更新：立即更新 UI
      const newMsg = {
        id, name, dlc: 8, cycle_time: 0, sender: '',
        signal_count: 0, id_hex: `0x${id.toString(16).toUpperCase()}`
      }
      this.messages.push(newMsg)
      this.messageCache[id] = { id, name, dlc: 8, cycle_time: 0, sender: '', comment: '', signals: [] }
      this.selectedMsgId = id
      this.modified = true
      this.modifiedAt = Date.now()

      // 异步发送 API 请求，不阻塞 UI
      try {
        await api('POST', '/api/messages', {
          id: `0x${id.toString(16)}`, name,
          dlc: 8, cycle_time: 0, sender: '', signals: [],
        })

        // API 成功后入栈（用于撤销删除）
        this.pushUndo({
          type: 'message_add',
          msgId: id,
          data: { id, name, dlc: 8, cycle_time: 0, sender: '', signals: [] }
        })

        useUiStore().showToast(t('toast.messageAdded'))
      } catch (e) {
        // 失败时回滚
        this.messages = this.messages.filter(m => m.id !== id)
        delete this.messageCache[id]
        useUiStore().showToast(e.message, true)
      }
    },

    async deleteMessage(id) {
      const msg = this.messageCache[id]
      if (msg) this.pushUndo({ type: 'message_delete', data: msg })

      // 乐观更新
      this.messages = this.messages.filter(m => m.id !== id)
      delete this.messageCache[id]
      if (this.selectedMsgId === id) this.selectedMsgId = null
      this.modified = true
      this.modifiedAt = Date.now()

      // 异步发送
      try {
        await api('DELETE', `/api/messages/${id}`)
        useUiStore().showToast(t('toast.messageDeleted'))
      } catch (e) {
        // 失败时回滚
        if (msg) {
          this.messages.push({ id: msg.id, name: msg.name, signal_count: msg.signals.length, id_hex: `0x${msg.id.toString(16).toUpperCase()}` })
          this.messageCache[id] = msg
        }
        useUiStore().showToast(e.message, true)
      }
    },

    async updateMessageField(field, value) {
      if (this.selectedMsgId == null) return

      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return

      // 获取旧值（统一为字符串比较，避免类型差异）
      const oldValue = msg[field]
      const oldValueStr = oldValue != null ? String(oldValue) : ''
      const newValueStr = value != null ? String(value) : ''

      // 值变化时入栈（乐观更新之前）
      if (oldValueStr !== newValueStr) {
        this.pushUndo({
          type: 'message_update',
          msgId: this.selectedMsgId,
          prev: { [field]: oldValue },
          next: { [field]: value }
        })
      }

      // 乐观更新
      const oldMessages = [...this.messages]
      const oldCache = this.messageCache[this.selectedMsgId]
      const idx = this.messages.findIndex(m => m.id === this.selectedMsgId)
      if (idx >= 0) {
        this.messages[idx] = { ...this.messages[idx], [field]: value }
      }
      if (oldCache) {
        this.messageCache[this.selectedMsgId] = { ...oldCache, [field]: value }
      }
      this.modified = true
      this.modifiedAt = Date.now()

      // 异步发送
      try {
        await api('PUT', `/api/messages/${this.selectedMsgId}`, { [field]: value })
      } catch (e) {
        // 回滚
        this.messages = oldMessages
        this.messageCache[this.selectedMsgId] = oldCache
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 添加信号（乐观更新 + client UUID 替换）
     * 使用前端生成的临时 UUID 乐观更新 UI，API 成功后替换为后端真实 UUID
     * @param {Object} signalData - 信号初始数据
     * @returns {Promise<void>}
     */
    async addSignal(signalData) {
      if (this.selectedMsgId == null) return

      // 补充完整默认值，确保 UI 上所有字段都有值
      const fullData = {
        name: 'NewSignal',
        start_bit: 0,
        length: 8,
        byte_order: 'motorola',
        factor: 1.0,
        offset: 0.0,
        min_val: 0.0,
        max_val: 0.0,
        unit: '',
        comment: '',
        ...signalData,
      }

      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return
      const clientUuid = crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(16).slice(2, 10)
      const newSig = { uuid: clientUuid, ...fullData }

      // 乐观更新
      const oldSignals = [...msg.signals]
      msg.signals = [...msg.signals, newSig]
      const idx = this.messages.findIndex(m => m.id === this.selectedMsgId)
      const oldMsgEntry = idx >= 0 ? this.messages[idx] : null
      if (idx >= 0) {
        this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
      }
      markModified(this)

      // 异步发送
      try {
        const result = await api('POST', `/api/messages/${this.selectedMsgId}/signals`, fullData)
        // 用后端返回的完整数据（含正确 uuid）替换乐观更新的信号
        const sigIdx = msg.signals.findIndex(s => s.uuid === clientUuid)
        if (sigIdx >= 0 && result) {
          msg.signals[sigIdx] = result
        }

        // API 成功后入栈（使用后端返回的真实 UUID）
        if (result && result.uuid) {
          this.pushUndo({
            type: 'signal_add',
            msgId: this.selectedMsgId,
            sigUuid: result.uuid,
            data: result
          })
        }

        useUiStore().showToast(t('toast.signalAdded'))
        this.loadSignalErrors()
      } catch (e) {
        // 回滚（仅针对真正的 API 失败，如网络/404；验证错误不再被后端拒绝）
        msg.signals = oldSignals
        if (oldMsgEntry) {
          this.messages[idx] = oldMsgEntry
        }
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 更新信号属性（乐观更新模式）
     * 值变化时先入撤销栈，再更新本地状态，异步发送 API
     * @param {string} sigUuid - 信号 UUID
     * @param {string} field - 字段名
     * @param {any} value - 新值
     * @returns {Promise<void>}
     */
    async updateSignal(sigUuid, field, value) {
      if (this.selectedMsgId == null) return

      // 乐观更新
      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return
      const sig = msg.signals.find(s => s.uuid === sigUuid)
      if (!sig) return
      const oldVal = sig[field]

      // 统一为字符串比较，避免类型差异（如输入框返回字符串 "16"，旧值是数字 16）
      const oldValStr = oldVal != null ? String(oldVal) : ''
      const newValStr = value != null ? String(value) : ''

      // 值变化时入栈（乐观更新之前）
      if (oldValStr !== newValStr) {
        this.pushUndo({
          type: 'signal_update',
          msgId: this.selectedMsgId,
          sigUuid,
          prev: { [field]: oldVal },
          next: { [field]: value }
        })
      }

      sig[field] = value
      markModified(this)

      // 异步发送
      try {
        await api('PUT', `/api/messages/${this.selectedMsgId}/signals/${sigUuid}`, { [field]: value })
        this.loadSignalErrors()
      } catch (e) {
        // 回滚（仅针对真正的 API 失败；验证错误不再被后端拒绝）
        sig[field] = oldVal
        useUiStore().showToast(e.message, true)
      }
    },

    async deleteSignal(sigUuid) {
      if (this.selectedMsgId == null) return

      const msg = this.selectedMessage
      const sig = msg ? msg.signals.find(s => s.uuid === sigUuid) : null
      if (sig) {
        this.pushUndo({ type: 'signal_delete', msgId: this.selectedMsgId, data: JSON.parse(JSON.stringify(sig)) })
      }

      // 乐观更新
      if (msg) {
        msg.signals = msg.signals.filter(s => s.uuid !== sigUuid)
      }
      const idx = this.messages.findIndex(m => m.id === this.selectedMsgId)
      if (idx >= 0 && msg) {
        this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
      }
      markModified(this)

      // 异步发送
      try {
        await api('DELETE', `/api/messages/${this.selectedMsgId}/signals/${sigUuid}`)
        useUiStore().showToast(t('toast.signalDeleted'))
        this.loadSignalErrors()
      } catch (e) {
        // 回滚
        if (sig && msg) {
          msg.signals.push(sig)
          this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
        }
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 批量添加信号（乐观更新 + 并发 API）
     * 所有信号先本地乐观更新，然后并发发送 API 请求
     * @param {Object} params - 批量参数
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
      markModified(this)
      this.isLoading = true

      // 异步批量发送
      let created = 0
      const results = [] // 收集后端返回的完整信号数据（含真实 UUID）
      try {
        const promises = newSigs.map(sig =>
          api('POST', `/api/messages/${this.selectedMsgId}/signals`, {
            name: sig.name, start_bit: sig.start_bit, length: sig.length,
            byte_order: sig.byte_order, factor: sig.factor, offset: sig.offset,
            min_val: sig.min_val, max_val: sig.max_val, unit: sig.unit, comment: sig.comment,
          }).then(result => {
            created++
            if (result && result.uuid) {
              results.push({ uuid: result.uuid, data: result })
              // 替换乐观更新中的 clientUuid 为真实 UUID
              const idxInMsg = msg.signals.findIndex(s => s.uuid === sig.uuid)
              if (idxInMsg >= 0) {
                msg.signals[idxInMsg] = result
              }
            }
          }).catch(e => {
            console.error('[STORE] batchAddSignals() 单个信号创建失败:', sig.name, e)
          })
        )
        await Promise.all(promises)

        // API 成功后入栈（仅对成功创建的信号）
        if (results.length > 0) {
          this.pushUndo({
            type: 'batch_signal_add',
            msgId: this.selectedMsgId,
            signals: results
          })
        }

        useUiStore().showToast(t('toast.batchCreated', { count: created }))
      } catch (e) {
        useUiStore().showToast(t('toast.batchFailed', { idx: created + 1, msg: e.message }), true)
      } finally {
        this.isLoading = false
        this.loadSignalErrors()
      }
    },

    async checkApiHealth() {
      try {
        await api('GET', '/api/status')
        this.apiStatus = 'connected'
      } catch (_) {
        this.apiStatus = 'offline'
      }
    },

    // ── Session History ──

    async loadSessionHistory() {
      try {
        const data = await api('GET', '/api/sessions')
        this.sessionHistory = data || []
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    async loadHistorySession(sessionId) {
      // 乐观更新：立即清空状态，显示加载中
      this.selectedMsgId = null
      this.messageCache = {}
      this.messages = []
      this.isLoading = true

      try {
        const data = await api('POST', `/api/session/${sessionId}/load`)
        const sid = data.session_id
        setSessionId(sid)
        addRecentSession(sid, data.file_name || '')
        this.currentFileName = data.file_name || ''

        // 异步加载消息列表，不阻塞 UI
        this.loadMessages()
        useUiStore().showToast(t('toast.sessionLoaded'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      } finally {
        this.isLoading = false
      }
    },

    async deleteHistorySession(sessionId) {
      try {
        await api('DELETE', `/api/session/${sessionId}`)
        this.sessionHistory = this.sessionHistory.filter(s => s.session_id !== sessionId)
        removeRecentSession(sessionId)
        useUiStore().showToast(t('toast.sessionDeleted'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    async renameSession(name) {
      try {
        const data = await api('PUT', '/api/session', { name })
        this.currentFileName = data.file_name || ''
        this._scheduleModifiedCheck()
        useUiStore().showToast(t('toast.renamed'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    async createNewSession(name = 'Untitled') {
      try {
        const data = await api('POST', '/api/new', { name })
        const sid = data.session_id
        setSessionId(sid)
        addRecentSession(sid, data.name + '.toml')
        this.currentFileName = data.name + '.toml'
        this.selectedMsgId = null
        this.messageCache = {}
        this.messages = []
        this.modified = false
        useUiStore().showToast(t('toast.newSessionCreated'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    // ═══════════════════════════════════════════
    // 区域 D：剪贴板（Clipboard）
    // ═══════════════════════════════════════════

    copySignal(sigUuid) {
      const msg = this.selectedMessage
      if (!msg) return
      const sig = msg.signals.find(s => s.uuid === sigUuid)
      if (!sig) return
      this.clipboard = { type: 'signal', data: JSON.parse(JSON.stringify(sig)) }
      useUiStore().showToast(t('toast.signalCopied'))
    },

    async cutSignal(sigUuid) {
      this.copySignal(sigUuid)
      await this.deleteSignal(sigUuid)
      useUiStore().showToast(t('toast.signalCut'))
    },

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
        await api('POST', '/api/messages', msg)
        this.selectedMsgId = maxId
        await this.loadMessages()
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
        await api('POST', '/api/messages', {
          id: `0x${maxId.toString(16)}`,
          name: orig.name + '_copy',
          dlc: orig.dlc,
          cycle_time: orig.cycle_time,
          sender: orig.sender,
          comment: orig.comment,
          signals: orig.signals.map(s => ({ ...s })),
        })
        this.selectedMsgId = maxId
        await this.loadMessages()
        useUiStore().showToast(t('toast.messageDuplicated'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },
  },
})
