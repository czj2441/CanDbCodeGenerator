import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'
import { useMessagesStore } from './messages.js'
import { useSignalsStore } from './signals.js'
import { generateMessageId, resolveCopyName } from '../utils/storeHelpers.js'

export const useClipboardStore = defineStore('clipboard', {
  state: () => ({
    clipboard: null,  // { type: 'signal'|'message', items: [...] }
  }),

  actions: {
    // ── 内部复用方法 ──

    /**
     * 将深拷贝后的项目数组存入剪贴板并显示 toast。
     * @param {'signal'|'message'} type
     * @param {Array} items - 已深拷贝的项目数组
     * @param {string} singularToastKey - 单条目时的 i18n key
     * @param {string} pluralToastKey - 多条目时的 i18n key
     */
    _copyToClipboard(type, items, singularToastKey, pluralToastKey) {
      if (!items.length) return
      this.clipboard = { type, items }
      const ui = useUiStore()
      if (items.length === 1) {
        ui.showToast(t(singularToastKey))
      } else {
        ui.showToast(t(pluralToastKey, { count: items.length }))
      }
    },

    // ── 信号方法 ──

    /**
     * 复制信号到剪贴板（支持批量）
     * @param {string[]} sigNames
     */
    copySignals(sigNames) {
      const editor = useEditorStore()
      const msg = editor.selectedMessage
      if (!msg || !sigNames.length) return
      const items = sigNames
        .map(name => msg.signals[name])
        .filter(Boolean)
        .map(sig => JSON.parse(JSON.stringify(sig)))
      this._copyToClipboard('signal', items, 'toast.signalCopied', 'toast.signalsCopied')
    },

    /**
     * 复制单个信号（委托 copySignals）
     */
    copySignal(sigName) {
      this.copySignals([sigName])
    },

    /**
     * 剪切信号到剪贴板（复制 + 删除）
     * @param {string[]} sigNames
     */
    async cutSignals(sigNames) {
      this.copySignals(sigNames)
      if (!this.clipboard) return
      const signals = useSignalsStore()
      await signals.batchDeleteSignals(sigNames)
      const ui = useUiStore()
      if (sigNames.length === 1) {
        ui.showToast(t('toast.signalCut'))
      } else {
        ui.showToast(t('toast.signalsCut', { count: sigNames.length }))
      }
    },

    /**
     * 剪切单个信号（委托 cutSignals）
     */
    cutSignal(sigName) {
      return this.cutSignals([sigName])
    },

    /**
     * 从剪贴板粘贴信号（统一入口，处理单选/多选复制的数据）
     */
    async pasteSignals() {
      if (!this.clipboard || this.clipboard.type !== 'signal') return
      const editor = useEditorStore()
      const msg = editor.selectedMessage
      if (!msg || editor.selectedMsgId == null) return

      // 兼容旧格式 { type, data } → 视为单条目数组
      const sourceItems = this.clipboard.items || [this.clipboard.data]
      if (!sourceItems.length) return

      // 构建已有名称集合（含本批次已分配的，防止内部重名）
      const existingNames = new Set(Object.keys(msg.signals))
      const toPaste = []

      for (const orig of sourceItems) {
        const sig = JSON.parse(JSON.stringify(orig))
        sig.name = resolveCopyName(existingNames, sig.name || 'PastedSig')
        existingNames.add(sig.name)
        // 保持原始 start_bit 不变
        toPaste.push(sig)
      }

      // 逐个调 add_signal（部分失败不阻塞后续）
      let successCount = 0
      for (const sig of toPaste) {
        try {
          await editor._wsRequest('add_signal', { msg_id: editor.selectedMsgId, signal: sig })
          successCount++
        } catch (e) {
          // 单个失败不阻塞，继续粘贴后续信号
        }
      }

      const ui = useUiStore()
      ui.showToast(t('toast.signalsPasted', { count: successCount }))
    },

    // ── 报文方法 ──

    /**
     * 复制报文到剪贴板（支持批量）
     * cache miss 时通过 get_message 预加载完整数据
     * @param {number[]} msgIds
     */
    async copyMessages(msgIds) {
      const editor = useEditorStore()
      if (!msgIds.length) return

      const items = []
      for (const id of msgIds) {
        let detail = editor.messageCache[id]
        // cache miss: 预加载完整数据
        if (!detail) {
          try {
            detail = await editor._wsRequest('get_message', { msg_id: id })
            editor.messageCache[id] = detail
          } catch (e) {
            continue  // 加载失败，跳过此报文
          }
        }
        items.push(JSON.parse(JSON.stringify(detail)))
      }

      this._copyToClipboard('message', items, 'toast.messageCopied', 'toast.messagesCopied')
    },

    /**
     * 复制当前选中的报文（委托 copyMessages）
     */
    copyMessage() {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      return this.copyMessages([editor.selectedMsgId])
    },

    /**
     * 剪切报文到剪贴板（复制 + 删除）
     * @param {number[]} msgIds
     */
    async cutMessages(msgIds) {
      await this.copyMessages(msgIds)
      if (!this.clipboard) return
      const messages = useMessagesStore()
      await messages.batchDeleteMessages(msgIds)
      const ui = useUiStore()
      if (msgIds.length === 1) {
        ui.showToast(t('toast.messageCut'))
      } else {
        ui.showToast(t('toast.messagesCut', { count: msgIds.length }))
      }
    },

    /**
     * 剪切当前选中的报文（委托 cutMessages）
     */
    cutMessage() {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      return this.cutMessages([editor.selectedMsgId])
    },

    /**
     * 从剪贴板粘贴报文（统一入口，处理单选/多选复制的数据）
     */
    async pasteMessages() {
      if (!this.clipboard || this.clipboard.type !== 'message') return
      const editor = useEditorStore()

      // 兼容旧格式
      const sourceItems = this.clipboard.items || [this.clipboard.data]
      if (!sourceItems.length) return

      const existingNames = new Set(Object.values(editor.messages).map(m => m.name))
      let successCount = 0

      for (const orig of sourceItems) {
        const msg = JSON.parse(JSON.stringify(orig))
        // ID 始终需要生成新的（避免与已有报文冲突）
        msg.id = generateMessageId(editor.messages)
        // 名称：无冲突保持原名，冲突加 _copy_N
        msg.name = resolveCopyName(existingNames, msg.name || 'PastedMsg')
        existingNames.add(msg.name)

        try {
          await editor._wsRequest('add_message', { message: msg })
          editor.selectedMsgId = msg.id
          successCount++
        } catch (e) {
          useUiStore().showToast(e.message, true)
        }
      }

      if (successCount > 0) {
        useUiStore().showToast(t('toast.messagesPasted', { count: successCount }))
      }
    },

    // ── 保留的方法 ──

    /**
     * 复制报文（走后端 duplicate_message 端点）
     */
    async duplicateMessage() {
      const editor = useEditorStore()
      const orig = editor.selectedMessage
      if (!orig) return
      const maxId = generateMessageId(editor.messages)
      try {
        await editor._wsRequest('duplicate_message', { msg_id: orig.id, new_id: maxId })
        editor.selectedMsgId = maxId
        useUiStore().showToast(t('toast.messageDuplicated'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },
  },
})
