import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'
import { useMessagesStore } from './messages.js'
import { useSignalsStore } from './signals.js'
import { generateMessageId } from '../utils/storeHelpers.js'

export const useClipboardStore = defineStore('clipboard', {
  state: () => ({
    clipboard: null,
  }),

  actions: {
    /**
     * 复制信号到剪贴板
     */
    copySignal(sigUuid) {
      const editor = useEditorStore()
      const msg = editor.selectedMessage
      if (!msg) return
      const sig = msg.signals.find(s => s.uuid === sigUuid)
      if (!sig) return
      this.clipboard = { type: 'signal', data: JSON.parse(JSON.stringify(sig)) }
      useUiStore().showToast(t('toast.signalCopied'))
    },

    /**
     * 剪切信号到剪贴板（复制 + 删除）
     */
    async cutSignal(sigUuid) {
      const signals = useSignalsStore()
      this.copySignal(sigUuid)
      await signals.deleteSignal(sigUuid)
      useUiStore().showToast(t('toast.signalCut'))
    },

    /**
     * 从剪贴板粘贴信号
     */
    async pasteSignal() {
      if (!this.clipboard || this.clipboard.type !== 'signal') return
      const signals = useSignalsStore()
      const sig = JSON.parse(JSON.stringify(this.clipboard.data))
      sig.name = sig.name ? sig.name + '_copy' : 'PastedSig'
      await signals.addSignal(sig)
      useUiStore().showToast(t('toast.signalPasted'))
    },

    /**
     * 复制报文到剪贴板
     */
    copyMessage() {
      const editor = useEditorStore()
      const msg = editor.selectedMessage
      if (!msg) return
      this.clipboard = { type: 'message', data: JSON.parse(JSON.stringify(msg)) }
      useUiStore().showToast(t('toast.messageCopied'))
    },

    /**
     * 从剪贴板粘贴报文
     */
    async pasteMessage() {
      if (!this.clipboard || this.clipboard.type !== 'message') return
      const editor = useEditorStore()
      const messages = useMessagesStore()
      const msg = JSON.parse(JSON.stringify(this.clipboard.data))
      msg.id = generateMessageId(editor.messages)
      msg.name = (msg.name || 'PastedMsg') + '_copy'
      try {
        await editor._wsRequest('add_message', { message: msg })
        editor.selectedMsgId = msg.id
        useUiStore().showToast(t('toast.messagePasted'))
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 复制报文
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
