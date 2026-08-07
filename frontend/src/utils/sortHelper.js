/**
 * 通用排序工具函数
 *
 * 供 SignalEditorTab / MessageTab / ValueTableTab 复用。
 */

/**
 * 对 items 按指定字段排序。
 * @param {Array} items - 待排序数组
 * @param {string} field - 排序字段名
 * @param {'asc'|'desc'} direction - 排序方向
 * @returns {Array} 新数组（不修改原数组）
 */
export function sortByField(items, field, direction = 'asc') {
  if (!field || !items?.length) return items
  const mult = direction === 'desc' ? -1 : 1
  return [...items].sort((a, b) => {
    const va = a[field]
    const vb = b[field]
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    if (typeof va === 'number' && typeof vb === 'number') {
      return (va - vb) * mult
    }
    return String(va).localeCompare(String(vb), undefined, { numeric: true }) * mult
  })
}

/**
 * 切换排序：同字段则翻转方向，不同字段则设为 asc。
 * @param {string} currentField - 当前排序字段
 * @param {'asc'|'desc'} currentDir - 当前方向
 * @param {string} newField - 点击的字段
 * @returns {{ field: string, dir: 'asc'|'desc' }}
 */
export function toggleSort(currentField, currentDir, newField) {
  if (currentField === newField) {
    return { field: newField, dir: currentDir === 'asc' ? 'desc' : 'asc' }
  }
  return { field: newField, dir: 'asc' }
}

/**
 * 返回排序图标字符。
 * @param {string} field - 列字段
 * @param {string} activeField - 当前排序字段
 * @param {'asc'|'desc'} activeDir - 当前方向
 * @returns {string} '▲' | '▼' | ''
 */
export function getSortIcon(field, activeField, activeDir) {
  if (field !== activeField) return ''
  return activeDir === 'asc' ? '▲' : '▼'
}
