/**
 * 多选 composable — 为表格组件提供多选状态管理。
 *
 * 纯函数式，不依赖任何 Pinia store（与 useColumnResize.js 同风格）。
 * 通过回调函数注入数据访问，支持 Ctrl/Shift+Click 和 checkbox 两种选择方式。
 *
 * @param {() => Array} getItems - 返回当前排序后的数据数组（用于 Shift 范围选择）
 * @param {Object} options
 * @param {(item: any) => string|number} options.getKey - 提取行唯一标识
 */
import { shallowRef, computed, watch } from 'vue'

export function useMultiSelect(getItems, { getKey }) {
  // 使用 shallowRef 避免 Vue 深层代理 Set 内元素，只在赋值时触发响应式
  const selectedKeys = shallowRef(new Set())

  // Shift 范围选择的锚点（普通变量，不触发响应式）
  let _anchorKey = null

  // ── Computed ──

  const selectedCount = computed(() => selectedKeys.value.size)

  const allSelected = computed(() => {
    const items = getItems()
    if (!items || items.length === 0) return false
    const keys = selectedKeys.value
    return items.every(item => keys.has(getKey(item)))
  })

  const someSelected = computed(() => {
    const keys = selectedKeys.value
    return keys.size > 0 && !allSelected.value
  })

  const isMultiSelect = computed(() => selectedKeys.value.size > 1)

  // ── Actions ──

  /**
   * 查询单个是否选中
   * @param {string|number} key
   * @returns {boolean}
   */
  function isSelected(key) {
    return selectedKeys.value.has(key)
  }

  /**
   * 行点击处理 — 核心选择逻辑
   * @param {string|number} key - 被点击行的标识
   * @param {number} index - 被点击行在当前排序数组中的索引
   * @param {MouseEvent|{ctrlKey?: boolean, shiftKey?: boolean, metaKey?: boolean}} event
   */
  function handleRowClick(key, index, event) {
    const ctrlOrMeta = event.ctrlKey || event.metaKey
    const shift = event.shiftKey

    if (shift && _anchorKey != null) {
      // Shift+Click: 从锚点到当前项范围选中
      _rangeSelect(key, index)
    } else if (ctrlOrMeta) {
      // Ctrl+Click: toggle 当前项
      _toggle(key)
      _anchorKey = key
    } else {
      // 普通点击: 清空选中，仅选中当前项
      selectedKeys.value = new Set([key])
      _anchorKey = key
    }
  }

  /**
   * Checkbox 点击 — 等同 Ctrl+Click（toggle 当前项）
   * @param {string|number} key
   */
  function toggleCheckbox(key) {
    _toggle(key)
    _anchorKey = key
  }

  /**
   * 全选/取消全选
   */
  function toggleAll() {
    const items = getItems()
    if (!items || items.length === 0) return

    if (allSelected.value) {
      // 已全选 → 取消全选
      selectedKeys.value = new Set()
    } else {
      // 未全选 → 全选
      const newSet = new Set()
      for (const item of items) {
        newSet.add(getKey(item))
      }
      selectedKeys.value = newSet
    }
    _anchorKey = null
  }

  /**
   * 清空选中
   */
  function clearSelection() {
    if (selectedKeys.value.size === 0) return
    selectedKeys.value = new Set()
    _anchorKey = null
  }

  /**
   * 获取所有选中的 key 数组（用于传递给后端）
   * @returns {(string|number)[]}
   */
  function getSelectedKeys() {
    return [...selectedKeys.value]
  }

  // ── 内部方法 ──

  /**
   * Toggle 单个 key
   */
  function _toggle(key) {
    const next = new Set(selectedKeys.value)
    if (next.has(key)) {
      next.delete(key)
    } else {
      next.add(key)
    }
    selectedKeys.value = next
  }

  /**
   * Shift 范围选择
   */
  function _rangeSelect(targetKey, targetIndex) {
    const items = getItems()
    if (!items || items.length === 0) {
      _toggle(targetKey)
      return
    }

    // 查找锚点在排序数组中的索引
    let anchorIndex = -1
    for (let i = 0; i < items.length; i++) {
      if (getKey(items[i]) === _anchorKey) {
        anchorIndex = i
        break
      }
    }

    // 锚点不在当前数组中，降级为普通 toggle
    if (anchorIndex === -1) {
      _toggle(targetKey)
      _anchorKey = targetKey
      return
    }

    // 计算范围 [start, end]
    const start = Math.min(anchorIndex, targetIndex)
    const end = Math.max(anchorIndex, targetIndex)

    const next = new Set(selectedKeys.value)
    for (let i = start; i <= end; i++) {
      next.add(getKey(items[i]))
    }
    selectedKeys.value = next
  }

  // ── 数据变更时清理无效 key ──
  // 当数据源变化（如删除行、切换报文）时，移除不再存在的 key
  watch(
    () => {
      const items = getItems()
      if (!items) return null
      return items.map(getKey).join('\x00')
    },
    () => {
      const items = getItems()
      if (!items || items.length === 0) {
        if (selectedKeys.value.size > 0) {
          selectedKeys.value = new Set()
          _anchorKey = null
        }
        return
      }
      const validKeys = new Set(items.map(getKey))
      const currentKeys = selectedKeys.value
      let needsClean = false
      for (const k of currentKeys) {
        if (!validKeys.has(k)) {
          needsClean = true
          break
        }
      }
      if (needsClean) {
        const next = new Set()
        for (const k of currentKeys) {
          if (validKeys.has(k)) next.add(k)
        }
        selectedKeys.value = next
      }
      // 锚点失效时重置
      if (_anchorKey != null && !validKeys.has(_anchorKey)) {
        _anchorKey = null
      }
    }
  )

  return {
    selectedKeys,
    selectedCount,
    allSelected,
    someSelected,
    isMultiSelect,
    isSelected,
    handleRowClick,
    toggleCheckbox,
    toggleAll,
    clearSelection,
    getSelectedKeys,
  }
}
