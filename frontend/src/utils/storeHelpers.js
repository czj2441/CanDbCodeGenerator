/**
 * Store 工具函数
 *
 * 职责：提取 editor.js 中重复的工具逻辑
 */

/**
 * 统一标记修改状态
 * @param {Object} store - Pinia store 实例
 */
export function markModified(store) {
  store.modified = true
  store.modifiedAt = Date.now()
  store._scheduleModifiedCheck()
}
