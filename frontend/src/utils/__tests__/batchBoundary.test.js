/**
 * batchAddSignals 边界检查单元测试
 *
 * 验证修复后的 Motorola/Intel 字节序边界检查逻辑：
 * - 使用 getSignalBits() 精确计算每个信号占用的 bit 集合
 * - 逐一检查是否越界 [0, maxBits)
 *
 * Run with: node --test src/utils/__tests__/batchBoundary.test.js
 */
import { describe, it } from 'node:test'
import assert from 'node:assert'
import { getSignalBits } from '../signalLayout.js'

/**
 * 模拟 signals.js 中 batchAddSignals() 的边界检查逻辑
 * 返回 null 表示全部合法，否则返回第一个越界的信号信息
 *
 * @param {number} count - 信号数量
 * @param {number} startBit - 起始 bit
 * @param {number} bitStep - 信号间 bit 步长
 * @param {number} length - 每个信号长度
 * @param {string} byteOrder - 'intel' | 'motorola'
 * @param {number} dlc - 报文 DLC
 * @returns {{ index: number, sb: number, badBit: number } | null}
 */
function checkBatchBoundary(count, startBit, bitStep, length, byteOrder, dlc) {
  const maxBits = dlc * 8
  for (let i = 0; i < count; i++) {
    const sb = startBit + i * bitStep
    const bits = getSignalBits(sb, length, byteOrder)
    for (const b of bits) {
      if (b < 0 || b >= maxBits) {
        return { index: i, sb, badBit: b }
      }
    }
  }
  return null
}

// ── Intel 字节序测试 ──

describe('Intel 字节序边界检查', () => {
  it('正常批量添加 — 全部在范围内', () => {
    // DLC=8 (64 bits), 8 个 8-bit 信号, startBit=0, bitStep=8
    const result = checkBatchBoundary(8, 0, 8, 8, 'intel', 8)
    assert.strictEqual(result, null, '8x8-bit signals should fit in 64-bit message')
  })

  it('单个信号恰好在边界', () => {
    // DLC=8 (64 bits), 1 个 8-bit 信号 at bit 56
    const result = checkBatchBoundary(1, 56, 0, 8, 'intel', 8)
    assert.strictEqual(result, null, 'signal at bit 56-63 should fit in 64-bit message')
  })

  it('单个信号超出边界 — 正确拒绝', () => {
    // DLC=8 (64 bits), 1 个 8-bit 信号 at bit 57 (ends at 64, out of range)
    const result = checkBatchBoundary(1, 57, 0, 8, 'intel', 8)
    assert.ok(result !== null, 'signal at bit 57-64 should exceed 64-bit message')
    assert.strictEqual(result.index, 0)
  })

  it('批量中最后一个超出边界', () => {
    // DLC=8 (64 bits), 9 个 8-bit 信号, startBit=0, bitStep=8
    // 前 8 个占用 0-63, 第 9 个从 bit 64 开始越界
    const result = checkBatchBoundary(9, 0, 8, 8, 'intel', 8)
    assert.ok(result !== null, '9th signal should exceed boundary')
    assert.strictEqual(result.index, 8, 'the 9th signal (index=8) should be the first bad one')
  })

  it('count=1 单信号合法', () => {
    const result = checkBatchBoundary(1, 0, 8, 1, 'intel', 1)
    assert.strictEqual(result, null)
  })

  it('count=1 单信号越界', () => {
    const result = checkBatchBoundary(1, 8, 8, 1, 'intel', 1)
    assert.ok(result !== null, 'bit 8 exceeds 8-bit message (DLC=1)')
  })
})

// ── Motorola 字节序测试 ──

describe('Motorola 字节序边界检查', () => {
  it('正常批量添加 — 全部在范围内', () => {
    // DLC=8 (64 bits), 8 个 8-bit Motorola 信号
    // MSB=7,15,23,31,39,47,55,63 → 各填满一个字节
    const result = checkBatchBoundary(8, 7, 8, 8, 'motorola', 8)
    assert.strictEqual(result, null, '8 Motorola 8-bit signals from MSB=7 step=8 should fit')
  })

  it('线性计算会误报的场景 — Motorola 实际合法', () => {
    // DLC=2 (16 bits), Motorola, startBit=7, bitStep=8, length=8, count=2
    // 线性计算: lastEnd = 7 + (2-1)*8 + 8 = 23 > 16 → 误报越界
    // 实际: Signal 0 MSB=7 → bits {7,6,5,4,3,2,1,0} 全部在 [0,16)
    //       Signal 1 MSB=15 → bits {15,14,13,12,11,10,9,8} 全部在 [0,16)
    const result = checkBatchBoundary(2, 7, 8, 8, 'motorola', 2)
    assert.strictEqual(result, null,
      'Motorola MSB=7 and MSB=15 with length=8 should both fit in 16-bit message')
  })

  it('另一个线性误报场景 — 跨字节 Motorola', () => {
    // DLC=4 (32 bits), Motorola, startBit=15, bitStep=16, length=16, count=2
    // 线性计算: lastEnd = 15 + (2-1)*16 + 16 = 47 > 32 → 误报
    // 实际: Signal 0 MSB=15 → 16 bits 填满 Byte2+Byte3 → {15..8, 23..16}
    //       Signal 1 MSB=31 → 16 bits 填满 Byte4+Byte5 → 但 DLC=4 只有 32 bits
    // MSB=31 的 16-bit Motorola: 31→30→...→24→39→38→...→32 → bit 39 超出!
    // 所以这个应该被正确拒绝
    const result = checkBatchBoundary(2, 15, 16, 16, 'motorola', 4)
    assert.ok(result !== null,
      'Second signal MSB=31 length=16 should exceed 32-bit (DLC=4) message')
    assert.strictEqual(result.index, 1)
  })

  it('Motorola 真实越界 — 正确拒绝', () => {
    // DLC=1 (8 bits), Motorola, startBit=7, length=16, count=1
    // MSB=7 走 16 步: 7→6→5→4→3→2→1→0→15→14→13→12→11→10→9→8
    // bit 15,14,...,8 超出 [0,8) 范围
    const result = checkBatchBoundary(1, 7, 0, 16, 'motorola', 1)
    assert.ok(result !== null, '16-bit Motorola signal in 8-bit message should exceed')
    assert.strictEqual(result.index, 0)
  })

  it('Motorola 跨字节边界合法 — 16-bit 信号填满两个字节', () => {
    // DLC=2 (16 bits), Motorola, startBit=15, length=16, count=1
    // MSB=15 → 15→14→...→8→23→22→...→16 → bit 23 超出!
    // 实际上 Motorola 16-bit 需要 MSB=7 才能填满 Byte0+Byte1
    // MSB=7: 7→6→...→0→15→14→...→8 ✓
    const resultOK = checkBatchBoundary(1, 7, 0, 16, 'motorola', 2)
    assert.strictEqual(resultOK, null, 'MSB=7 length=16 should fit in 16-bit message')

    const resultBad = checkBatchBoundary(1, 15, 0, 16, 'motorola', 2)
    assert.ok(resultBad !== null, 'MSB=15 length=16 should exceed 16-bit message')
  })

  it('count=1 单信号 Motorola 合法', () => {
    // DLC=1, Motorola, MSB=7, length=8 → 填满一个字节
    const result = checkBatchBoundary(1, 7, 0, 8, 'motorola', 1)
    assert.strictEqual(result, null)
  })

  it('count=1 单信号 Motorola 越界', () => {
    // DLC=1, Motorola, MSB=0, length=8
    // MSB=0 → 0→15→14→13→12→11→10→9 → bit 15 超出 [0,8)
    const result = checkBatchBoundary(1, 0, 0, 8, 'motorola', 1)
    assert.ok(result !== null, 'MSB=0 length=8 should exceed 8-bit message')
  })
})

// ── 边界情况 ──

describe('边界情况', () => {
  it('count=0 — 无信号，不触发检查', () => {
    const result = checkBatchBoundary(0, 0, 8, 8, 'intel', 8)
    assert.strictEqual(result, null, '0 signals should always pass')
  })

  it('length=1 单 bit 信号', () => {
    const result = checkBatchBoundary(64, 0, 1, 1, 'intel', 8)
    assert.strictEqual(result, null, '64 single-bit signals should fit in 64-bit message')
  })

  it('length=64 填满整个报文', () => {
    // Intel: startBit=0, length=64, DLC=8 → 恰好填满
    const result = checkBatchBoundary(1, 0, 0, 64, 'intel', 8)
    assert.strictEqual(result, null, '64-bit Intel signal should fill 64-bit message')
  })

  it('DLC=1 小报文 Motorola', () => {
    // DLC=1 (8 bits), Motorola, MSB=3, length=4
    // 3→2→1→0 ✓ 全部在 [0,8)
    const result = checkBatchBoundary(1, 3, 0, 4, 'motorola', 1)
    assert.strictEqual(result, null)
  })
})
