import { defineStore } from 'pinia'
import { api, setSessionId, clearSession, addRecentSession, removeRecentSession } from '../api/client.js'
import { t } from '../i18n.js'
import { createUndoRedoManager } from '../utils/useUndoRedo.js'

export const useEditorStore = defineStore('editor', {
  state: () => ({
    messages: [],
    selectedMsgId: null,
    messageCache: {},
    currentFileName: '',
    isLoading: false,
    apiStatus: 'connecting',
    modified: false,
    modifiedAt: 0,
    toast: { text: '', isError: false, visible: false },
    batchModalOpen: false,
    clipboard: null,
    contextMenu: { visible: false, x: 0, y: 0, target: null, idx: null },
    historyModalOpen: false,
    sessionHistory: [],
    newConfirmOpen: false,
    theme: localStorage.getItem('canmatrix_theme') || 'dark',
    locale: localStorage.getItem('canmatrix_locale') || 'zh',
    signalErrors: [],
    layoutViewMode: false,
    selectedSignalUuid: null,
    _undoRedo: null, // 撤销/重做管理器实例
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
    showToast(text, isError = false) {
      this.toast = { text, isError, visible: true }
      setTimeout(() => { this.toast.visible = false }, 2000)
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

    // ── 撤销/重做 ──

    initUndoRedo() {
      if (this._undoRedo) return // 已初始化
      this._undoRedo = createUndoRedoManager({
        maxSize: 50,
        onReload: async () => {
          await this.loadMessages()
          if (this.selectedMsgId != null) await this.loadSelectedMessage()
        },
        onToast: (text, isError) => this.showToast(text, isError),
      })
    },

    pushUndo(snapshot) {
      this.initUndoRedo()
      this._undoRedo.pushUndo(snapshot)
    },

    async undo() {
      this.initUndoRedo()
      await this._undoRedo.undo()
    },

    async redo() {
      this.initUndoRedo()
      await this._undoRedo.redo()
    },

    clearUndoStack() {
      if (this._undoRedo) this._undoRedo.clear()
    },

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
            this.showToast(t('toast.restored', { name: data.file_name }))
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
        this.showToast(t('toast.serverOffline'), true)
      }
    },

    async loadMessages() {
      const t0 = performance.now()
      console.log('[STORE] loadMessages() START')
      try {
        console.log('[STORE] loadMessages() API DONE +', (performance.now() - t0).toFixed(1), 'ms)')
        this.messages = await api('GET', '/api/messages')
        if (this.selectedMsgId != null) {
          await this.loadSelectedMessage()
        }
        console.log('[STORE] loadMessages() ALL DONE +', (performance.now() - t0).toFixed(1), 'ms)')
        await this._checkModifiedStatus()
      } catch (e) {
        this.showToast(e.message, true)
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
      const t0 = performance.now()
      this.selectedMsgId = id
      // 乐观更新：立即清空旧缓存，让 UI 显示加载中
      this.messageCache[id] = null
      console.log('[STORE] selectMessage() optimistic DONE +', (performance.now() - t0).toFixed(1), 'ms)')
      // 异步加载，不阻塞 UI
      this.loadSelectedMessage()
    },

    async loadSelectedMessage() {
      if (this.selectedMsgId == null) return
      const t0 = performance.now()
      console.log('[STORE] loadSelectedMessage() START', this.selectedMsgId)
      try {
        const msg = await api('GET', `/api/messages/${this.selectedMsgId}`)
        this.messageCache[this.selectedMsgId] = msg
        console.log('[STORE] loadSelectedMessage() DONE +', (performance.now() - t0).toFixed(1), 'ms)')
        this.loadSignalErrors()
      } catch (e) {
        this.showToast(e.message, true)
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

    async autoFixSignal(sigUuid, newStartBit) {
      if (this.selectedMsgId == null) return
      await this.updateSignal(sigUuid, 'start_bit', newStartBit)
    },

    // ── Layout View ──

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

    async addMessage() {
      const t0 = performance.now()
      console.log(`[STORE] addMessage() START`)

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

      const t1 = performance.now()
      console.log(`[STORE] addMessage() optimistic update DONE (+${(t1 - t0).toFixed(1)}ms)`)

      // 异步发送 API 请求，不阻塞 UI
      try {
        await api('POST', '/api/messages', {
          id: `0x${id.toString(16)}`, name,
          dlc: 8, cycle_time: 0, sender: '', signals: [],
        })
        const t2 = performance.now()
        console.log(`[STORE] addMessage() API response DONE (+${(t2 - t0).toFixed(1)}ms)`)
        this.showToast(t('toast.messageAdded'))
      } catch (e) {
        // 失败时回滚
        this.messages = this.messages.filter(m => m.id !== id)
        delete this.messageCache[id]
        this.showToast(e.message, true)
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
        this.showToast(t('toast.messageDeleted'))
      } catch (e) {
        // 失败时回滚
        if (msg) {
          this.messages.push({ id: msg.id, name: msg.name, signal_count: msg.signals.length, id_hex: `0x${msg.id.toString(16).toUpperCase()}` })
          this.messageCache[id] = msg
        }
        this.showToast(e.message, true)
      }
    },

    async updateMessageField(field, value) {
      if (this.selectedMsgId == null) return

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
        this.showToast(e.message, true)
      }
    },

    async addSignal(signalData) {
      if (this.selectedMsgId == null) return
      const t0 = performance.now()
      console.log('[STORE] addSignal() START', signalData.name || 'unnamed')

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
      this.modified = true
      this.modifiedAt = Date.now()

      console.log('[STORE] addSignal() optimistic DONE +', (performance.now() - t0).toFixed(1), 'ms)')

      // 异步发送
      try {
        const result = await api('POST', `/api/messages/${this.selectedMsgId}/signals`, fullData)
        console.log('[STORE] addSignal() API DONE +', (performance.now() - t0).toFixed(1), 'ms)')
        // 用后端返回的完整数据（含正确 uuid）替换乐观更新的信号
        const sigIdx = msg.signals.findIndex(s => s.uuid === clientUuid)
        if (sigIdx >= 0 && result) {
          msg.signals[sigIdx] = result
        }
        this.showToast(t('toast.signalAdded'))
        this.loadSignalErrors()
      } catch (e) {
        // 回滚（仅针对真正的 API 失败，如网络/404；验证错误不再被后端拒绝）
        msg.signals = oldSignals
        if (oldMsgEntry) {
          this.messages[idx] = oldMsgEntry
        }
        this.showToast(e.message, true)
      }
    },

    async updateSignal(sigUuid, field, value) {
      if (this.selectedMsgId == null) return
      const t0 = performance.now()
      console.log('[STORE] updateSignal()', sigUuid, field, '=', value)

      // 乐观更新
      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return
      const sig = msg.signals.find(s => s.uuid === sigUuid)
      if (!sig) return
      const oldVal = sig[field]
      sig[field] = value
      this.modified = true
      this.modifiedAt = Date.now()

      console.log('[STORE] updateSignal() optimistic DONE +', (performance.now() - t0).toFixed(1), 'ms)')

      // 异步发送
      try {
        await api('PUT', `/api/messages/${this.selectedMsgId}/signals/${sigUuid}`, { [field]: value })
        this.loadSignalErrors()
      } catch (e) {
        // 回滚（仅针对真正的 API 失败；验证错误不再被后端拒绝）
        sig[field] = oldVal
        console.log('[STORE] updateSignal() API DONE +', (performance.now() - t0).toFixed(1), 'ms)')
        this.showToast(e.message, true)
      }
    },

    async deleteSignal(sigUuid) {
      if (this.selectedMsgId == null) return
      const t0 = performance.now()
      console.log('[STORE] deleteSignal()', sigUuid)

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
      this.modified = true
      this.modifiedAt = Date.now()

      console.log('[STORE] deleteSignal() optimistic DONE +', (performance.now() - t0).toFixed(1), 'ms)')

      // 异步发送
      try {
        await api('DELETE', `/api/messages/${this.selectedMsgId}/signals/${sigUuid}`)
        console.log('[STORE] deleteSignal() API DONE +', (performance.now() - t0).toFixed(1), 'ms)')
        this.showToast(t('toast.signalDeleted'))
        this.loadSignalErrors()
      } catch (e) {
        // 回滚
        if (sig && msg) {
          msg.signals.push(sig)
          this.messages[idx] = { ...this.messages[idx], signal_count: msg.signals.length }
        }
        this.showToast(e.message, true)
      }
    },

    async batchAddSignals({ nameTemplate, count, startNum, startBit, bitStep, length, byteOrder, factor, offset, minVal, maxVal, unit, commentTemplate }) {
      if (this.selectedMsgId == null) return
      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return
      const { expandTemplate } = await import('../utils/format.js')
      const maxBits = msg.dlc * 8
      const lastEnd = startBit + (count - 1) * bitStep + length
      // 简单预检查（Intel 格式估算；Motorola 的实际边界由后端验证）
      if (lastEnd > maxBits) {
        this.showToast(`Last signal ends at bit ${lastEnd - 1}, exceeds ${maxBits - 1}`, true)
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
      this.modified = true
      this.modifiedAt = Date.now()
      this.isLoading = true

      // 异步批量发送
      let created = 0
      try {
        const promises = newSigs.map(sig =>
          api('POST', `/api/messages/${this.selectedMsgId}/signals`, {
            name: sig.name, start_bit: sig.start_bit, length: sig.length,
            byte_order: sig.byte_order, factor: sig.factor, offset: sig.offset,
            min_val: sig.min_val, max_val: sig.max_val, unit: sig.unit, comment: sig.comment,
          }).then(() => { created++ }).catch(() => {})
        )
        await Promise.all(promises)
        this.showToast(t('toast.batchCreated', { count: created }))
      } catch (e) {
        this.showToast(t('toast.batchFailed', { idx: created + 1, msg: e.message }), true)
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
        this.showToast(e.message, true)
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
        this.showToast(t('toast.sessionLoaded'))
      } catch (e) {
        this.showToast(e.message, true)
      } finally {
        this.isLoading = false
      }
    },

    async deleteHistorySession(sessionId) {
      try {
        await api('DELETE', `/api/session/${sessionId}`)
        this.sessionHistory = this.sessionHistory.filter(s => s.session_id !== sessionId)
        removeRecentSession(sessionId)
        this.showToast(t('toast.sessionDeleted'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async renameSession(name) {
      try {
        const data = await api('PUT', '/api/session', { name })
        this.currentFileName = data.file_name || ''
        this._scheduleModifiedCheck()
        this.showToast(t('toast.renamed'))
      } catch (e) {
        this.showToast(e.message, true)
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
        this.showToast(t('toast.newSessionCreated'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    // ── Clipboard ──

    copySignal(sigUuid) {
      const msg = this.selectedMessage
      if (!msg) return
      const sig = msg.signals.find(s => s.uuid === sigUuid)
      if (!sig) return
      this.clipboard = { type: 'signal', data: JSON.parse(JSON.stringify(sig)) }
      this.showToast(t('toast.signalCopied'))
    },

    async cutSignal(sigUuid) {
      this.copySignal(sigUuid)
      await this.deleteSignal(sigUuid)
      this.showToast(t('toast.signalCut'))
    },

    async pasteSignal() {
      if (!this.clipboard || this.clipboard.type !== 'signal' || this.selectedMsgId == null) return
      const sig = JSON.parse(JSON.stringify(this.clipboard.data))
      sig.name = sig.name ? sig.name + '_copy' : 'PastedSig'
      await this.addSignal(sig)
      this.showToast(t('toast.signalPasted'))
    },

    copyMessage() {
      const msg = this.selectedMessage
      if (!msg) return
      this.clipboard = { type: 'message', data: JSON.parse(JSON.stringify(msg)) }
      this.showToast(t('toast.messageCopied'))
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
        this.showToast(t('toast.messagePasted'))
      } catch (e) {
        this.showToast(e.message, true)
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
        this.showToast(t('toast.messageDuplicated'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },
  },
})
