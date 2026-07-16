import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { setSessionId, getSessionId } from '../api/client.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'
import { useUndoRedoStore } from './undoRedo.js'
import { resetMessageIdGenerator } from '../utils/storeHelpers.js'

export const useFileOperationsStore = defineStore('fileOperations', {
  actions: {
    /**
     * 手动保存当前会话
     */
    async saveSession() {
      const editor = useEditorStore()
      try {
        editor.lastSaveError = null
        editor.saveStatus = 'saving'
        await editor._wsRequest('save', {}, 120000)
        editor.saveStatus = 'saved'
        editor._startSaveFadeTimer()
        return true
      } catch (e) {
        console.error('Failed to save session:', e)
        editor.lastSaveError = e.message || String(e)
        editor.saveStatus = editor.backendDirty ? 'modified' : 'idle'
        return false
      }
    },

    /**
     * 加载文件
     */
    async loadHistoryFile(fileName) {
      const editor = useEditorStore()
      const undoRedo = useUndoRedoStore()

      editor.selectedMsgId = null
      editor.messageCache = {}
      editor.messages = []
      resetMessageIdGenerator()
      editor.signalErrors = []
      editor._defaultSignalLength = 8
      editor._healthFailCount = 0
      undoRedo.clearUndoStack()
      editor.isLoading = true

      try {
        const currentSid = getSessionId()

        editor.stopEditorSync()
        editor.startEditorSync()
        await editor._waitForWsReady()

        const data = await editor._wsClient.request('load_file', {
          file_name: fileName,
          current_session_id: currentSid
        })
        const sid = data.session_id
        setSessionId(sid)
        editor._dataVersion = 0
        editor.currentFileName = data.file_name || ''
        useUiStore().showToast(t('toast.sessionLoaded'))
      } catch (e) {
        editor._resetOnSessionFailure()
        if (e.code === 'FILE_LOCKED') {
          useUiStore().showToast(t('toast.noEditPermission'), true)
        } else {
          useUiStore().showToast(e.message, true)
        }
        throw e
      } finally {
        editor.isLoading = false
      }
    },

    /**
     * 另存为：克隆当前会话数据到新文件，切换到新 session
     */
    async saveAs(name) {
      const editor = useEditorStore()
      const undoRedo = useUndoRedoStore()
      try {
        const data = await editor._wsRequest('save_as', { name })
        const sid = data.session_id
        setSessionId(sid)
        editor.currentFileName = data.file_name
        editor.selectedMsgId = null
        editor.messageCache = {}
        editor.messages = []
        resetMessageIdGenerator()
        editor.signalErrors = []
        editor._dataVersion = 0
        undoRedo.clearUndoStack()
        useUiStore().showToast(t('toast.saveAs', { name: data.file_name }))
      } catch (e) {
        if (e.code === 'FILE_NAME_EXISTS') {
          useUiStore().showToast(t('toast.saveAsExistsError'), true)
        } else if (e.code === 'VALUE_INVALID') {
          useUiStore().showToast(t('toast.saveAsNameRequired'), true)
        } else if (e.code === 'INVALID_FILE_NAME') {
          useUiStore().showToast(t('toast.invalidFileName'), true)
        } else if (e.code === 'SESSION_NOT_FOUND') {
          editor._resetOnSessionFailure()
          useUiStore().showToast(t('toast.sessionLost'), true)
        } else {
          useUiStore().showToast(e.message, true)
        }
        throw e
      }
    },

    /**
     * 创建新会话
     */
    async createNewSession(name = 'Untitled') {
      const editor = useEditorStore()
      const undoRedo = useUndoRedoStore()

      try {
        editor.stopEditorSync()
        editor.startEditorSync()
        await editor._waitForWsReady()

        const data = await editor._wsRequest('new_file', { name })
        const sid = data.session_id
        setSessionId(sid)
        editor.currentFileName = data.file_name
        editor.selectedMsgId = null
        editor.messageCache = {}
        editor.messages = []
        resetMessageIdGenerator()
        editor.signalErrors = []
        editor._defaultSignalLength = 8
        editor._dataVersion = 0
        undoRedo.clearUndoStack()
        useUiStore().showToast(t('toast.newSessionCreated'))
      } catch (e) {
        editor._resetOnSessionFailure()
        useUiStore().showToast(e.message, true)
      }
    },

    /**
     * 导入文件到新会话
     */
    async importFile({ format, content, filename }) {
      const editor = useEditorStore()
      const undoRedo = useUndoRedoStore()

      editor.selectedMsgId = null
      editor.messageCache = {}
      editor.messages = []
      resetMessageIdGenerator()
      editor.signalErrors = []
      editor._defaultSignalLength = 8
      editor._dataVersion = 0
      undoRedo.clearUndoStack()
      editor.isLoading = true

      try {
        editor.stopEditorSync()
        editor.startEditorSync()
        await editor._waitForWsReady()

        const data = await editor._wsRequest('import_file', {
          format, content, filename
        }, 60000)

        const sid = data.session_id
        setSessionId(sid)
        editor.currentFileName = data.file_name || filename
        editor._dataVersion = 0

        return data
      } catch (e) {
        editor._resetOnSessionFailure()
        useUiStore().showToast(e.message, true)
        throw e
      } finally {
        editor.isLoading = false
      }
    },

    /**
     * 新建文件（从 FileBrowser 调用）
     */
    async newFile(name = 'Untitled') {
      const editor = useEditorStore()
      const undoRedo = useUndoRedoStore()

      editor.stopEditorSync()
      editor.startEditorSync()
      try {
        await editor._waitForWsReady()

        const data = await editor._wsRequest('new_file', { name })
        const sid = data.session_id
        setSessionId(sid)
        editor.currentFileName = data.file_name
        editor.selectedMsgId = null
        editor.messageCache = {}
        editor.messages = []
        resetMessageIdGenerator()
        editor.signalErrors = []
        editor._defaultSignalLength = 8
        editor._dataVersion = 0
        undoRedo.clearUndoStack()
        return sid
      } catch (e) {
        editor._resetOnSessionFailure()
        throw e
      }
    },

    /**
     * 释放当前 session 的文件锁
     */
    async releaseSession() {
      const editor = useEditorStore()
      const sid = getSessionId()
      if (sid) {
        try {
          await editor._wsRequest('release_lock', { abort: true })
        } catch (_) {
          // 忽略释放失败
        }
      }
    },
  },
})
