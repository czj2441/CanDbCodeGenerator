/**
 * 表格方向键单元格导航 composable
 *
 * 提取自 SignalEditorTab / MessageTab / ValueTableTab 共用的方向键导航逻辑。
 * 编辑模式（isEditing 返回 true）时方向键保留在当前元素内，不触发单元格跳转。
 * 浏览模式下按下可打印字符键时，自动进入编辑模式（类 Excel 行为）。
 * 浏览模式下按 F2 或 Enter 进入编辑模式（光标置于末尾，不替换值）。
 * 编辑模式下按 Enter 确认当前编辑并移动到同列下一行（最后一行仅确认）。
 * 编辑模式下 F2 无操作。
 * 调用方通过回调函数注入数据访问，composable 不直接依赖任何 store。
 *
 * @param {import('vue').Ref<HTMLTableElement|null>} tableRef - 表格 DOM 引用
 * @param {import('vue').ComputedRef<Array>} visibleColumns - 当前可见列定义数组
 * @param {Object} options
 * @param {Set<string>} options.nonNavigableCols - 不可导航的列 key 集合
 * @param {() => number} options.getTotalRows - 返回当前数据行总数
 * @param {() => boolean} options.isEditing - 返回当前是否处于编辑模式
 * @param {(rowIdx: number) => void} options.onRowSelect - 导航后同步行选中状态
 * @param {(el: HTMLInputElement, rowIdx: number, colIdx: number, char: string) => boolean} [options.onStartEdit]
 *   浏览模式下按下可打印字符时调用，进入编辑模式。
 *   返回 false 表示权限不允许（如只读会话），此时不触发编辑。
 * @param {() => void} [options.onEndEdit]
 *   编辑模式下 Enter 确认时调用，清除编辑状态（如 editingKey.value = null）。
 */

import { nextTick, watch } from 'vue'

const NAV_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])

/** 判断按键是否为可打印字符（排除修饰键组合） */
function isPrintableChar(e) {
  return e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey
}

/** 判断字符是否可作为 number input 的合法起始输入 */
function isValidNumberChar(ch) {
  return /[0-9.\-eE]/.test(ch)
}

export function useTableNavigation(tableRef, visibleColumns, {
  nonNavigableCols,
  getTotalRows,
  isEditing,
  onRowSelect,
  onStartEdit,
  onEndEdit,
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

  /**
   * 捕获阶段：仅阻止方向键原生行为（防止 select 切选项 / input 移光标）。
   * 通过 addEventListener({ capture: true }) 注册，由 watch(tableRef) 管理生命周期。
   */
  function captureKeyDown(e) {
    if (NAV_KEYS.has(e.key) && !isEditing()) {
      const t = e.target
      if ((t.tagName === 'INPUT' || t.tagName === 'SELECT') && tableRef.value?.contains(t)) {
        e.preventDefault()
      }
    }
  }

  function onCellKeyDown(e) {
    // ── 编辑模式 + Enter → 确认并移至下一行同列 ──
    if (e.key === 'Enter' && isEditing()) {
      const el = e.target
      if ((el.tagName === 'INPUT' || el.tagName === 'SELECT') && tableRef.value?.contains(el)) {
        e.preventDefault()
        const td = el.closest('td')
        const tr = td?.parentElement
        const colIdx = td?.cellIndex
        if (!tr || colIdx == null) return

        // 1) blur 触发 @blur 保存（此时 editingKey 仍有效，isCellEditable 为 true）
        if (el.tagName === 'INPUT') el.blur()
        // 2) 清除编辑状态（可选回调，组件通过 onEndEdit 注入）
        onEndEdit?.()
        // 3) 焦点移至同列下一行（最后一行仅确认不下移）
        nextTick(() => {
          const nextTr = tr.nextElementSibling
          if (!nextTr || nextTr.tagName !== 'TR') return
          const nextEl = nextTr.cells[colIdx]?.querySelector('input, select')
          if (!nextEl) return
          nextEl.focus()
          nextEl.closest('tr')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
          const tbody = tableRef.value?.tBodies[0]
          if (tbody) {
            const nextRowIdx = Array.from(tbody.children).indexOf(nextTr)
            if (nextRowIdx >= 0) onRowSelect(nextRowIdx)
          }
        })
        return
      }
    }

    // ── 浏览模式 + F2/Enter → 进入编辑模式（光标置于末尾）──
    if (!isEditing() && onStartEdit && (e.key === 'F2' || e.key === 'Enter')) {
      const el = e.target
      if (el.tagName === 'INPUT' && el.readOnly && tableRef.value?.contains(el)) {
        const pos = getCellPosition(el)
        if (pos && !nonNavigableCols.has(visibleColumns.value[pos.colIdx]?.key)) {
          if (onStartEdit(el, pos.rowIdx, pos.colIdx, '') === false) return
          e.preventDefault()
          nextTick(() => {
            try {
              const len = el.value.length
              el.setSelectionRange(len, len)
            } catch { /* type="number" 等不支持 setSelectionRange */ }
          })
          return
        }
      }
    }

    // ── 浏览模式 + 可打印字符 → 自动进入编辑模式 ──
    if (!isEditing() && onStartEdit && isPrintableChar(e)) {
      const el = e.target
      if (el.tagName === 'INPUT' && el.readOnly && tableRef.value?.contains(el)) {
        // type="number" 输入框仅接受数字相关字符
        if (el.type === 'number' && !isValidNumberChar(e.key)) return

        const pos = getCellPosition(el)
        if (pos && !nonNavigableCols.has(visibleColumns.value[pos.colIdx]?.key)) {
          // 权限检查：onStartEdit 返回 false 表示只读会话不允许编辑
          if (onStartEdit(el, pos.rowIdx, pos.colIdx, e.key) === false) return
          e.preventDefault()
          nextTick(() => {
            el.select()
            el.value = e.key
            el.dispatchEvent(new Event('input', { bubbles: true }))
          })
          return
        }
      }
    }

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

      const dir = e.key === 'ArrowLeft' ? -1 : 1
      const nextCol = findNavigableCol(colIdx, dir)
      if (nextCol < 0) return
      targetCol = nextCol
    }

    // ── 垂直导航（上下） ──
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
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

    // ── 聚焦目标 ──
    const target = getCellEditor(targetRow, targetCol)
    if (!target) return

    e.preventDefault()
    target.focus()

    // 确保目标行在视口内
    target.closest('tr')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })

    // 同步行选中状态
    onRowSelect(targetRow)
  }

  // ── 捕获监听器生命周期管理：响应 v-if 条件渲染导致的 tableRef 变化 ──
  watch(tableRef, (newEl, oldEl) => {
    oldEl?.removeEventListener('keydown', captureKeyDown, { capture: true })
    newEl?.addEventListener('keydown', captureKeyDown, { capture: true })
  })

  return { onCellKeyDown }
}
