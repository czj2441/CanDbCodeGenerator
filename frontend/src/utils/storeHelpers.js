/**
 * Store 工具函数
 *
 * 从 editor.js 提取的通用辅助逻辑，供多个 Pinia store 共享使用。
 */

import { t } from '../i18n.js'
import { getSignalBits } from './signalLayout.js'

export { getSignalBits }  // re-export for convenience

/**
 * 将后端校验错误翻译为 i18n 文本。
 * 若 error_code 对应的翻译不存在，则 fallback 到原始 e.message。
 */
export function translateError(e) {
  const errorCode = e.details?.error_code
  if (!errorCode) return e.message
  const i18nKey = `toast.validation.${errorCode}`
  const translated = t(i18nKey, e.details || {})
  return translated !== i18nKey ? translated : e.message
}

// ── 信号位布局计算（与后端 models.py 保持一致） ──

/**
 * 在报文中寻找第一个足够大的空闲区间
 * @param {Array} signals - 当前报文的信号列表
 * @param {number} dlc - 报文 DLC
 * @param {number} length - 新信号长度
 * @param {string} byteOrder - 新信号字节序
 * @returns {number|null} 推荐的 start_bit，无空闲位置返回 null
 */
export function findNextAvailableStartBit(signals, dlc, length, byteOrder) {
  const maxBits = dlc * 8
  if (length > maxBits) return null

  const used = new Set()
  for (const s of signals) {
    for (const b of getSignalBits(s.start_bit, s.length, s.byte_order)) {
      used.add(b)
    }
  }

  // Intel: 从 bit 0 开始连续填充
  if (byteOrder !== 'motorola') {
    for (let candidate = 0; candidate < maxBits; candidate++) {
      const candidateBits = getSignalBits(candidate, length, byteOrder)
      let valid = true
      for (const b of candidateBits) {
        if (b < 0 || b >= maxBits || used.has(b)) {
          valid = false
          break
        }
      }
      if (valid) return candidate
    }
    return null
  }

  // Motorola: 三轮扫描策略
  // 第一轮：按字节遍历，优先尝试字节内紧凑位置（不跨字节）
  for (let byteIdx = 0; byteIdx < dlc; byteIdx++) {
    const byteBase = byteIdx * 8
    for (let offset = 7; offset >= length - 1 && offset >= 0; offset -= length) {
      const candidate = byteBase + offset
      if (candidate >= maxBits) continue
      const candidateBits = getSignalBits(candidate, length, byteOrder)
      let valid = true
      for (const b of candidateBits) {
        if (b < 0 || b >= maxBits || used.has(b)) {
          valid = false
          break
        }
      }
      if (valid) return candidate
    }
  }

  // 第二轮：优先尝试字节边界 MSB（7,15,23...），长信号通常从此开始
  for (let candidate = 7; candidate < maxBits; candidate += 8) {
    const candidateBits = getSignalBits(candidate, length, byteOrder)
    let valid = true
    for (const b of candidateBits) {
      if (b < 0 || b >= maxBits || used.has(b)) {
        valid = false
        break
      }
    }
    if (valid) return candidate
  }

  // 第三轮：全位扫描兜底（与后端保持一致），确保不遗漏任何有效位置
  for (let candidate = 0; candidate < maxBits; candidate++) {
    const candidateBits = getSignalBits(candidate, length, byteOrder)
    let valid = true
    for (const b of candidateBits) {
      if (b < 0 || b >= maxBits || used.has(b)) {
        valid = false
        break
      }
    }
    if (valid) return candidate
  }
  return null
}

// ── 报文 ID 生成器（模块级，同步递增避免异步竞争） ──
let _lastGeneratedMsgId = null

/**
 * 生成新的报文 ID（优先基于最后一次新增的 ID +1）
 * @param {Array} messages - 当前报文列表
 * @returns {number}
 */
export function generateMessageId(messages) {
  if (_lastGeneratedMsgId != null) {
    _lastGeneratedMsgId += 1
  } else {
    _lastGeneratedMsgId = messages.length > 0
      ? Math.max(...messages.map(m => m.id)) + 1
      : 0x300
  }
  return _lastGeneratedMsgId
}

/**
 * 重置报文 ID 生成器基线（会话切换后调用）
 */
export function resetMessageIdGenerator() {
  _lastGeneratedMsgId = null
}

/**
 * 生成唯一信号名：扫描已有信号名，提取同名前缀的最大数字后缀并 +1。
 * 例：已有 NewSignal, NewSignal2 → 返回 NewSignal3
 */
export function generateSignalName(signals, baseName = 'NewSignal') {
  const existingNames = new Set(signals.map(s => s.name))
  if (!existingNames.has(baseName)) return baseName
  let maxSuffix = 1
  const escaped = baseName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const pattern = new RegExp(`^${escaped}(\\d+)$`)
  for (const name of existingNames) {
    const m = name.match(pattern)
    if (m) maxSuffix = Math.max(maxSuffix, parseInt(m[1], 10))
  }
  return `${baseName}${maxSuffix + 1}`
}
