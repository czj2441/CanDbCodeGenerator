import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'
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
      this.loadSelectedMessage()
    },

    /**
     * 加载选中报文的详细信息（含信号列表）
     */
    async loadSelectedMessage() {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      try {
        editor.messageCache[editor.selectedMsgId] = await editor._wsRequest('get_message', { msg_id: editor.selectedMsgId })
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
          message: { id, name, dlc: 8, cycle_time: 0, sender: '', is_fd: false, signals: {} }
        })
        if (result?.id != null) {
          editor.messageCache[result.id] = result
          editor.selectedMsgId = result.id
        }
        useUiStore().showToast(t('toast.messageAdded'))
        editor.addLogEntry('add', `添加报文: 0x${id.toString(16).toUpperCase()} ${name}`)
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
        editor.addLogEntry('delete', `删除报文: 0x${id.toString(16).toUpperCase()}`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      }
    },

    /**
     * 更新报文属性（等待服务器模式）
     */
    async updateMessageField(field, value, msgId) {
      const editor = useEditorStore()
      const targetId = msgId ?? editor.selectedMsgId
      if (targetId == null) return
      const msg = editor.messageCache[targetId]
      if (!msg) return

      // 记录旧值用于日志
      const oldVal = msg[field]
      const msgName = msg.name || '0x' + targetId.toString(16).toUpperCase()

      try {
        const result = await editor._wsRequest('edit_message', {
          msg_id: targetId,
          fields: { [field]: value }
        })
        if (result?.id != null && result.id !== targetId) {
          delete editor.messageCache[targetId]
          if (targetId === editor.selectedMsgId) {
            editor.selectedMsgId = result.id
          }
        }
        if (result) {
          const cacheId = result?.id != null ? result.id : targetId
          editor.messageCache[cacheId] = result
        }
        editor.addLogEntry('update', `报文 ${msgName}.${field}: ${oldVal} → ${value}`)
      } catch (e) {
        // 后端拒绝时，用后端返回的权威值覆盖缓存中的对应字段
        if (e.details && field in e.details) {
          const cache = editor.messageCache[targetId]
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

    /**
     * 批量更新多个报文的指定字段（等待服务器模式）
     */
    async batchUpdateMessages(msgIds, fields) {
      const editor = useEditorStore()
      try {
        const result = await editor._wsRequest('batch_edit_messages', {
          msg_ids: msgIds,
          fields: fields,
        })
        const updated = result?.updated || 0
        const errors = result?.errors || []
        if (errors.length > 0) {
          useUiStore().showToast(t('toast.batchPartialSuccess', { success: updated, failed: errors.length }), true)
        } else {
          useUiStore().showToast(t('toast.batchUpdated', { count: updated }))
        }
        editor.addLogEntry('batch', `批量更新 ${updated} 个报文: ${Object.keys(fields).join(', ')}`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      }
    },

    /**
     * 批量删除多个报文（等待服务器模式）
     */
    async batchDeleteMessages(msgIds) {
      const editor = useEditorStore()
      try {
        const result = await editor._wsRequest('batch_delete_messages', {
          msg_ids: msgIds,
        })
        const deleted = result?.deleted || 0
        useUiStore().showToast(t('toast.batchDeleted', { count: deleted }))
        editor.addLogEntry('batch', `批量删除 ${deleted} 个报文`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      }
    },
  },
})
