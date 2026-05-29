import { defineStore } from 'pinia'
import { api, setSessionId, clearSession } from '../api/client.js'
import { t } from '../i18n.js'

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
    undoStack: [],
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

    // ── Undo ──

    pushUndo(snapshot) {
      this.undoStack.push(snapshot)
      if (this.undoStack.length > 50) this.undoStack.shift()
    },

    async undo() {
      if (this.undoStack.length === 0) {
        this.showToast(t('toast.undoEmpty'))
        return
      }
      const snap = this.undoStack.pop()
      try {
        if (snap.type === 'message_delete') {
          await api('POST', '/api/messages', snap.data)
        } else if (snap.type === 'signal_delete') {
          await api('POST', `/api/messages/${snap.msgId}/signals`, snap.data)
        } else if (snap.type === 'message_update') {
          await api('PUT', `/api/messages/${snap.msgId}`, snap.prev)
        } else if (snap.type === 'signal_update') {
          await api('PUT', `/api/messages/${snap.msgId}/signals/${snap.sigIdx}`, snap.prev)
        }
        await this.loadMessages()
        if (this.selectedMsgId != null) await this.loadSelectedMessage()
        this.showToast(t('toast.undoSuccess'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async initSession() {
      const sid = localStorage.getItem('canmatrix_session_id')
      if (sid) {
        try {
          const data = await api('GET', `/api/session/${sid}`)
          if (data && data.db) {
            this.currentFileName = data.file_name || ''
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
        this.currentFileName = session.file_name || ''

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
      try {
        this.messages = await api('GET', '/api/messages')
        if (this.selectedMsgId != null) {
          await this.loadSelectedMessage()
        }
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
      this.selectedMsgId = id
      await this.loadSelectedMessage()
    },

    async loadSelectedMessage() {
      if (this.selectedMsgId == null) return
      try {
        const msg = await api('GET', `/api/messages/${this.selectedMsgId}`)
        this.messageCache[this.selectedMsgId] = msg
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async addMessage() {
      try {
        const id = 0x300 + this.messages.length
        const msg = await api('POST', '/api/messages', {
          id: `0x${id.toString(16)}`, name: `NewMessage${this.messages.length + 1}`,
          dlc: 8, cycle_time: 0, sender: '', signals: [],
        })
        await this.loadMessages()
        this.selectedMsgId = msg.id
        this._scheduleModifiedCheck()
        this.showToast(t('toast.messageAdded'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async deleteMessage(id) {
      try {
        const msg = this.messageCache[id]
        if (msg) this.pushUndo({ type: 'message_delete', data: msg })
        await api('DELETE', `/api/messages/${id}`)
        if (this.selectedMsgId === id) this.selectedMsgId = null
        delete this.messageCache[id]
        await this.loadMessages()
        this._scheduleModifiedCheck()
        this.showToast(t('toast.messageDeleted'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async updateMessageField(field, value) {
      if (this.selectedMsgId == null) return
      try {
        await api('PUT', `/api/messages/${this.selectedMsgId}`, { [field]: value })
        this._scheduleModifiedCheck()
        await this.loadSelectedMessage()
        await this.loadMessages()
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async addSignal(signalData) {
      if (this.selectedMsgId == null) return
      try {
        await api('POST', `/api/messages/${this.selectedMsgId}/signals`, signalData)
        this.modified = true
        this.modifiedAt = Date.now()
        await this.loadSelectedMessage()
        await this.loadMessages()
        this.showToast(t('toast.signalAdded'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async updateSignal(idx, field, value) {
      if (this.selectedMsgId == null) return
      try {
        await api('PUT', `/api/messages/${this.selectedMsgId}/signals/${idx}`, { [field]: value })
        this._scheduleModifiedCheck()
        await this.loadSelectedMessage()
        await this.loadMessages()
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async deleteSignal(idx) {
      if (this.selectedMsgId == null) return
      try {
        const msg = this.selectedMessage
        if (msg && msg.signals[idx]) {
          this.pushUndo({ type: 'signal_delete', msgId: this.selectedMsgId, data: JSON.parse(JSON.stringify(msg.signals[idx])) })
        }
        await api('DELETE', `/api/messages/${this.selectedMsgId}/signals/${idx}`)
        this._scheduleModifiedCheck()
        await this.loadSelectedMessage()
        await this.loadMessages()
        this.showToast(t('toast.signalDeleted'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async batchAddSignals({ nameTemplate, count, startNum, startBit, bitStep, length, byteOrder, factor, offset, minVal, maxVal, unit, commentTemplate }) {
      if (this.selectedMsgId == null) return
      const { expandTemplate } = await import('../utils/format.js')
      const lastEnd = startBit + (count - 1) * bitStep + length
      if (lastEnd > 64) {
        this.showToast(`Last signal ends at bit ${lastEnd - 1}, exceeds 63`, true)
        return
      }
      this.isLoading = true
      let created = 0
      try {
        for (let i = 0; i < count; i++) {
          const n = startNum + i
          const name = expandTemplate(nameTemplate, n)
          const comment = commentTemplate ? expandTemplate(commentTemplate, n) : ''
          const sb = startBit + i * bitStep
          await api('POST', `/api/messages/${this.selectedMsgId}/signals`, {
            name, start_bit: sb, length, byte_order: byteOrder,
            factor, offset, min_val: minVal, max_val: maxVal, unit, comment,
          })
          created++
        }
        delete this.messageCache[this.selectedMsgId]
        await this.loadSelectedMessage()
        await this.loadMessages()
        this._scheduleModifiedCheck()
        this.showToast(t('toast.batchCreated', { count: created }))
      } catch (e) {
        this.showToast(t('toast.batchFailed', { idx: created + 1, msg: e.message }), true)
      } finally {
        this.isLoading = false
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
      try {
        const data = await api('POST', `/api/session/${sessionId}/load`)
        const sid = data.session_id
        setSessionId(sid)
        this.currentFileName = data.file_name || ''
        this.selectedMsgId = null
        this.messageCache = {}
        await this.loadMessages()
        this.showToast(t('toast.sessionLoaded'))
      } catch (e) {
        this.showToast(e.message, true)
      }
    },

    async deleteHistorySession(sessionId) {
      try {
        await api('DELETE', `/api/session/${sessionId}`)
        this.sessionHistory = this.sessionHistory.filter(s => s.session_id !== sessionId)
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

    copySignal(idx) {
      const msg = this.selectedMessage
      if (!msg) return
      this.clipboard = { type: 'signal', data: JSON.parse(JSON.stringify(msg.signals[idx])) }
      this.showToast(t('toast.signalCopied'))
    },

    async cutSignal(idx) {
      this.copySignal(idx)
      await this.deleteSignal(idx)
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
