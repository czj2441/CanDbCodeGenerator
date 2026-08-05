import { defineStore } from 'pinia'
import { t } from '../i18n.js'
import { useUiStore } from './uiStore.js'
import { useEditorStore } from './editor.js'
import { translateError, findNextAvailableStartBit, generateSignalName } from '../utils/storeHelpers.js'
import { getSignalBits, toStorageStartBit } from '../utils/signalLayout.js'

export const useSignalsStore = defineStore('signals', {
  actions: {
    /**
     * 通过布局视图移动信号位置
     */
    async moveSignalByLayout(sigName, newStartBit) {
      await this.updateSignal(sigName, 'start_bit', newStartBit).catch(() => {})
    },

    /**
     * 通过布局视图调整信号长度
     */
    async resizeSignalByLayout(sigName, newLength) {
      await this.updateSignal(sigName, 'length', newLength).catch(() => {})
    },

    /**
     * 添加信号（等待服务器模式）
     */
    async addSignal(signalData) {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      const msg = editor.messageCache[editor.selectedMsgId]
      if (!msg) return

      // 自动顺延
      let defaultStartBit = 0
      if (signalData?.start_bit == null) {
        const newLength = signalData?.length ?? editor._defaultSignalLength
        const newByteOrder = signalData?.byte_order ?? 'motorola'
        const available = findNextAvailableStartBit(msg.signals, msg.dlc, newLength, newByteOrder)
        if (available != null) defaultStartBit = available
      }

      const { name: reqName, ...restSignalData } = signalData || {}
      const baseName = reqName || 'NewSignal'
      const uniqueName = generateSignalName(msg.signals, baseName)

      const fullData = {
        name: uniqueName, start_bit: defaultStartBit, length: editor._defaultSignalLength,
        byte_order: 'motorola', factor: 1.0, offset: 0.0, min_val: 0.0, max_val: 0.0,
        unit: '', comment: '', ...restSignalData,
      }

      try {
        await editor._wsRequest('add_signal', { msg_id: editor.selectedMsgId, signal: fullData })
        useUiStore().showToast(t('toast.signalAdded'))
        editor.addLogEntry('signal_add', `添加信号: name=${fullData.name}, start_bit=${fullData.start_bit}, length=${fullData.length}`)
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      }
    },

    /**
     * 更新信号属性（等待服务器模式）
     */
    async updateSignal(sigName, field, value) {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      const msg = editor.messageCache[editor.selectedMsgId]
      if (!msg) return
      const sig = msg.signals[sigName]
      if (!sig) return

      // 记忆用户修改的 length
      if (field === 'length') {
        editor._defaultSignalLength = value
      }

      try {
        await editor._wsRequest('edit_signal', {
          msg_id: editor.selectedMsgId,
          sig_name: sigName,
          field: field,
          value: value
        })
      } catch (e) {
        // 后端拒绝时，用后端返回的权威值覆盖缓存中的对应字段
        if (e.details && field in e.details) {
          sig[field] = e.details[field]
        }
        if (field === 'length') {
          editor._defaultSignalLength = sig.length
        }
        if (!e.message?.includes?.('Connection lost')) {
          useUiStore().showToast(translateError(e), true)
        }
        throw e  // 重新抛出，让调用方也能处理错误
      }
    },

    /**
     * 删除信号（等待服务器模式）
     */
    async deleteSignal(sigName) {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      try {
        await editor._wsRequest('delete_signal', { msg_id: editor.selectedMsgId, sig_name: sigName })
        useUiStore().showToast(t('toast.signalDeleted'))
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      }
    },

    /**
     * 批量更新多个信号的指定字段（等待服务器模式）
     */
    async batchUpdateSignals(sigNames, fields) {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      const msg = editor.messageCache[editor.selectedMsgId]
      if (!msg) return

      editor.isLoading = true
      try {
        const result = await editor._wsRequest('batch_edit_signals', {
          msg_id: editor.selectedMsgId,
          sig_names: sigNames,
          fields: fields,
        })
        const updated = result?.updated || 0
        const errors = result?.errors || []
        if (errors.length > 0) {
          useUiStore().showToast(t('toast.batchPartialSuccess', { success: updated, failed: errors.length }), true)
        } else {
          useUiStore().showToast(t('toast.batchUpdated', { count: updated }))
        }
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      } finally {
        editor.isLoading = false
      }
    },

    /**
     * 批量删除多个信号（等待服务器模式）
     */
    async batchDeleteSignals(sigNames) {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return

      editor.isLoading = true
      try {
        const result = await editor._wsRequest('batch_delete_signals', {
          msg_id: editor.selectedMsgId,
          sig_names: sigNames,
        })
        const deleted = result?.deleted || 0
        useUiStore().showToast(t('toast.batchDeleted', { count: deleted }))
      } catch (e) {
        useUiStore().showToast(translateError(e), true)
      } finally {
        editor.isLoading = false
      }
    },

    /**
     * 批量添加信号（等待服务器模式）
     * startBit 参数为 LSB（与信号列表显示一致），内部转为 MSB（存储格式）
     */
    async batchAddSignals({ nameTemplate, count, startNum, startBit, bitStep, length, byteOrder, factor, offset, minVal, maxVal, unit, commentTemplate }) {
      const editor = useEditorStore()
      if (editor.selectedMsgId == null) return
      const msg = editor.messageCache[editor.selectedMsgId]
      if (!msg) return
      const { expandTemplate } = await import('../utils/format.js')
      const maxBits = msg.dlc * 8

      // LSB → MSB 转换（Intel 下不变，Motorola 下转换）
      const storageStartBit = toStorageStartBit(startBit, length, byteOrder, 63, -1)
      if (storageStartBit < 0) {
        useUiStore().showToast(`Invalid start bit ${startBit} for ${byteOrder} length ${length}`, true)
        return
      }

      for (let i = 0; i < count; i++) {
        const sb = storageStartBit + i * bitStep
        const bits = getSignalBits(sb, length, byteOrder)
        for (const b of bits) {
          if (b < 0 || b >= maxBits) {
            useUiStore().showToast(`Signal #${startNum + i} at bit ${sb} exceeds range [0, ${maxBits - 1}]`, true)
            return
          }
        }
      }

      const signals = []
      for (let i = 0; i < count; i++) {
        const n = startNum + i
        const name = expandTemplate(nameTemplate, n)
        const comment = commentTemplate ? expandTemplate(commentTemplate, n) : ''
        const sb = storageStartBit + i * bitStep
        signals.push({
          name, start_bit: sb, length, byte_order: byteOrder,
          factor, offset, min_val: minVal, max_val: maxVal, unit, comment,
        })
      }

      editor.isLoading = true
      try {
        const result = await editor._wsRequest('batch_add_signals', {
          msg_id: editor.selectedMsgId,
          signals,
        })
        const created = result?.count || 0
        if (result?.errors?.length > 0) {
          console.warn('[STORE] batchAddSignals() 部分信号创建失败:', result.errors)
        }
        useUiStore().showToast(t('toast.batchCreated', { count: created }))
      } catch (e) {
        useUiStore().showToast(t('toast.batchFailed', { idx: 1, msg: e.message }), true)
      } finally {
        editor.isLoading = false
      }
    },

  },
})
