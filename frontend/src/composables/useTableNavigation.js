/**
 * 表格方向键单元格导航 composable
 *
 * 提取自 SignalEditorTab / MessageTab / ValueTableTab 共用的方向键导航逻辑。
 * 编辑模式（isEditing 返回 true）时方向键保留在当前元素内，不触发单元格跳转。
 * 调用方通过回调函数注入数据访问，composable 不直接依赖任何 store。
 *
 * @param {import('vue').Ref<HTMLTableElement|null>} tableRef - 表格 DOM 引用
 * @param {import('vue').ComputedRef<Array>} visibleColumns - 当前可见列定义数组
 * @param {Object} options
 * @param {Set<string>} options.nonNavigableCols - 不可导航的列 key 集合
 * @param {() => number} options.getTotalRows - 返回当前数据行总数
 * @param {() => boolean} options.isEditing - 返回当前是否处于编辑模式
 * @param {(rowIdx: number) => void} options.onRowSelect - 导航后同步行选中状态
 */

const NAV_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])

export function useTableNavigation(tableRef, visibleColumns, {
  nonNavigableCols,
  getTotalRows,
  isEditing,
  onRowSelect,
}) {
  /** 从当前 DOM 元素定位所在行列索引 */
  function getCellPosition(el) {
    const td = el.closest('td')
    if (!td) return null
    const tr = td.parentElement
    if (!tr || tr.tagName !== 'TR') return null
    const tbody = tr.parentElement
    if (!tbody || tbody.tagName !== 'TBODY') return null
    const rowIdx = Array.from(tbody.children).indexOf(tr)
    return { rowIdx, colIdx: td.cellIndex }
  }

  /** 获取目标单元格内的可聚焦元素（含 readonly input，浏览模式下所有 input 均为 readonly） */
  function getCellEditor(rowIdx, colIdx) {
    const table = tableRef.value
    if (!table) return null
    const tbody = table.tBodies[0]
    if (!tbody) return null
    const row = tbody.rows[rowIdx]
    if (!row) return null
    const cell = row.cells[colIdx]
    if (!cell) return null
    return cell.querySelector('input, select')
  }

  /** 从当前列出发，沿 direction 方向查找下一个可导航列 */
  function findNavigableCol(colIdx, direction) {
    const cols = visibleColumns.value
    let i = colIdx + direction
    while (i >= 0 && i < cols.length) {
      if (!nonNavigableCols.has(cols[i].key)) return i
      i += direction
    }
    return -1
  }

  function onCellKeyDown(e) {
    if (!NAV_KEYS.has(e.key)) return

    // ── 编辑模式下禁止导航，方向键留在当前 input/select 内 ──
    if (isEditing()) return

    const el = e.target
    if (el.tagName !== 'INPUT' && el.tagName !== 'SELECT') return
    if (!tableRef.value?.contains(el)) return

    const pos = getCellPosition(el)
    if (!pos) return

    const cols = visibleColumns.value
    const totalRows = getTotalRows()
    let { rowIdx, colIdx } = pos
    let targetRow = rowIdx
    let targetCol = colIdx

    // ── 水平导航（左右） ──
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      // 对 input：仅在光标处于边界时才导航
      if (el.tagName === 'INPUT') {
        // type="number" 等不支持 selectionStart/End，无光标概念，始终允许导航
        const supportsSelection = el.type === 'text' || el.type === 'search' || el.type === 'url' || el.type === 'tel' || el.type === 'password' || el.type === ''
        if (supportsSelection) {
          if (e.key === 'ArrowLeft' && el.selectionStart > 0) return
          if (e.key === 'ArrowRight' && el.selectionEnd < el.value.length) return
        }
      }
      // select 元素：左右键同样导航（选项切换通过鼠标点击完成）

      const dir = e.key === 'ArrowLeft' ? -1 : 1
      const nextCol = findNavigableCol(colIdx, dir)
      if (nextCol < 0) return
      targetCol = nextCol
    }

    // ── 垂直导航（上下） ──
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      // select 元素：上下键同样导航（选项切换通过鼠标点击完成）

      const dir = e.key === 'ArrowUp' ? -1 : 1
      targetRow = rowIdx + dir
      if (targetRow < 0 || targetRow >= totalRows) return

      // 若当前列不可编辑，跳到最近的可编辑列
      if (nonNavigableCols.has(cols[colIdx]?.key)) {
        const nextCol = findNavigableCol(colIdx, 1)
        if (nextCol < 0) return
        targetCol = nextCol
      }
    }

    e.preventDefault()

    // ── 聚焦目标 ──
    const target = getCellEditor(targetRow, targetCol)
    if (!target) return

    target.focus()
    if (target.tagName === 'INPUT') target.select()

    // 确保目标行在视口内
    target.closest('tr')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })

    // 同步行选中状态
    onRowSelect(targetRow)
  }

  return { onCellKeyDown }
}
