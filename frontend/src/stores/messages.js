import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'
import { useSignalsStore } from './signals.js'
import { translateError, generateMessageId } from '../utils/storeHelpers.js'

export const useMessagesStore = defineStore('messages', {
  actions: {
    /**
     * 加载所有报文列表
     */
    async loadMessages() {
      const editor = useEditorStore()
      try {
        editor.messages = await editor._wsRequest('get_messages')
        if (editor.selectedMsgId != null) {
          await this.loadSelectedMessage()
        }
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 选中报文
     */
    selectMessage(id) {
      const editor = useEditorStore()
      editor.selectedMsgId = id
      editor.messageCache[id] = null
      this.loadSelectedMessage()
    },

    /**
     * 加载选中报文的详细信息（含信号列表）
     */
    async loadSelectedMessage() {
      const editor = useEditorStore()
      const signals = useSignalsStore()
      if (editor.selectedMsgId == null) return
      try {
        editor.messageCache[editor.selectedMsgId] = await editor._wsRequest('get_message', { msg_id: editor.selectedMsgId })
        signals.loadSignalErrors()
      } catch (e) {
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 添加报文（等待服务器模式）
     */
    async addMessage() {
      const editor = useEditorStore()
      const id = generateMessageId(editor.messages)
      const name = `NewMessage${id - 0x300 + 1}`

      try {
        const result = await editor._wsRequest('add_message', {
          message: { id, name, dlc: 8, cycle_time: 0, sender: '', is_fd: false, signals: [] }
        })
        if (result?.id != null) {
          editor.messageCache[result.id] = result
          editor.selectedMsgId = result.id
        }
        useUiStore().showToast(t('toast.messageAdded'))
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      }
    },

    /**
     * 删除报文（等待服务器模式）
     */
    async deleteMessage(id) {
      const editor = useEditorStore()
      try {
        await editor._wsRequest('delete_message', { msg_id: id })
        useUiStore().showToast(t('toast.messageDeleted'))
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      }
    },

    /**
     * 更新报文属性（等待服务器模式）
     */
    async updateMessageField(field, value) {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      const msg = editor.messageCache[editor.selectedMsgId]
      if (!msg) return

      try {
        const result = await editor._wsRequest('edit_message', {
          msg_id: editor.selectedMsgId,
          fields: { [field]: value }
        })
        if (result?.id != null && result.id !== editor.selectedMsgId) {
          delete editor.messageCache[editor.selectedMsgId]
          editor.selectedMsgId = result.id
        }
        if (result) {
          editor.messageCache[editor.selectedMsgId] = result
        }
      } catch (e) {
        // 后端拒绝时，用后端返回的权威值覆盖缓存中的对应字段
        if (e.details && field in e.details) {
          const cache = editor.messageCache[editor.selectedMsgId]
          if (cache) {
            cache[field] = e.details[field]
          }
        }
        if (!e.message?.includes?.('Connection lost')) {
          useUiStore().showToast(translateError(e), true)
        }
        throw e  // 重新抛出，让调用方（如 toggleIsFd）也能处理错误
      }
    },
  },
})
