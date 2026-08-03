/**
 * 列宽拖拽 composable
 *
 * 提取自 SignalTable / MessageTable / ValueTableList 共用的列宽拖拽逻辑。
 * 调用方通过回调函数注入宽度读写操作，composable 不直接依赖任何 store。
 *
 * @param {import('vue').Ref<HTMLTableElement|null>} tableRef - 表格 DOM 引用
 * @param {import('vue').ComputedRef<Array>} visibleColumns - 当前可见列定义数组
 * @param {Object} options
 * @param {function(string, number): number} options.getColumnWidth - (colKey, defaultPct) => 当前宽度百分比
 * @param {function(): Object} options.getColumnWidths - () => 当前完整宽度映射（用于浅拷贝后覆写）
 * @param {function(Object): void} options.setColumnWidths - (widthsMap) => 持久化列宽
 * @param {function(): Array} options.hiddenColumns - () => 当前隐藏列 key 数组（用于归一化 watcher）
 */
import { computed, watch, onUnmounted } from 'vue'

const MIN_PCT = 2 // 列宽最小百分比

export function useColumnResize(tableRef, visibleColumns, {
  getColumnWidth,
  getColumnWidths,
  setColumnWidths,
  hiddenColumns,
}) {
  // 非响应式状态：拖拽期间以鼠标事件频率更新，避免 Vue reactivity 开销
  let resizeState = null
  let justResized = false

  /** 归一化列宽百分比，确保总和 = 100%，防止浏览器自动缩放导致拖拽不同步 */
  const normalizedPcts = computed(() => {
    const cols = visibleColumns.value
    const raw = {}
    let total = 0
    for (const c of cols) {
      const v = getColumnWidth(c.key, c.defaultPct)
      raw[c.key] = v
      total += v
    }
    if (Math.abs(total - 100) < 0.01 || total === 0) return raw
    const scale = 100 / total
    const result = {}
    for (const c of cols) {
      result[c.key] = raw[c.key] * scale
    }
    return result
  })

  function startResize(colIndex, e) {
    e.preventDefault()
    const cols = visibleColumns.value
    const col = cols[colIndex]
    const nextCol = cols[colIndex + 1]
    if (!nextCol) return

    // 从 DOM 读取实际渲染宽度，避免 store 原始百分比与浏览器缩放后的渲染宽度不一致
    const tableWidth = tableRef.value.getBoundingClientRect().width
    const colEls = tableRef.value.querySelectorAll('colgroup col')
    const curPct = colEls[colIndex]?.getBoundingClientRect().width / tableWidth * 100
      ?? getColumnWidth(col.key, col.defaultPct)
    const nextPct = colEls[colIndex + 1]?.getBoundingClientRect().width / tableWidth * 100
      ?? getColumnWidth(nextCol.key, nextCol.defaultPct)

    resizeState = { col, nextCol, colIndex, startX: e.clientX, curPct, nextPct, tableWidth }
    document.addEventListener('mousemove', onResize)
    document.addEventListener('mouseup', stopResize)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  function onResize(e) {
    if (!resizeState) return
    const deltaPct = ((e.clientX - resizeState.startX) / resizeState.tableWidth) * 100
    let newCur = Math.max(MIN_PCT, resizeState.curPct + deltaPct)
    let newNext = resizeState.nextPct - (newCur - resizeState.curPct)
    if (newNext < MIN_PCT) { newNext = MIN_PCT; newCur = resizeState.curPct + resizeState.nextPct - MIN_PCT }

    const colEls = tableRef.value.querySelectorAll('colgroup col')
    if (colEls[resizeState.colIndex]) colEls[resizeState.colIndex].style.width = newCur + '%'
    if (colEls[resizeState.colIndex + 1]) colEls[resizeState.colIndex + 1].style.width = newNext + '%'
  }

  function stopResize(e) {
    if (!resizeState) return
    const deltaPct = ((e.clientX - resizeState.startX) / resizeState.tableWidth) * 100
    let newCur = Math.max(MIN_PCT, resizeState.curPct + deltaPct)
    let newNext = resizeState.nextPct - (newCur - resizeState.curPct)
    if (newNext < MIN_PCT) { newNext = MIN_PCT; newCur = resizeState.curPct + resizeState.nextPct - MIN_PCT }

    const widths = { ...getColumnWidths() }
    widths[resizeState.col.key] = Math.round(newCur * 100) / 100
    widths[resizeState.nextCol.key] = Math.round(newNext * 100) / 100
    setColumnWidths(widths)

    // 标记刚完成拖拽，阻止后续合成的 click 事件触发排序
    justResized = true
    resizeState = null
    document.removeEventListener('mousemove', onResize)
    document.removeEventListener('mouseup', stopResize)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  /** 读取并重置拖拽标记，用于 onHeaderClick 中阻止误触发排序 */
  function consumeJustResized() {
    if (justResized) { justResized = false; return true }
    return false
  }

  // 列显隐时宽度归一化
  watch(hiddenColumns, () => {
    const visible = visibleColumns.value
    if (!visible.length) return
    const total = visible.reduce((s, c) => s + getColumnWidth(c.key, c.defaultPct), 0)
    if (Math.abs(total - 100) > 0.1) {
      const scale = 100 / total
      const widths = { ...getColumnWidths() }
      for (const c of visible) {
        widths[c.key] = Math.round(getColumnWidth(c.key, c.defaultPct) * scale * 100) / 100
      }
      setColumnWidths(widths)
    }
  }, { deep: true })

  // 组件卸载时清理 document 级事件监听器（兜底：拖拽中途组件被销毁）
  onUnmounted(() => {
    if (resizeState) {
      document.removeEventListener('mousemove', onResize)
      document.removeEventListener('mouseup', stopResize)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      resizeState = null
    }
  })

  return {
    normalizedPcts,
    startResize,
    consumeJustResized,
  }
}
