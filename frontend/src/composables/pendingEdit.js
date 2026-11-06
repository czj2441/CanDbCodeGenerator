/**
 * 统一的“待提交编辑”注册表。
 *
 * 背景：属性面板的输入框依赖 blur 提交，而列表在 mousedown 阶段就切换了
 * 全局选中项。浏览器事件顺序是 mousedown → blur，如果不提前提交，blur
 * 处理器会读到新选中项，把编辑值写到新目标上。
 *
 * 本模块不依赖任何 store，避免循环依赖。面板在 focusin 时快照目标，
 * blur / change 时取走快照提交；选中 action 在修改选中前调用
 * flushPendingEdit() 同步 blur。
 */

const pendingEdits = new Map()
const EDITABLE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

export const PENDING_EDIT_OWNERS = Object.freeze({
  signalPanel: 'signal-panel',
  messagePanel: 'message-panel',
  valueTablePanel: 'value-table-panel',
})

/**
 * 记录一次待提交编辑的目标。
 * @param {string} owner
 * @param {object} target 开始编辑时捕获的目标（不含输入值）
 * @param {{ cancel?: (target: object) => void }} [options]
 */
export function beginPendingEdit(owner, target, { cancel } = {}) {
  pendingEdits.set(owner, { target, cancel })
}

/** 读取当前待提交目标，不清除。 */
export function peekPendingEdit(owner) {
  return pendingEdits.get(owner)?.target ?? null
}

/** 取走并清除当前待提交目标。 */
export function takePendingEditTarget(owner) {
  const entry = pendingEdits.get(owner)
  if (!entry) return null
  pendingEdits.delete(owner)
  return entry.target
}

/** 清除待提交目标，不触发 cancel 回调。 */
export function clearPendingEdit(owner) {
  pendingEdits.delete(owner)
}

/**
 * 取消待提交编辑。
 * @param {string} owner
 * @param {(target: object) => boolean} [predicate] 返回 false 时保留快照
 */
export function cancelPendingEdit(owner, predicate) {
  const entry = pendingEdits.get(owner)
  if (!entry) return
  if (predicate && !predicate(entry.target)) return
  pendingEdits.delete(owner)
  try {
    entry.cancel?.(entry.target)
  } catch (e) {
    console.error('[pendingEdit] cancel callback failed', e)
  }
}

/** 目标被重命名/改 id 时同步更新快照，不触发提交。 */
export function remapPendingEditTarget(owner, mapper) {
  const entry = pendingEdits.get(owner)
  if (!entry) return
  const next = mapper(entry.target)
  if (next != null) entry.target = next
}

/** 取消全部待提交编辑（会话重置、全量同步、undo/redo）。 */
export function cancelAllPendingEdits() {
  for (const owner of [...pendingEdits.keys()]) cancelPendingEdit(owner)
}

/**
 * 同步提交当前焦点控件里尚未失焦的编辑。
 *
 * 必须在修改选中项之前调用：此时 blur 处理器读到的仍是旧目标。
 * 不等待网络请求。注册表为空时直接返回——表格方向键导航会在聚焦
 * 单元格后调用选中 action，无条件 blur 会夺走刚聚焦的元素。
 */
export function flushPendingEdit() {
  if (pendingEdits.size === 0) return
  const el = typeof document !== 'undefined' ? document.activeElement : null
  if (el && EDITABLE_TAGS.has(el.tagName) && typeof el.blur === 'function') {
    el.blur()
  }
  for (const owner of [...pendingEdits.keys()]) {
    cancelPendingEdit(owner)
    if (import.meta.env?.DEV) {
      console.warn(`[pendingEdit] discarded un-flushed edit for ${owner}`)
    }
  }
}

/**
 * 面板接入封装。
 * @param {string} owner
 * @param {() => object} getTarget 返回“当前选中项”对应的目标
 */
export function usePanelEdit(owner, getTarget) {
  return {
    /** focusin 时调用，快照目标。 */
    begin() {
      const target = getTarget()
      if (target) beginPendingEdit(owner, target)
    },
    peek() { return peekPendingEdit(owner) },
    take() { return takePendingEditTarget(owner) },
    /** 取快照；没有快照时回退到当前目标（用于编程式调用）。 */
    snapshot() { return takePendingEditTarget(owner) ?? (getTarget() || null) },
    clear() { clearPendingEdit(owner) },
    cancel() { cancelPendingEdit(owner) },
    /** 用快照目标执行提交，常用在 blur / change 处理器中。 */
    commit(fn) {
      const target = takePendingEditTarget(owner) ?? getTarget()
      if (target == null) return undefined
      return fn(target)
    },
  }
}