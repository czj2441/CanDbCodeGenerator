/**
 * 撤销/重做管理器
 *
 * 职责：
 * - 管理 undoStack 和 redoStack
 * - 提供 pushUndo / undo / redo 操作
 * - 处理撤销时的 API 回滚
 *
 * ⚠️ 维护注意：新增操作类型时，需同步更新：
 * 1. UNDO_HANDLERS 映射表
 * 2. undo() 中的对应处理逻辑
 */

import { api } from '../api/client.js'

// ── 撤销操作处理器映射 ──
// 每种操作类型对应一个回滚函数，接收 snapshot 数据并执行 API 调用
const UNDO_HANDLERS = {
  message_delete: async (snap) => {
    // 恢复已删除的报文（含所有信号）
    await api('POST', '/api/messages', snap.data)
  },
  signal_delete: async (snap) => {
    // 恢复已删除的信号
    await api('POST', `/api/messages/${snap.msgId}/signals`, snap.data)
  },
  message_update: async (snap) => {
    // 恢复报文修改前的状态
    await api('PUT', `/api/messages/${snap.msgId}`, snap.prev)
  },
  signal_update: async (snap) => {
    // 恢复信号修改前的状态
    await api('PUT', `/api/messages/${snap.msgId}/signals/${snap.sigUuid}`, snap.prev)
  },
  message_add: async (snap) => {
    // 撤销添加报文 = 删除该报文
    await api('DELETE', `/api/messages/${snap.msgId}`)
  },
  signal_add: async (snap) => {
    // 撤销添加信号 = 删除该信号
    await api('DELETE', `/api/messages/${snap.msgId}/signals/${snap.sigUuid}`)
  },
  batch_signal_add: async (snap) => {
    // 撤销批量添加信号 = 逐个删除所有信号
    for (const sig of snap.signals) {
      await api('DELETE', `/api/messages/${snap.msgId}/signals/${sig.uuid}`)
    }
  },
}

// ── 重做操作处理器映射 ──
// 撤销的逆操作（未来扩展用）
const REDO_HANDLERS = {
  message_delete: async (snap) => {
    // 重做删除报文
    await api('DELETE', `/api/messages/${snap.data.id}`)
  },
  signal_delete: async (snap) => {
    // 重做删除信号
    await api('DELETE', `/api/messages/${snap.msgId}/signals/${snap.data.uuid}`)
  },
  message_update: async (snap) => {
    // 重做报文修改（恢复到修改后的状态）
    await api('PUT', `/api/messages/${snap.msgId}`, snap.next)
  },
  signal_update: async (snap) => {
    // 重做信号修改（恢复到修改后的状态）
    await api('PUT', `/api/messages/${snap.msgId}/signals/${snap.sigUuid}`, snap.next)
  },
  message_add: async (snap) => {
    // 重做添加报文 = 重新创建
    await api('POST', '/api/messages', snap.data)
  },
  signal_add: async (snap) => {
    // 重做添加信号 = 重新创建
    await api('POST', `/api/messages/${snap.msgId}/signals`, snap.data)
  },
  batch_signal_add: async (snap) => {
    // 重做批量添加信号 = 逐个重新创建
    for (const sig of snap.signals) {
      await api('POST', `/api/messages/${snap.msgId}/signals`, sig.data)
    }
  },
}

// ── 日志描述生成 ──
const TYPE_LABELS = {
  message_delete: '报文',
  signal_delete: '信号',
  message_update: '报文属性',
  signal_update: '信号属性',
  message_add: '报文',
  signal_add: '信号',
  batch_signal_add: '批量信号',
}

/**
 * 深度克隆快照（避免引用污染撤销栈）
 */
function cloneSnapshot(snapshot) {
  try {
    return JSON.parse(JSON.stringify(snapshot))
  } catch (e) {
    console.warn('[UndoRedo] 快照序列化失败，使用浅拷贝', e)
    return { ...snapshot }
  }
}

function getLogDescription(snap, action) {
  const label = TYPE_LABELS[snap.type] || snap.type
  const actionText = action === 'undo' ? '撤销' : '重做'

  if (snap.type === 'message_update' || snap.type === 'signal_update') {
    const field = Object.keys(snap.prev || {})[0] || ''
    const prevVal = Object.values(snap.prev || {})[0] || ''
    const nextVal = Object.values(snap.next || {})[0] || ''
    if (action === 'undo') {
      return `${actionText}${label}：${field} "${nextVal}" → "${prevVal}"`
    }
    return `${actionText}${label}：${field} "${prevVal}" → "${nextVal}"`
  }

  if (snap.type === 'batch_signal_add') {
    const count = snap.signals?.length || 0
    const names = snap.signals?.map(s => s.data?.name || s.uuid).join(', ') || ''
    return `${actionText}${label}（${count}个）：${names}`
  }

  if (snap.type === 'signal_add' || snap.type === 'signal_delete') {
    const name = snap.data?.name || snap.sigUuid || ''
    return `${actionText}${label}：${name}`
  }

  if (snap.type === 'message_add' || snap.type === 'message_delete') {
    const name = snap.data?.name || `0x${(snap.msgId || 0).toString(16)}` || ''
    return `${actionText}${label}：${name}`
  }

  return `${actionText}${label}`
}

/**
 * 创建撤销/重做管理器
 * @param {object} options
 * @param {number} options.maxSize - 撤销栈最大深度（默认 50）
 * @param {Function} options.onReload - 撤销/重做后的刷新回调
 * @param {Function} options.onToast - 提示回调
 * @returns {object} 管理器实例
 */
export function createUndoRedoManager({ maxSize = 50, onReload, onToast, onLog } = {}) {
  const undoStack = []
  const redoStack = []
  let isExecuting = false // ⚠️ 并发保护：防止快速连按导致重复执行

  /**
   * 推送撤销快照
   * @param {object} snapshot
   * @param {string} snapshot.type - 操作类型（message_delete/signal_delete/message_update/signal_update）
   * @param {object} snapshot.data - 操作相关数据
   * @param {object} [snapshot.prev] - 修改前的状态（update 类型必需）
   * @param {object} [snapshot.next] - 修改后的状态（用于 redo）
   */
  function pushUndo(snapshot) {
    undoStack.push(cloneSnapshot(snapshot))
    if (undoStack.length > maxSize) {
      undoStack.shift() // 超出限制时移除最早的记录
    }
    // 新操作会清空 redo 栈（标准行为）
    redoStack.length = 0
  }

  /**
   * 执行撤销
   */
  async function undo() {
    // ⚠️ 并发保护：正在执行时忽略新的撤销请求
    if (isExecuting) {
      if (onToast) onToast('操作执行中，请稍后再试', false)
      return
    }

    if (undoStack.length === 0) {
      if (onToast) onToast('无操作可撤销', false)
      return
    }

    isExecuting = true
    const snap = undoStack.pop()
    const handler = UNDO_HANDLERS[snap.type]

    if (!handler) {
      console.warn(`[UndoRedo] 未定义的操作类型: ${snap.type}`)
      isExecuting = false
      return
    }

    try {
      // 1. 执行回滚
      await handler(snap)

      // 2. 推入 redo 栈
      redoStack.push(snap)

      // 3. 刷新数据
      if (onReload) await onReload()

      if (onToast) onToast('撤销成功', false)
      if (onLog) {
        const desc = getLogDescription(snap, 'undo')
        onLog('undo', desc)
      }
    } catch (e) {
      console.error('[UndoRedo] 撤销失败:', e)
      if (onToast) onToast(e.message || '撤销失败', true)
      // 回滚失败，恢复 undo 栈
      undoStack.push(snap)
    } finally {
      isExecuting = false // 释放执行锁
    }
  }

  /**
   * 执行重做
   */
  async function redo() {
    // ⚠️ 并发保护：正在执行时忽略新的重做请求
    if (isExecuting) {
      if (onToast) onToast('操作执行中，请稍后再试', false)
      return
    }

    if (redoStack.length === 0) {
      if (onToast) onToast('无操作可重做', false)
      return
    }

    isExecuting = true
    const snap = redoStack.pop()
    const handler = REDO_HANDLERS[snap.type]

    if (!handler) {
      console.warn(`[UndoRedo] 未定义的重做操作类型: ${snap.type}`)
      isExecuting = false
      return
    }

    try {
      // 1. 执行重做
      await handler(snap)

      // 2. 推回 undo 栈
      undoStack.push(snap)

      // 3. 刷新数据
      if (onReload) await onReload()

      if (onToast) onToast('重做成功', false)
      if (onLog) {
        const desc = getLogDescription(snap, 'redo')
        onLog('redo', desc)
      }
    } catch (e) {
      console.error('[UndoRedo] 重做失败:', e)
      if (onToast) onToast(e.message || '重做失败', true)
      // 回滚失败，恢复 redo 栈
      redoStack.push(snap)
    } finally {
      isExecuting = false // 释放执行锁
    }
  }

  /**
   * 清空撤销/重做栈（会话切换时调用）
   */
  function clear() {
    undoStack.length = 0
    redoStack.length = 0
  }

  return {
    get undoCount() { return undoStack.length },
    get redoCount() { return redoStack.length },
    pushUndo,
    undo,
    redo,
    clear,
  }
}
