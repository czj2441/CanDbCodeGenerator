import { describe, it } from 'node:test'
import assert from 'node:assert'
import { computeOccupiedBits, occupiedBitsToCells, computeCellMap } from '../signalLayout.js'

describe('computeOccupiedBits', () => {
  it('intel 线性占用 0..7', () => {
    const s = computeOccupiedBits([{ start_bit: 0, length: 8, byte_order: 'intel' }])
    assert.deepStrictEqual([...s].sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6, 7])
  })

  it('motorola 跨字节锯齿占用 8..23', () => {
    const s = computeOccupiedBits([{ start_bit: 15, length: 16, byte_order: 'motorola' }])
    const want = Array.from({ length: 16 }, (_, i) => 8 + i)
    assert.deepStrictEqual([...s].sort((a, b) => a - b), want)
  })

  it('多信号取并集', () => {
    const s = computeOccupiedBits([
      { start_bit: 0, length: 4, byte_order: 'intel' },
      { start_bit: 8, length: 4, byte_order: 'intel' },
    ])
    assert.strictEqual(s.size, 8)
  })
})

describe('occupiedBitsToCells', () => {
  it('裁剪 row >= dlc 的越界 bit', () => {
    const cells = occupiedBitsToCells(new Set([0, 8, 64]), 1)
    assert.strictEqual(cells.length, 1)
    assert.strictEqual(cells[0].bit, 0)
  })

  it('忽略 NaN / 非有限 bit', () => {
    const cells = occupiedBitsToCells(new Set([0, NaN, undefined, Infinity]), 8)
    assert.deepStrictEqual(cells.map(c => c.bit), [0])
  })
})

describe('computeCellMap 与 occupiedBits 重叠', () => {
  it('新信号 cell 与 occupiedBits 相交 → 进入 overlapBits', () => {
    const occupied = new Set([4])
    const { cells, overlapBits } = computeCellMap(
      [{ name: 'A', start_bit: 0, length: 8, byte_order: 'intel' }],
      {},
      occupied,
    )
    assert.strictEqual(cells.length, 8)
    assert.deepStrictEqual([...overlapBits], [4])
  })

  it('空 occupiedBits → 无重叠、正常 cells', () => {
    const { cells, overlapBits } = computeCellMap(
      [{ name: 'A', start_bit: 0, length: 8, byte_order: 'intel' }],
      {},
      new Set(),
    )
    assert.strictEqual(cells.length, 8)
    assert.strictEqual(overlapBits.size, 0)
  })
})
