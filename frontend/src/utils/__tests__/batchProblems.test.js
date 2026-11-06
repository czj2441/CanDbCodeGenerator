import { describe, it } from 'node:test'
import assert from 'node:assert'
import { analyzeBatchProblems, computeOccupiedBits } from '../signalLayout.js'

function sig(name, start_bit, length, byte_order = 'intel', _invalid = false) {
  return { name, start_bit, length, byte_order, _invalid }
}

describe('analyzeBatchProblems', () => {
  it('无问题', () => {
    const r = analyzeBatchProblems([sig('A', 0, 8)], new Set(), [])
    assert.deepStrictEqual(r, {
      invalidCount: 0, overlapSignalCount: 0, overlapBits: 0, duplicateCount: 0, hasProblems: false,
    })
  })

  it('越界无效信号计数', () => {
    const r = analyzeBatchProblems([sig('A', 0, 8, 'intel', true)], new Set(), [])
    assert.strictEqual(r.invalidCount, 1)
    assert.strictEqual(r.hasProblems, true)
  })

  it('Intel 与已有信号重叠', () => {
    const occupied = computeOccupiedBits([{ start_bit: 0, length: 8, byte_order: 'intel' }])
    const r = analyzeBatchProblems([sig('A', 4, 8)], occupied, [])
    assert.strictEqual(r.overlapSignalCount, 1)
    assert.strictEqual(r.overlapBits, 4)
  })

  it('Motorola 与已有信号重叠', () => {
    const occupied = computeOccupiedBits([{ start_bit: 15, length: 8, byte_order: 'motorola' }])
    const r = analyzeBatchProblems([sig('A', 15, 8, 'motorola')], occupied, [])
    assert.strictEqual(r.overlapSignalCount, 1)
    assert.strictEqual(r.overlapBits, 8)
  })

  it('与已有信号同名', () => {
    const r = analyzeBatchProblems([sig('PTA01', 0, 8)], new Set(), ['PTA01'])
    assert.strictEqual(r.duplicateCount, 1)
  })

  it('批内同名', () => {
    const r = analyzeBatchProblems([sig('X', 0, 8), sig('X', 8, 8)], new Set(), [])
    assert.strictEqual(r.duplicateCount, 2)
  })

  it('无效信号不计入重叠与重名', () => {
    const occupied = computeOccupiedBits([{ start_bit: 0, length: 8, byte_order: 'intel' }])
    const r = analyzeBatchProblems([sig('A', 0, 8, 'intel', true)], occupied, ['A'])
    assert.strictEqual(r.invalidCount, 1)
    assert.strictEqual(r.overlapSignalCount, 0)
    assert.strictEqual(r.overlapBits, 0)
    assert.strictEqual(r.duplicateCount, 0)
  })

  it('多类问题同时存在', () => {
    const occupied = computeOccupiedBits([{ start_bit: 0, length: 8, byte_order: 'intel' }])
    const r = analyzeBatchProblems([
      sig('A', 0, 8, 'intel', true),    // 无效，跳过
      sig('B', 0, 8),                   // 重叠 + 与已有同名
      sig('C', 8, 8), sig('C', 16, 8),  // 批内同名
    ], occupied, ['A', 'B'])
    assert.strictEqual(r.invalidCount, 1)
    assert.strictEqual(r.overlapSignalCount, 1)
    assert.strictEqual(r.overlapBits, 8)
    assert.strictEqual(r.duplicateCount, 3)  // B + 2×C
    assert.strictEqual(r.hasProblems, true)
  })
})
