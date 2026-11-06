import { describe, it } from 'node:test'
import assert from 'node:assert'
import { analyzeBatchProblems, formatBitRanges } from '../signalLayout.js'

function sig(name, start_bit, length, byte_order = 'intel', _invalid = false, display_start_bit = start_bit) {
  return { name, start_bit, display_start_bit, length, byte_order, _invalid }
}

function ex(name, start_bit, length, byte_order = 'intel') {
  return { name, start_bit, length, byte_order }
}

describe('analyzeBatchProblems', () => {
  it('无问题', () => {
    const r = analyzeBatchProblems([sig('A', 0, 8)], [])
    assert.deepStrictEqual(r, {
      invalid: [], overlaps: [], duplicates: [], hasProblems: false,
    })
  })

  it('越界无效信号带名称与起始位', () => {
    const r = analyzeBatchProblems([sig('A', 0, 8, 'intel', true, 40)], [])
    assert.deepStrictEqual(r.invalid, [{ name: 'A', startBit: 40 }])
    assert.strictEqual(r.hasProblems, true)
  })

  it('Intel 与已有信号重叠，带冲突名与 bit', () => {
    const r = analyzeBatchProblems([sig('N', 4, 8)], [ex('E', 0, 8)])
    assert.strictEqual(r.overlaps.length, 1)
    assert.strictEqual(r.overlaps[0].name, 'N')
    assert.deepStrictEqual(r.overlaps[0].others, ['E'])
    assert.deepStrictEqual(r.overlaps[0].bits, [4, 5, 6, 7])
  })

  it('Motorola 与已有信号重叠，按锯齿 bit 计算', () => {
    const r = analyzeBatchProblems([sig('N', 15, 8, 'motorola')], [ex('E', 15, 8, 'motorola')])
    assert.strictEqual(r.overlaps.length, 1)
    assert.deepStrictEqual(r.overlaps[0].bits, [8, 9, 10, 11, 12, 13, 14, 15])
  })

  it('与已有信号同名', () => {
    const r = analyzeBatchProblems([sig('X', 0, 8)], [ex('X', 0, 8)])
    assert.deepStrictEqual(r.duplicates, [{ name: 'X', kind: 'existing', count: 1 }])
  })

  it('批内同名合并为一条并给次数', () => {
    const r = analyzeBatchProblems([sig('X', 0, 8), sig('X', 8, 8)], [])
    assert.deepStrictEqual(r.duplicates, [{ name: 'X', kind: 'batch', count: 2 }])
  })

  it('无效信号不计入重叠与重名', () => {
    const r = analyzeBatchProblems(
      [sig('A', 0, 8, 'intel', true, 40)],
      [ex('E', 0, 8), ex('A', 0, 8)],
    )
    assert.strictEqual(r.invalid.length, 1)
    assert.strictEqual(r.overlaps.length, 0)
    assert.strictEqual(r.duplicates.length, 0)
  })

  it('多类问题同时存在', () => {
    const r = analyzeBatchProblems([
      sig('A', 0, 8, 'intel', true, 40),  // 无效
      sig('B', 0, 8),                     // 与 E 重叠
      sig('C', 8, 8), sig('C', 16, 8),    // 批内同名
    ], [ex('E', 0, 8)])
    assert.deepStrictEqual(r.invalid, [{ name: 'A', startBit: 40 }])
    assert.strictEqual(r.overlaps.length, 1)
    assert.strictEqual(r.overlaps[0].name, 'B')
    assert.deepStrictEqual(r.overlaps[0].bits, [0, 1, 2, 3, 4, 5, 6, 7])
    assert.deepStrictEqual(r.duplicates, [{ name: 'C', kind: 'batch', count: 2 }])
    assert.strictEqual(r.hasProblems, true)
  })
})

describe('formatBitRanges', () => {
  it('空数组返回空串', () => {
    assert.strictEqual(formatBitRanges([]), '')
  })

  it('单 bit', () => {
    assert.strictEqual(formatBitRanges([5]), '5')
  })

  it('连续与离散区间', () => {
    assert.strictEqual(formatBitRanges([0, 1, 2, 5]), '0-2, 5')
    assert.strictEqual(formatBitRanges([3, 1, 2, 9, 7, 8]), '1-3, 7-9')
  })
})