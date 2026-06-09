import { defineStore } from 'pinia'
import { api, setSessionId, clearSession, addRecentSession, removeRecentSession, getSessionId } from '../api/client.js'
import { t } from '../i18n.js'
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
    _modifiedTimer: null,
    logEntries: [],

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
    // 区域 C：撤销/重做（Undo/Redo）- 后端管理
    // ═══════════════════════════════════════════

    /**
     * 执行撤销操作（调用后端 API）
     * API 成功后刷新数据
     * @returns {Promise<void>}
     */
    async undo() {
      try {
        const result = await api('POST', '/api/undo')
        if (result.success) {
          // 刷新数据
          await this.loadMessages()
          if (this.selectedMsgId != null) {
            await this.loadSelectedMessage()
          }
          // 同步计数
          await this._syncUndoRedoCounts()
          useUiStore().showToast('撤销成功', false)
          this.addLogEntry('undo', '撤销操作')
        }
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
        const result = await api('POST', '/api/redo')
        if (result.success) {
          // 刷新数据
          await this.loadMessages()
          if (this.selectedMsgId != null) {
            await this.loadSelectedMessage()
          }
          // 同步计数
          await this._syncUndoRedoCounts()
          useUiStore().showToast('重做成功', false)
          this.addLogEntry('redo', '重做操作')
        }
      } catch (e) {
        console.error('[STORE] redo() failed:', e)
        useUiStore().showToast(e.message || '重做失败', true)
      }
    },

    /**
     * 同步撤销/重做计数器（从后端获取）
     * @private
     */
    async _syncUndoRedoCounts() {
      try {
        const status = await api('GET', '/api/status')
        this.undoCount = status.undo_count || 0
        this.redoCount = status.redo_count || 0
      } catch (_) {
        // 忽略错误，保持当前计数
        this.undoCount = 0
        this.redoCount = 0
      }
    },

    /**
     * 清空撤销/重做栈（切换会话时调用）
     * 同时清理 modified 定时器
     */
    clearUndoStack() {
      this._syncUndoRedoCounts()
      // 切换会话时清理 modified 定时器
      if (this._modifiedTimer) {
        clearTimeout(this._modifiedTimer)
        this._modifiedTimer = null
      }
    },

    // ═══════════════════════════════════════════
    // 区域 B：会话管理（Session Management）
    // ═══════════════════════════════════════════

    /**
     * 初始化会话（从 sessionStorage 恢复）
     * 如果 session 有效，则加载报文数据
     * @returns {Promise<void>}
     */
    async initSession() {
      const sid = sessionStorage.getItem('canmatrix_session_id')
      if (sid) {
        try {
          const data = await api('GET', `/api/session/${sid}`)
          if (data && data.session_id) {
            this.currentFileName = data.file_name || ''
            this.modified = false
            this.modifiedAt = 0
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

    /**
     * 创建 Demo 会话（无需后端）
     * 用于离线演示和测试
     * @returns {Promise<void>}
     */
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

    /**
     * 手动保存当前会话
     * 调用后端 POST /api/save 立即保存数据到磁盘
     * @returns {Promise<boolean>} 保存是否成功
     */
    async saveSession() {
      try {
        await api('POST', '/api/save')
        this.modified = false
        this.modifiedAt = 0
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

    /**
     * 检查后端修改状态
     * 仅在本地修改超过 1.5 秒后才同步后端状态，避免覆盖本地修改
     * @returns {Promise<void>}
     * @private
     */
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

    /**
     * 调度修改状态检查
     * 标记本地为已修改，并在 2 秒后检查后端状态
     * 清除之前的定时器，避免积累多个未执行的检查
     * @private
     */
    _scheduleModifiedCheck() {
      this.modified = true
      this.modifiedAt = Date.now()
      // 清除之前的定时器，避免积累多个未执行的检查
      if (this._modifiedTimer) clearTimeout(this._modifiedTimer)
      this._modifiedTimer = setTimeout(() => {
        this._modifiedTimer = null
        this._checkModifiedStatus()
      }, 2000)
    },

    /**
     * 选中报文（乐观更新模式）
     * 立即清空旧缓存让 UI 显示加载中，异步加载报文详情
     * @param {number} id - 报文 ID
     * @returns {Promise<void>}
     */
    async selectMessage(id) {
      this.selectedMsgId = id
      // 乐观更新：立即清空旧缓存，让 UI 显示加载中
      this.messageCache[id] = null
      // 异步加载，不阻塞 UI
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
        const msg = await api('GET', `/api/messages/${this.selectedMsgId}`)
        this.messageCache[this.selectedMsgId] = msg
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
        const errors = await api('GET', `/api/messages/${this.selectedMsgId}/signal-errors`)
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

        // 后端已自动推入撤销栈

        useUiStore().showToast(t('toast.messageAdded'))
      } catch (e) {
        // 失败时回滚
        this.messages = this.messages.filter(m => m.id !== id)
        delete this.messageCache[id]
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 删除报文（乐观更新模式）
     * 先更新本地状态再发送 API，失败时回滚
     * @param {number} id - 报文 ID
     * @returns {Promise<void>}
     */
    async deleteMessage(id) {
      // 后端已自动推入撤销栈

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

    /**
     * 更新报文属性（乐观更新模式）
     * 值变化时先入撤销栈，再更新本地状态，异步发送 API
     * @param {string} field - 字段名
     * @param {any} value - 新值
     * @returns {Promise<void>}
     */
    async updateMessageField(field, value) {
      if (this.selectedMsgId == null) return

      const msg = this.messageCache[this.selectedMsgId]
      if (!msg) return

      // 获取旧值（统一为字符串比较，避免类型差异）
      const oldValue = msg[field]
      const oldValueStr = oldValue != null ? String(oldValue) : ''
      const newValueStr = value != null ? String(value) : ''

      // 后端已自动推入撤销栈

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

        // 后端已自动推入撤销栈

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

      // 后端已自动推入撤销栈

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

    /**
     * 删除信号（乐观更新模式）
     * 先更新本地状态再发送 API，失败时回滚
     * @param {string} sigUuid - 信号 UUID
     * @returns {Promise<void>}
     */
    async deleteSignal(sigUuid) {
      if (this.selectedMsgId == null) return

      // 后端已自动推入撤销栈

      const msg = this.selectedMessage
      const sig = msg ? msg.signals.find(s => s.uuid === sigUuid) : null

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
     * API 成功后替换 clientUuid 为真实 UUID，并入撤销栈
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

        // 后端已自动推入撤销栈

        useUiStore().showToast(t('toast.batchCreated', { count: created }))
      } catch (e) {
        useUiStore().showToast(t('toast.batchFailed', { idx: created + 1, msg: e.message }), true)
      } finally {
        this.isLoading = false
        this.loadSignalErrors()
      }
    },

    /**
     * 检查 API 健康状态
     * 由 App.vue 定时调用（每 15 秒）
     * @returns {Promise<void>}
     */
    async checkApiHealth() {
      try {
        await api('GET', '/api/status')
        this.apiStatus = 'connected'
      } catch (_) {
        this.apiStatus = 'offline'
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

    // ── Session History ──

    async loadSessionHistory() {
      try {
        const data = await api('GET', '/api/sessions')
        this.sessionHistory = data || []
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 加载历史会话
     * @param {string} sessionId - 会话 ID
     * @returns {Promise<void>}
     */
    async loadHistorySession(sessionId) {
      // 乐观更新：立即清空状态，显示加载中
      this.selectedMsgId = null
      this.messageCache = {}
      this.messages = []
      this.signalErrors = []
      this.modified = false
      this.modifiedAt = 0
      this.clearUndoStack()
      this.isLoading = true

      try {
        const currentSid = getSessionId()
        const data = await api('POST', `/api/session/${sessionId}/load`, null, { 'X-Session-Id': currentSid })
        const sid = data.session_id
        setSessionId(sid)
        addRecentSession(sid, data.file_name || '')
        this.currentFileName = data.file_name || ''

        // 异步加载消息列表，不阻塞 UI
        this.loadMessages()
        useUiStore().showToast(t('toast.sessionLoaded'))
      } catch (e) {
        // 409 表示文件被锁定，转换为友好的错误信息
        if (e.status === 409) {
          e.message = t('toast.noEditPermission')
        } else {
          useUiStore().showToast(e.message, true)
        }
        throw e  // 重新抛出，让调用方处理
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
        this.signalErrors = []
        this.modified = false
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
      const data = await api('POST', '/api/new', { name })
      const sid = data.session_id
      setSessionId(sid)
      addRecentSession(sid, data.name + '.toml')
      this.currentFileName = data.name + '.toml'
      this.selectedMsgId = null
      this.messageCache = {}
      this.messages = []
      this.signalErrors = []
      this.modified = false
      this.clearUndoStack()
      return sid
    },

    /**
     * 释放当前 session 的文件锁（返回文件浏览器时调用）
     */
    async releaseSession() {
      const sid = sessionStorage.getItem('canmatrix_session_id')
      if (sid) {
        try {
          await api('POST', '/api/release', null, { 'X-Session-Id': sid })
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
