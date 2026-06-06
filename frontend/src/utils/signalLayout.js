/**
 * CAN signal bit-layout math utilities.
 *
 * Port of the Python `_get_signal_bits()` algorithm from api_server.py,
 * plus grid-coordinate helpers for the Konva-based layout visualizer.
 */

/**
 * Compute the set of absolute bit positions occupied by a signal.
 *
 * Intel (little_endian): bits are a contiguous block [start_bit, start_bit+length-1].
 * Motorola (big_endian): start_bit is the MSB; traversal zigzags within bytes:
 *   decrement within byte, when reaching bit 0 jump to bit 7 of the next byte (+15).
 *
 * This is an exact JS port of api_server.py:_get_signal_bits().
 *
 * @param {number} startBit
 * @param {number} length
 * @param {string} byteOrder - "little_endian" | "big_endian"
 * @returns {Set<number>}
 */
export function getSignalBits(startBit, length, byteOrder) {
  const bits = new Set()
  if (byteOrder === 'big_endian' || byteOrder === 'motorola') {
    let current = startBit
    for (let i = 0; i < length; i++) {
      bits.add(current)
      if (current % 8 === 0) {
        current += 15
      } else {
        current -= 1
      }
    }
  } else {
    for (let i = 0; i < length; i++) {
      bits.add(startBit + i)
    }
  }
  return bits
}

/**
 * Convert an absolute bit number to grid cell coordinates.
 * Column 0 = bit 7, column 7 = bit 0.
 * @param {number} bit
 * @returns {{row: number, col: number}}
 */
export function bitToGridCell(bit) {
  return {
    row: Math.floor(bit / 8),
    col: 7 - (bit % 8),
  }
}

/**
 * Inverse of bitToGridCell.
 * @param {number} row
 * @param {number} col
 * @returns {number}
 */
export function gridCellToBit(row, col) {
  return row * 8 + (7 - col)
}

/**
 * Group a signal's occupied bits by byte row and find contiguous column runs.
 * Returns one rectangle descriptor per contiguous segment per row.
 *
 * @param {{start_bit: number, length: number, byte_order: string}} signal
 * @param {number} dlc - message DLC (bytes)
 * @returns {{row: number, colStart: number, colEnd: number}[]} sorted top-to-bottom, left-to-right
 */
export function signalToRowRects(signal, dlc) {
  const bits = getSignalBits(signal.start_bit, signal.length, signal.byte_order)
  const colsByRow = {} // row -> Set<col>

  for (const bit of bits) {
    const { row, col } = bitToGridCell(bit)
    if (row < 0 || row >= dlc) continue
    if (!colsByRow[row]) colsByRow[row] = new Set()
    colsByRow[row].add(col)
  }

  const rects = []
  const sortedRows = Object.keys(colsByRow).map(Number).sort((a, b) => a - b)

  for (const row of sortedRows) {
    const cols = [...colsByRow[row]].sort((a, b) => a - b)
    // group contiguous columns
    let segStart = cols[0]
    let segEnd = cols[0]
    for (let i = 1; i < cols.length; i++) {
      if (cols[i] === segEnd + 1) {
        segEnd = cols[i]
      } else {
        rects.push({ row, colStart: segStart, colEnd: segEnd })
        segStart = cols[i]
        segEnd = cols[i]
      }
    }
    rects.push({ row, colStart: segStart, colEnd: segEnd })
  }

  return rects
}

/**
 * Get the visible bit extents of a signal in pixel coordinates.
 * Returns the top-left grid cell and total column span.
 *
 * @param {{start_bit: number, length: number, byte_order: string}} signal
 * @param {number} dlc
 * @returns {{minRow: number, minCol: number, colSpan: number}}
 */
export function signalExtents(signal, dlc) {
  const rects = signalToRowRects(signal, dlc)
  if (rects.length === 0) return { minRow: 0, minCol: 0, colSpan: 0 }
  let minRow = Infinity, minCol = Infinity, maxCol = -1
  for (const r of rects) {
    if (r.row < minRow) minRow = r.row
    if (r.colStart < minCol) minCol = r.colStart
    if (r.colEnd > maxCol) maxCol = r.colEnd
  }
  return { minRow, minCol, colSpan: maxCol - minCol + 1 }
}

/**
 * Compute the valid start_bit range extremes for a signal so that all occupied bits
 * lie within [0, maxBit].  O(1) for both Intel and Motorola.
 *
 * NOTE: For Motorola the valid start_bits are NOT always contiguous;
 * use clampStartBit() to snap a candidate to the nearest valid value.
 *
 * @param {number} length
 * @param {string} byteOrder - "little_endian" | "big_endian"
 * @param {number} maxBit
 * @returns {{minStart: number, maxStart: number}}  (-1, -1) when impossible
 */
export function validStartBitRangeOptimized(length, byteOrder, maxBit) {
  if (length > maxBit + 1) {
    return { minStart: -1, maxStart: -1 }
  }

  if (byteOrder === 'little_endian') {
    return { minStart: 0, maxStart: maxBit - length + 1 }
  }

  const dlc = Math.floor((maxBit + 1) / 8)

  function computeMaxK(r) {
    if (length <= r + 1) {
      return dlc - 1
    }
    const remaining = length - r - 1
    const totalJumps = 1 + Math.floor((remaining - 1) / 8)
    return dlc - 1 - totalJumps
  }

  // Motorola: start_bit must be a byte MSB (bit 7, 15, 23, ...), so r must be 7.
  const r = 7
  const maxK = computeMaxK(r)
  if (maxK < 0) {
    return { minStart: -1, maxStart: -1 }
  }

  const minStart = r
  const maxStart = maxK * 8 + r

  return { minStart, maxStart }
}

/**
 * Find the nearest valid start_bit to a candidate value.
 * Handles Motorola gaps correctly.
 *
 * @param {number} candidate
 * @param {number} length
 * @param {string} byteOrder
 * @param {number} maxBit
 * @returns {number} nearest valid start_bit, or -1 if none exists
 */
export function clampStartBit(candidate, length, byteOrder, maxBit) {
  if (length > maxBit + 1) return -1

  if (byteOrder === 'little_endian') {
    return Math.max(0, Math.min(maxBit - length + 1, candidate))
  }

  const dlc = Math.floor((maxBit + 1) / 8)

  function maxKForR(r) {
    if (length <= r + 1) return dlc - 1
    const remaining = length - r - 1
    const totalJumps = 1 + Math.floor((remaining - 1) / 8)
    return dlc - 1 - totalJumps
  }

  // Motorola: start_bit must be a byte MSB (bit 7, 15, 23, ...), so r must be 7.
  const validRs = [7]

  let bestS = -1
  let bestDist = Infinity

  for (const r of validRs) {
    const maxK = maxKForR(r)
    if (maxK < 0) continue

    let k = Math.round((candidate - r) / 8)
    k = Math.max(0, Math.min(maxK, k))
    const s = k * 8 + r
    const dist = Math.abs(s - candidate)

    if (dist < bestDist || (dist === bestDist && s < bestS)) {
      bestDist = dist
      bestS = s
    }

    for (const dk of [-1, 1]) {
      const k2 = k + dk
      if (k2 < 0 || k2 > maxK) continue
      const s2 = k2 * 8 + r
      const dist2 = Math.abs(s2 - candidate)
      if (dist2 < bestDist || (dist2 === bestDist && s2 < bestS)) {
        bestDist = dist2
        bestS = s2
      }
    }
  }

  return bestS
}

/**
 * Color palette for signal blocks — OKLCH hues with moderate saturation/lightness.
 * @param {number} index
 * @returns {string} OKLCH color string
 */
export function getSignalColor(index) {
  const palette = [
    'oklch(0.72 0.13 155)',   // green
    'oklch(0.72 0.14 40)',    // orange
    'oklch(0.72 0.12 260)',   // blue
    'oklch(0.72 0.12 340)',   // pink
    'oklch(0.72 0.13 80)',    // yellow
    'oklch(0.72 0.11 200)',   // teal
    'oklch(0.72 0.12 300)',   // purple
    'oklch(0.72 0.14 10)',    // red
    'oklch(0.72 0.13 120)',   // lime
    'oklch(0.72 0.11 220)',   // cyan
  ]
  return palette[index % palette.length]
}

/**
 * Convert pixel coordinates to grid cell coordinates.
 *
 * @param {number} x - pixel x (relative to canvas origin)
 * @param {number} y - pixel y (relative to canvas origin)
 * @param {{labelWidth: number, headerH: number, cellSize: number}} options
 * @returns {{row: number, col: number}}
 */
export function pixelToGridCell(x, y, { labelWidth, headerH, cellSize }) {
  const col = Math.floor((x - labelWidth) / cellSize)
  const row = Math.floor((y - headerH) / cellSize)
  return { row, col }
}

/**
 * Convert grid cell coordinates to pixel coordinates (top-left of the cell).
 *
 * @param {number} row
 * @param {number} col
 * @param {{labelWidth: number, headerH: number, cellSize: number}} options
 * @returns {{x: number, y: number}}
 */
export function gridCellToPixel(row, col, { labelWidth, headerH, cellSize }) {
  const x = labelWidth + col * cellSize
  const y = headerH + row * cellSize
  return { x, y }
}

/**
 * Build render data for a signal, ready to be drawn by a Konva (or any) renderer.
 *
 * Uses `signalToRowRects` to determine the occupied grid cells, then maps them
 * to pixel coordinates relative to a Group anchor.
 *
 * @param {SignalInput} signal
 * @param {number} dlc - message DLC (bytes)
 * @param {RenderOptions} options
 * @returns {SignalRenderData|null} null when the signal has no visible rects
 */
export function signalToRenderData(signal, dlc, options) {
  const {
    cellSize = 36,
    headerH = 32,
    labelWidth = 44,
    color,
    hasError = false,
    labelText,
  } = options

  const rects = signalToRowRects(signal, dlc)
  if (rects.length === 0) {
    return null
  }

  let minRow = Infinity
  let minCol = Infinity
  let maxCol = -1

  for (const r of rects) {
    if (r.row < minRow) minRow = r.row
    if (r.colStart < minCol) minCol = r.colStart
    if (r.colEnd > maxCol) maxCol = r.colEnd
  }

  const groupX = labelWidth + minCol * cellSize
  const groupY = headerH + minRow * cellSize

  const pixelRects = rects.map((r) => ({
    x: (r.colStart - minCol) * cellSize,
    y: (r.row - minRow) * cellSize,
    width: (r.colEnd - r.colStart + 1) * cellSize,
    height: cellSize,
    row: r.row,
    colStart: r.colStart,
    colEnd: r.colEnd,
  }))

  const colSpan = maxCol - minCol + 1
  const label = {
    x: -labelWidth,
    y: 0,
    width: labelWidth,
    text: labelText !== undefined ? labelText : signal.name,
  }

  return {
    uuid: signal.uuid,
    groupX,
    groupY,
    rects: pixelRects,
    label,
    color,
    hasError,
    _meta: {
      startBit: signal.start_bit,
      length: signal.length,
      byteOrder: signal.byte_order,
      minRow,
      minCol,
      startCell: { row: minRow, col: minCol },
    },
  }
}
