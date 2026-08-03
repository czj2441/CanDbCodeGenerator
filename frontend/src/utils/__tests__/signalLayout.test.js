/**
 * Unit tests for signalLayout.js
 * Run with: node --test src/utils/__tests__/signalLayout.test.js
 */
import { describe, it } from 'node:test'
import assert from 'node:assert'
import { getSignalBits, validStartBitRangeOptimized, clampStartBit } from '../signalLayout.js'

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
