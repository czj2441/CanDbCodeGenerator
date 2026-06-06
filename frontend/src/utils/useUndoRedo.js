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
}

/**
 * 创建撤销/重做管理器
 * @param {object} options
 * @param {number} options.maxSize - 撤销栈最大深度（默认 50）
 * @param {Function} options.onReload - 撤销/重做后的刷新回调
 * @param {Function} options.onToast - 提示回调
 * @returns {object} 管理器实例
 */
export function createUndoRedoManager({ maxSize = 50, onReload, onToast } = {}) {
  const undoStack = []
  const redoStack = []

  /**
   * 推送撤销快照
   * @param {object} snapshot
   * @param {string} snapshot.type - 操作类型（message_delete/signal_delete/message_update/signal_update）
   * @param {object} snapshot.data - 操作相关数据
   * @param {object} [snapshot.prev] - 修改前的状态（update 类型必需）
   * @param {object} [snapshot.next] - 修改后的状态（用于 redo）
   */
  function pushUndo(snapshot) {
    undoStack.push(snapshot)
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
    if (undoStack.length === 0) {
      if (onToast) onToast('无操作可撤销', false)
      return
    }

    const snap = undoStack.pop()
    const handler = UNDO_HANDLERS[snap.type]

    if (!handler) {
      console.warn(`[UndoRedo] 未定义的操作类型: ${snap.type}`)
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
    } catch (e) {
      console.error('[UndoRedo] 撤销失败:', e)
      if (onToast) onToast(e.message || '撤销失败', true)
      // 回滚失败，恢复 undo 栈
      undoStack.push(snap)
    }
  }

  /**
   * 执行重做
   */
  async function redo() {
    if (redoStack.length === 0) {
      if (onToast) onToast('无操作可重做', false)
      return
    }

    const snap = redoStack.pop()
    const handler = REDO_HANDLERS[snap.type]

    if (!handler) {
      console.warn(`[UndoRedo] 未定义的重做操作类型: ${snap.type}`)
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
    } catch (e) {
      console.error('[UndoRedo] 重做失败:', e)
      if (onToast) onToast(e.message || '重做失败', true)
      // 回滚失败，恢复 redo 栈
      redoStack.push(snap)
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
