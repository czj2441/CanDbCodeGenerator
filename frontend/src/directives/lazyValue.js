/**
 * v-lazy-value 自定义指令
 *
 * 与 :value 绑定类似，但当输入框处于聚焦状态（用户正在编辑）时，
 * 不会用 store 中的旧值覆盖 DOM 的当前值，从而保护用户未 blur 的编辑内容。
 *
 * 用法：
 *   <input v-lazy-value="sig.name" @blur="onBlur">
 *
 * 原理：
 * - 记录 el.__lastCommitted 为上次设置的值
 * - mounted/updated 时，若值未变或 el === document.activeElement，跳过 DOM 写入
 * - 失焦后下次 updated 自然同步新值
 */
export const vLazyValue = {
  mounted(el, binding) {
    el.__lastCommitted = binding.value
    // 首次设置 DOM 值
    if (el.value !== String(binding.value ?? '')) {
      el.value = binding.value ?? ''
    }
  },
  updated(el, binding) {
    const newVal = binding.value
    // 值未变化 → 跳过
    if (newVal === el.__lastCommitted) return
    // 输入框正在聚焦 → 不覆盖用户正在编辑的内容
    if (el === document.activeElement) return
    // 正常更新
    el.__lastCommitted = newVal
    if (el.value !== String(newVal ?? '')) {
      el.value = newVal ?? ''
    }
  }
}

/**
 * v-lazy-select 自定义指令（用于 <select> 元素）
 *
 * 与 v-lazy-value 同理，但 select 不存在用户"正在编辑"的情况，
 * 保留此指令仅为统一用法，实际 select 可直接用 :value。
 */
export const vLazySelect = {
  mounted(el, binding) {
    el.__lastCommitted = binding.value
    if (el.value !== String(binding.value ?? '')) {
      el.value = binding.value ?? ''
    }
  },
  updated(el, binding) {
    const newVal = binding.value
    if (newVal === el.__lastCommitted) return
    el.__lastCommitted = newVal
    if (el.value !== String(newVal ?? '')) {
      el.value = newVal ?? ''
    }
  }
}
