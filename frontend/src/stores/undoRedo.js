import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useCoreStore } from './coreStore.js'

export const useUndoRedoStore = defineStore('undoRedo', {
  state: () => ({
    undoCount: 0,
    redoCount: 0,
  }),

  getters: {
    canUndo: (state) => state.undoCount > 0,
    canRedo: (state) => state.redoCount > 0,
  },

  actions: {
    /**
     * 执行撤销操作（调用后端 API）
     */
    async undo() {
      const editor = useCoreStore()
      try {
        const result = await editor._wsRequest('undo')
        const desc = result?.action_desc || '未知操作'
        const msg = `撤销: ${desc}`
        useUiStore().showToast(msg, false)
        editor.addLogEntry('undo', msg)
        this.undoCount = result?.undo_count ?? this.undoCount
        this.redoCount = result?.redo_count ?? this.redoCount
      } catch (e) {
        console.error('[STORE] undo() failed:', e)
        useUiStore().showToast(e.message || '撤销失败', true)
      }
    },

    /**
     * 执行重做操作（调用后端 API）
     */
    async redo() {
      const editor = useCoreStore()
      try {
        const result = await editor._wsRequest('redo')
        const desc = result?.action_desc || '未知操作'
        const msg = `重做: ${desc}`
        useUiStore().showToast(msg, false)
        editor.addLogEntry('redo', msg)
        this.undoCount = result?.undo_count ?? this.undoCount
        this.redoCount = result?.redo_count ?? this.redoCount
      } catch (e) {
        console.error('[STORE] redo() failed:', e)
        useUiStore().showToast(e.message || '重做失败', true)
      }
    },

    /**
     * 清空撤销/重做栈（切换会话时调用）
     */
    clearUndoStack() {
      this.undoCount = 0
      this.redoCount = 0
    },

    /**
     * 从后端状态同步计数器
     */
    syncCounts(status) {
      if (status) {
        this.undoCount = status.undo_count || 0
        this.redoCount = status.redo_count || 0
      }
    },
  },
})
