/**
 * batchAddSignals 布局与收敛性单元测试
 *
 * computeBatchSignals() 规则（保证收敛：间隔一致、互不重叠，放不下的信号跳过）：
 *   1. 首个信号可换算 → 全部信号沿字节序原生方向推进 length + interval
 *   2. 首个信号无法换算 → 首个及锚点前信号标记 invalid，找到首个可换算的后续信号作锚点，其后同样沿原生方向推进
 *   3. 占用位超出 [0, maxBit] → 标记 invalid 跳过，不中止整批
 *
 * Run with: node --test src/utils/__tests__/batchBoundary.test.js
 */
import { describe, it } from 'node:test'
import assert from 'node:assert'
import { computeBatchSignals, getSignalBits, bitToGridCell } from '../signalLayout.js'

function layout(count, startBit, interval, length, byteOrder, dlc) {
  return computeBatchSignals({ startBit, length, interval, byteOrder, count, maxBit: dlc * 8 - 1 })
}

function walkPos(bit) {
  const { row, col } = bitToGridCell(bit)
  return row * 8 + col
}

function walkPosToBit(p) {
  return Math.floor(p / 8) * 8 + (7 - (p % 8))
}

/** 收敛性断言：有效信号互不重叠、占用位在 [0,maxBit] 内、相邻间隔一致 */
function assertConverged(layouts, length, interval, byteOrder, dlc) {
  const maxBit = dlc * 8 - 1
  const step = length + interval
  const valids = layouts.filter(s => s.valid)
  const all = new Set()
  for (const s of valids) {
    for (const b of getSignalBits(s.start_bit, length, byteOrder)) {
      assert.ok(b >= 0 && b <= maxBit, `bit ${b} 超出 [0,${maxBit}]`)
      assert.ok(!all.has(b), `bit ${b} 被重复占用`)
      all.add(b)
    }
  }
  for (let i = 1; i < valids.length; i++) {
    const gap = byteOrder === 'intel'
      ? valids[i].start_bit - valids[i - 1].start_bit
      : walkPos(valids[i].start_bit) - walkPos(valids[i - 1].start_bit)
    assert.strictEqual(gap, step, `相邻有效信号间隔应为 ${step}，实际 ${gap}`)
  }
}

// ── Intel 字节序测试 ──

describe('Intel 字节序', () => {
  it('8 个 8-bit interval=0 紧密连接，全部有效', () => {
    const r = layout(8, 0, 0, 8, 'intel', 8)
    assert.ok(r.every(x => x.valid))
    assert.deepStrictEqual(r.map(x => x.start_bit), [0, 8, 16, 24, 32, 40, 48, 56])
  })

  it('单个信号恰好在边界 (56) — 有效', () => {
    assert.strictEqual(layout(1, 56, 0, 8, 'intel', 8)[0].valid, true)
  })

  it('单个信号超出边界 (57) — 无效跳过', () => {
    assert.strictEqual(layout(1, 57, 0, 8, 'intel', 8)[0].valid, false)
  })

  it('批量中最后一个超出边界 — 仅最后一个无效，其余创建', () => {
    // 9 个 8-bit，前 8 个占 0-63，第 9 个从 64 越界
    const r = layout(9, 0, 0, 8, 'intel', 8)
    assert.ok(r.slice(0, 8).every(x => x.valid))
    assert.strictEqual(r[8].valid, false)
  })

  it('count=1 单信号', () => {
    assert.strictEqual(layout(1, 0, 0, 1, 'intel', 1)[0].valid, true)
    assert.strictEqual(layout(1, 8, 0, 1, 'intel', 1)[0].valid, false)
  })

  it('间隔=8 — 间隔 8 bit', () => {
    const r = layout(3, 0, 8, 8, 'intel', 8)
    assert.ok(r.every(x => x.valid))
    assert.deepStrictEqual(r.map(x => x.start_bit), [0, 16, 32])
  })

  it('length=64 填满整个报文', () => {
    assert.strictEqual(layout(1, 0, 0, 64, 'intel', 8)[0].valid, true)
  })
})

// ── Motorola 字节序测试 ──

describe('Motorola 字节序', () => {
  it('8 个 8-bit interval=0 — 每字节一条', () => {
    const r = layout(8, 0, 0, 8, 'motorola', 8)
    assert.ok(r.every(x => x.valid))
    assert.deepStrictEqual(r.map(x => x.start_bit), [7, 15, 23, 31, 39, 47, 55, 63])
    assert.deepStrictEqual(r.map(x => x.display_start_bit), [0, 8, 16, 24, 32, 40, 48, 56])
  })

  it('DLC=2 两个 8-bit 均合法', () => {
    const r = layout(2, 0, 0, 8, 'motorola', 2)
    assert.ok(r.every(x => x.valid))
    assert.deepStrictEqual(r.map(x => x.start_bit), [7, 15])
  })

  it('跨字节 16-bit 越界 — 第二个信号无效跳过，不中止整批', () => {
    // DLC=4，LSB=16/len=16：信号1 MSB=15 填 Byte1-2；信号2 MSB=31 → 位 39 越界
    const r = layout(2, 16, 0, 16, 'motorola', 4)
    assert.strictEqual(r[0].valid, true)
    assert.strictEqual(r[1].valid, false)
  })

  it('真实越界 — 16-bit 信号放不进 DLC=1', () => {
    assert.strictEqual(layout(1, 8, 0, 16, 'motorola', 1)[0].valid, false)
    assert.strictEqual(layout(1, 8, 0, 16, 'motorola', 2)[0].valid, true)
    assert.strictEqual(layout(1, 16, 0, 16, 'motorola', 2)[0].valid, false)
  })

  it('count=1 单信号', () => {
    assert.strictEqual(layout(1, 0, 0, 8, 'motorola', 1)[0].valid, true)
    assert.strictEqual(layout(1, 9, 0, 8, 'motorola', 1)[0].valid, false)
  })

  it('间隔=8 — 空一个字节', () => {
    const r = layout(3, 0, 8, 8, 'motorola', 8)
    assert.ok(r.every(x => x.valid))
    assert.deepStrictEqual(r.map(x => x.start_bit), [7, 23, 39])
  })
})

// ── 已知问题场景 ──

describe('已知问题场景', () => {
  it('Motorola 间隔=1 起始位 0 — 第二信号 MSB=14、LSB=23', () => {
    const r = layout(2, 0, 1, 8, 'motorola', 8)
    assert.ok(r.every(x => x.valid))
    assert.strictEqual(r[0].start_bit, 7)
    assert.strictEqual(r[1].start_bit, 14)
    assert.strictEqual(r[1].display_start_bit, 23)
  })

  it('Motorola 间隔=2 起始位 15 — 沿锯齿推进，间隔一致', () => {
    const r = layout(4, 15, 2, 8, 'motorola', 8)
    assert.ok(r.every(x => x.valid))
    assert.deepStrictEqual(r.map(x => x.start_bit), [6, 12, 18, 24])
    assert.deepStrictEqual(r.map(x => x.display_start_bit), [15, 21, 27, 33])
  })

  it('Motorola 间隔=4 起始位 2 — 统一网格：首无效，PTA02/03 MSB=13/17', () => {
    // slotStart0 = walkPos(2)-7 = -2；step=12
    // slot1=[10,17]→MSB13/LSB22；slot2=[22,29]→MSB17/LSB26；slot3=[34,41]→MSB37/LSB46；slot4=[46,53]→MSB41/LSB50
    const r = layout(8, 2, 4, 8, 'motorola', 8)
    assert.strictEqual(r[0].valid, false)
    assert.strictEqual(r[0].display_start_bit, 2)
    assert.deepStrictEqual(r.slice(1, 5).map(x => x.valid), [true, true, true, true])
    assert.deepStrictEqual(r.slice(1, 5).map(x => x.start_bit), [13, 17, 37, 41])
    assert.deepStrictEqual(r.slice(1, 5).map(x => x.display_start_bit), [22, 26, 46, 50])
    assert.strictEqual(r[5].valid, false)
    assert.strictEqual(r[6].valid, false)
    assert.strictEqual(r[7].valid, false)
  })

  it('Motorola 间隔=4 起始位 4 — 统一网格：PTA02 MSB=15/LSB=8', () => {
    // slotStart0 = walkPos(4)-7 = -4；step=12
    // slot1=[8,15]→MSB15/LSB8（用户确认）；slot2=[20,27]→MSB19/LSB28；slot3=[32,39]→MSB39/LSB32；slot4=[44,51]→MSB43/LSB52；slot5=[56,63]→MSB63/LSB56
    const r = layout(8, 4, 4, 8, 'motorola', 8)
    assert.strictEqual(r[0].valid, false)
    assert.strictEqual(r[0].display_start_bit, 4)
    assert.deepStrictEqual(r.slice(1, 6).map(x => x.valid), [true, true, true, true, true])
    assert.deepStrictEqual(r.slice(1, 6).map(x => x.start_bit), [15, 19, 39, 43, 63])
    assert.deepStrictEqual(r.slice(1, 6).map(x => x.display_start_bit), [8, 28, 32, 52, 56])
    assert.strictEqual(r[1].start_bit, 15, 'PTA02 MSB 应为 15')
    assert.strictEqual(r[1].display_start_bit, 8, 'PTA02 LSB 应为 8')
    assert.strictEqual(r[6].valid, false)
    assert.strictEqual(r[7].valid, false)
  })

  it('Motorola 首信号无效（LSB=3, interval=0）— 锚点后平铺', () => {
    const r = layout(8, 3, 0, 8, 'motorola', 8)
    assert.strictEqual(r[0].valid, false)
    assert.strictEqual(r[0].display_start_bit, 3)
    assert.ok(r.slice(1).every(x => x.valid))
    assert.strictEqual(r[1].start_bit, 2)
    assert.strictEqual(r[1].display_start_bit, 11)
    assert.deepStrictEqual(r.slice(1).map(x => x.start_bit), [2, 10, 18, 26, 34, 42, 50])
    assert.deepStrictEqual(r.slice(1).map(x => x.display_start_bit), [11, 19, 27, 35, 43, 51, 59])
  })

  it('全无效批次（count=1 且首个无效）', () => {
    const r = layout(1, 3, 0, 8, 'motorola', 8)
    assert.strictEqual(r[0].valid, false)
  })
})

// ── 10 组随机有效用例收敛性 ──

describe('10 组随机有效用例收敛性', () => {
  let seed = 20260805
  const rnd = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const randInt = (a, b) => a + Math.floor(rnd() * (b - a + 1))
  const dlcs = [1, 2, 4, 8]

  for (let t = 0; t < 10; t++) {
    const dlc = dlcs[randInt(0, 3)]
    const totalBits = dlc * 8
    const byteOrder = rnd() < 0.5 ? 'intel' : 'motorola'
    const length = randInt(1, Math.min(16, totalBits))
    const interval = randInt(0, 8)
    const count = randInt(1, 8)
    // 保证首个信号有效（有效用例）：起始位取一个合法槽位的 LSB
    const startBit = byteOrder === 'intel'
      ? randInt(0, totalBits - length)
      : walkPosToBit(randInt(0, totalBits - length) + length - 1)

    it(`用例${t + 1}: dlc=${dlc} ${byteOrder} len=${length} interval=${interval} count=${count} startBit=${startBit}`, () => {
      const r = layout(count, startBit, interval, length, byteOrder, dlc)
      assert.strictEqual(r[0].valid, true, '首个信号应有效')
      assertConverged(r, length, interval, byteOrder, dlc)
    })
  }
})
