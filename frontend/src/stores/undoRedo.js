import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'

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
      const editor = useEditorStore()
      try {
        await editor._wsRequest('undo')
        useUiStore().showToast('撤销成功', false)
        editor.addLogEntry('undo', '撤销操作')
      } catch (e) {
        console.error('[STORE] undo() failed:', e)
        useUiStore().showToast(e.message || '撤销失败', true)
      }
    },

    /**
     * 执行重做操作（调用后端 API）
     */
    async redo() {
      const editor = useEditorStore()
      try {
        await editor._wsRequest('redo')
        useUiStore().showToast('重做成功', false)
        editor.addLogEntry('redo', '重做操作')
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
