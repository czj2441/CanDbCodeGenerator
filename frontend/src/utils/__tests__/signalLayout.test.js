/**
 * Unit tests for signalLayout.js
 * Run with: node --test src/utils/__tests__/signalLayout.test.js
 */
import { describe, it } from 'node:test'
import assert from 'node:assert'
import { getSignalBits, validStartBitRangeOptimized, clampStartBit, signalToRenderData } from '../signalLayout.js'

// ── Helpers ──
function bruteMinMax(length, byteOrder, maxBit) {
  let minStart = Infinity
  let maxStart = -Infinity
  for (let s = 0; s <= maxBit + 100; s++) {
    const bits = getSignalBits(s, length, byteOrder)
    const min = Math.min(...bits)
    const max = Math.max(...bits)
    if (min >= 0 && max <= maxBit) {
      if (s < minStart) minStart = s
      if (s > maxStart) maxStart = s
    }
  }
  if (minStart === Infinity) return { minStart: -1, maxStart: -1 }
  return { minStart, maxStart }
}

function isValidStartBit(s, length, byteOrder, maxBit) {
  const bits = getSignalBits(s, length, byteOrder)
  const min = Math.min(...bits)
  const max = Math.max(...bits)
  return min >= 0 && max <= maxBit
}

function bruteNearestValid(candidate, length, byteOrder, maxBit) {
  if (length > maxBit + 1) return -1
  if (byteOrder === 'little_endian') {
    return Math.max(0, Math.min(maxBit - length + 1, candidate))
  }
  let bestS = -1
  let bestDist = Infinity
  for (let s = 0; s <= maxBit + 100; s++) {
    if (isValidStartBit(s, length, byteOrder, maxBit)) {
      const dist = Math.abs(s - candidate)
      if (dist < bestDist || (dist === bestDist && s < bestS)) {
        bestDist = dist
        bestS = s
      }
    }
  }
  return bestS
}

function assertRangeEqual(actual, expected, label) {
  const msg = `${label}: expected {${expected.minStart},${expected.maxStart}} got {${actual.minStart},${actual.maxStart}}`
  assert.strictEqual(actual.minStart, expected.minStart, msg)
  assert.strictEqual(actual.maxStart, expected.maxStart, msg)
}

// ── Test matrix ──
const dlcs = [1, 2, 4, 8]
const lengths = [1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64]
const byteOrders = ['little_endian', 'big_endian']

describe('validStartBitRangeOptimized', () => {
  for (const dlc of dlcs) {
    const maxBit = dlc * 8 - 1
    for (const length of lengths) {
      for (const byteOrder of byteOrders) {
        const label = `dlc=${dlc} maxBit=${maxBit} length=${length} byteOrder=${byteOrder}`
        it(label, () => {
          const expected = bruteMinMax(length, byteOrder, maxBit)
          const actual = validStartBitRangeOptimized(length, byteOrder, maxBit)
          assertRangeEqual(actual, expected, label)
        })
      }
    }
  }
})

describe('clampStartBit', () => {
  for (const dlc of dlcs) {
    const maxBit = dlc * 8 - 1
    for (const length of lengths) {
      for (const byteOrder of byteOrders) {
        const labelPrefix = `dlc=${dlc} maxBit=${maxBit} length=${length} byteOrder=${byteOrder}`
        // Test a few candidate values around the range
        const candidates = [
          -5, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
          maxBit - 10, maxBit - 5, maxBit, maxBit + 5, maxBit + 10,
        ]
        for (const candidate of candidates) {
          it(`${labelPrefix} candidate=${candidate}`, () => {
            const expected = bruteNearestValid(candidate, length, byteOrder, maxBit)
            const actual = clampStartBit(candidate, length, byteOrder, maxBit)
            assert.strictEqual(actual, expected, `${labelPrefix} candidate=${candidate}: expected ${expected} got ${actual}`)
          })
        }
      }
    }
  }
})

describe('signalToRenderData (Intel little_endian)', () => {
  const lengthsIntel = [1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64]
  const startBitsIntel = [0, 1, 2, 3, 4, 5, 6, 7, 8, 15, 16, 17, 23, 24, 31, 32, 55, 56, 63]
  const dlcsIntel = [1, 2, 4, 8]
  const defaultOptions = { cellSize: 36, headerH: 32, labelWidth: 44 }

  function makeSignal(startBit, length) {
    return {
      uuid: `s_${startBit}_${length}`,
      name: `Signal_${startBit}_${length}`,
      start_bit: startBit,
      length,
      byte_order: 'little_endian',
    }
  }

  for (const dlc of dlcsIntel) {
    const maxBit = dlc * 8 - 1
    for (const length of lengthsIntel) {
      for (const startBit of startBitsIntel) {
        // skip impossible combinations
        if (startBit + length - 1 > maxBit) continue

        const label = `dlc=${dlc} length=${length} startBit=${startBit}`
        it(label, () => {
          const signal = makeSignal(startBit, length)
          const data = signalToRenderData(signal, dlc, defaultOptions)

          // 1. all rects inside grid
          for (const r of data.rects) {
            assert(r.row >= 0 && r.row < dlc, `${label}: row out of bounds: ${r.row}`)
            assert(r.colStart >= 0 && r.colStart < 8, `${label}: colStart out of bounds: ${r.colStart}`)
            assert(r.colEnd >= 0 && r.colEnd < 8, `${label}: colEnd out of bounds: ${r.colEnd}`)
          }

          // 2. rects do not overlap (pairwise disjoint grid cells)
          const occupied = new Set()
          for (const r of data.rects) {
            for (let c = r.colStart; c <= r.colEnd; c++) {
              const key = `${r.row},${c}`
              assert(!occupied.has(key), `${label}: overlapping cell at (${r.row},${c})`)
              occupied.add(key)
            }
          }

          // 3. total covered bits == signal.length
          assert.strictEqual(occupied.size, length, `${label}: covered bits ${occupied.size} != length ${length}`)

          // 4. group anchor is bounding-box top-left
          let minRow = Infinity, minCol = Infinity
          for (const r of data.rects) {
            if (r.row < minRow) minRow = r.row
            if (r.colStart < minCol) minCol = r.colStart
          }
          const expectedGroupX = defaultOptions.labelWidth + minCol * defaultOptions.cellSize
          const expectedGroupY = defaultOptions.headerH + minRow * defaultOptions.cellSize
          assert.strictEqual(data.groupX, expectedGroupX, `${label}: groupX mismatch`)
          assert.strictEqual(data.groupY, expectedGroupY, `${label}: groupY mismatch`)

          // 5. every rect relative x,y >= 0
          for (const r of data.rects) {
            assert(r.x >= 0, `${label}: rect x < 0: ${r.x}`)
            assert(r.y >= 0, `${label}: rect y < 0: ${r.y}`)
          }
        })
      }
    }
  }
})

// ── Motorola (big_endian) signalToRenderData tests ──
const motorolaLengths = [1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64]
const motorolaStartBits = [0, 1, 2, 3, 4, 5, 6, 7, 8, 15, 16, 17, 23, 24, 31, 32, 55, 56, 63]
const motorolaDlcs = [1, 2, 4, 8]
const motorolaOptions = { cellSize: 36, headerH: 32, labelWidth: 44, color: '#ff0000', hasError: false }

function makeMotorolaSignal(startBit, length) {
  return {
    uuid: `test-${startBit}-${length}`,
    name: `TestSignal_${startBit}_${length}`,
    start_bit: startBit,
    length,
    byte_order: 'big_endian',
  }
}

describe('signalToRenderData Motorola (big_endian)', () => {
  for (const dlc of motorolaDlcs) {
    for (const length of motorolaLengths) {
      for (const startBit of motorolaStartBits) {
        const label = `dlc=${dlc} length=${length} startBit=${startBit}`
        it(label, () => {
          const signal = makeMotorolaSignal(startBit, length)
          const renderData = signalToRenderData(signal, dlc, motorolaOptions)

          const maxBit = dlc * 8 - 1
          const bits = getSignalBits(startBit, length, 'big_endian')
          const validBits = [...bits].filter((b) => b >= 0 && b <= maxBit)

          if (validBits.length === 0) {
            assert.strictEqual(renderData, null, `${label}: expected null when no visible bits`)
            return
          }

          assert.ok(renderData, `${label}: expected non-null renderData`)

          // 1. All rects inside grid
          for (const rect of renderData.rects) {
            assert.ok(rect.row >= 0 && rect.row < dlc,
              `${label}: rect row ${rect.row} out of [0, ${dlc})`)
            assert.ok(rect.colStart >= 0 && rect.colStart < 8,
              `${label}: rect colStart ${rect.colStart} out of [0, 8)`)
            assert.ok(rect.colEnd >= 0 && rect.colEnd < 8,
              `${label}: rect colEnd ${rect.colEnd} out of [0, 8)`)
            assert.ok(rect.colStart <= rect.colEnd,
              `${label}: rect colStart ${rect.colStart} > colEnd ${rect.colEnd}`)
          }

          // 2. Rects do not overlap
          const occupied = new Set()
          for (const rect of renderData.rects) {
            for (let c = rect.colStart; c <= rect.colEnd; c++) {
              const key = `${rect.row},${c}`
              assert.ok(!occupied.has(key),
                `${label}: overlapping cell at row=${rect.row} col=${c}`)
              occupied.add(key)
            }
          }

          // 3. Total covered bits equal visible signal bits
          assert.strictEqual(occupied.size, validBits.length,
            `${label}: covered ${occupied.size} bits but expected ${validBits.length}`)

          // 4. Group anchor corresponds to bounding box top-left
          let minRow = Infinity
          let minCol = Infinity
          for (const rect of renderData.rects) {
            if (rect.row < minRow) minRow = rect.row
            if (rect.colStart < minCol) minCol = rect.colStart
          }
          const expectedGroupX = motorolaOptions.labelWidth + minCol * motorolaOptions.cellSize
          const expectedGroupY = motorolaOptions.headerH + minRow * motorolaOptions.cellSize
          assert.strictEqual(renderData.groupX, expectedGroupX,
            `${label}: groupX mismatch`)
          assert.strictEqual(renderData.groupY, expectedGroupY,
            `${label}: groupY mismatch`)

          // 5. Each rect relative coordinate (x, y) is non-negative
          for (const rect of renderData.rects) {
            assert.ok(rect.x >= 0, `${label}: rect.x ${rect.x} < 0`)
            assert.ok(rect.y >= 0, `${label}: rect.y ${rect.y} < 0`)
          }
        })
      }
    }
  }
})

describe('signalToRenderData clampStartBit filtering (Motorola)', () => {
  for (const dlc of motorolaDlcs) {
    const maxBit = dlc * 8 - 1
    for (const length of motorolaLengths) {
      for (const startBit of motorolaStartBits) {
        const label = `dlc=${dlc} length=${length} startBit=${startBit}`
        it(label, () => {
          const clamped = clampStartBit(startBit, length, 'big_endian', maxBit)
          const signal = makeMotorolaSignal(startBit, length)
          const renderData = signalToRenderData(signal, dlc, motorolaOptions)

          if (clamped !== startBit) {
            // Illegal start_bit should yield null (no visible rects)
            assert.strictEqual(renderData, null,
              `${label}: illegal start_bit not filtered (clamped=${clamped})`)
          } else {
            // Legal start_bit should yield non-null when at least one bit visible
            const bits = getSignalBits(startBit, length, 'big_endian')
            const validBits = [...bits].filter((b) => b >= 0 && b <= maxBit)
            if (validBits.length === 0) {
              assert.strictEqual(renderData, null,
                `${label}: expected null when no visible bits`)
            } else {
              assert.ok(renderData, `${label}: expected non-null renderData for legal start_bit`)
            }
          }
        })
      }
    }
  }
})
