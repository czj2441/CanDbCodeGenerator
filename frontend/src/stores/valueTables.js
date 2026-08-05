import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'
import { translateError } from '../utils/storeHelpers.js'

export const useValueTablesStore = defineStore('valueTables', {
  actions: {
    /**
     * 新增全局值描述表
     */
    async addValueTable(name, entries = {}) {
      const editor = useEditorStore()
      try {
        await editor._wsRequest('add_value_table', { name, entries })
        useUiStore().showToast(t('toast.valueTableAdded', { name }))
        editor.addLogEntry('add', `新增值描述表: ${name}`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
        throw e
      }
    },

    /**
     * 更新全局值描述表的条目
     */
    async updateValueTable(name, entries) {
      const editor = useEditorStore()
      try {
        await editor._wsRequest('update_value_table', { name, entries })
        editor.addLogEntry('update', `更新值描述表: ${name}`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
        throw e
      }
    },

    /**
     * 删除全局值描述表
     */
    async deleteValueTable(name) {
      const editor = useEditorStore()
      try {
        await editor._wsRequest('delete_value_table', { name })
        useUiStore().showToast(t('toast.valueTableDeleted', { name }))
        editor.addLogEntry('delete', `删除值描述表: ${name}`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
        throw e
      }
    },

    /**
     * 重命名全局值描述表
     */
    async renameValueTable(oldName, newName) {
      const editor = useEditorStore()
      try {
        await editor._wsRequest('rename_value_table', { old_name: oldName, new_name: newName })
        useUiStore().showToast(t('toast.valueTableRenamed', { old: oldName, new: newName }))
        editor.addLogEntry('update', `重命名值描述表: ${oldName} → ${newName}`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
        throw e
      }
    },
  },
})
