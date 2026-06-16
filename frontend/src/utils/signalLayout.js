/**
 * CAN signal bit-layout math utilities.
 *
 * Port of the Python `_get_signal_bits()` algorithm from api_server.py,
 * plus grid-coordinate helpers for the Konva-based layout visualizer.
 */

/**
 * Motorola 锯齿遍历：
 *   字节内 bit 递减，到 bit0 时跳下一字节 bit7
 *
 *   Byte 0      Byte 1      Byte 2
 *   7 6 5 4 3 2 1 0  15..8  23..16
 *   ←────────── ←────────── ←──────────
 *   MSB────→LSB  MSB────→LSB  MSB────→LSB
 *
 *   例: 7→6→...→0→15→14→...→8→23→...
 */
export function motorolaNextBit(bit) {
  return bit % 8 === 0 ? bit + 15 : bit - 1
}

/**
 * 从 MSB 出发走 pos 步，到达的 bit 编号
 *   pos=0 → MSB 自身
 *   pos=length-1 → LSB（与 toDisplayStartBit 一致）
 */
export function motorolaBitAtPosition(msb, pos) {
  let cur = msb
  for (let i = 0; i < pos; i++) cur = motorolaNextBit(cur)
  return cur
}

/**
 * 逆查: 哪个 MSB 使得遍历到 pos 时 = targetBit
 *   例: pos=7, targetBit=10, len=8
 *       候选 MSB=1: 1→0→15→14→13→12→11→10  ✅ pos7=10
 *   → 返回 1（最接近 hintMsb 的那个）
 */
export function motorolaFindMsbByPosition(pos, length, targetBit, maxBit = 63, hintMsb = -1) {
  if (pos < 0 || pos >= length) return -1
  let bestMsb = -1
  let bestDist = Infinity
  for (let msb = 0; msb <= maxBit; msb++) {
    if (motorolaBitAtPosition(msb, pos) === targetBit) {
      const d = hintMsb >= 0 ? Math.abs(msb - hintMsb) : 0
      if (d < bestDist) { bestDist = d; bestMsb = msb }
    }
  }
  return bestMsb
}

/**
 * 信号占用的 bit 集合
 *   Intel:  [startBit, startBit+length-1] 连续递增
 *   Motorola: MSB→LSB 锯齿遍历 (motorolaNextBit × length−1)
 */
export function getSignalBits(startBit, length, byteOrder) {
  const bits = new Set()
  if (byteOrder === 'motorola') {
    let cur = startBit
    for (let i = 0; i < length; i++) {
      bits.add(cur)
      cur = motorolaNextBit(cur)
    }
  } else {
    for (let i = 0; i < length; i++) bits.add(startBit + i)
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
 * 存储 MSB → 显示 LSB
 *   Intel:  不变（startBit 即 LSB）
 *   Motorola: 走 length−1 步到 LSB
 *     例: MSB=7 len=8 → 走7步 → 0  (填满 Byte0)
 *         MSB=23 len=16 → 走15步 → 24 (填满 Byte2+3)
 */
export function toDisplayStartBit(storageStartBit, length, byteOrder) {
  if (!length || length <= 0) return storageStartBit
  if (byteOrder === 'intel') return storageStartBit
  return motorolaBitAtPosition(storageStartBit, length - 1)
}

/**
 * 用户输入 LSB → 存储 MSB
 *   用 motorolaFindMsbByPosition 反查: 哪个 MSB 的 LSB = 输入值
 *   无匹配返回 −1，由调用方报错
 */
export function toStorageStartBit(displayStartBit, length, byteOrder, maxBit = 63, hintMsb = -1) {
  if (!length || length <= 0) return displayStartBit
  if (byteOrder === 'intel') return displayStartBit

  const msb = motorolaFindMsbByPosition(length - 1, length, displayStartBit, maxBit, hintMsb)
  if (msb < 0) return -1
  // 双向验证：确保 MSB 产生的 LSB 确实是输入值，且所有 bit 在范围内
  if (toDisplayStartBit(msb, length, 'motorola') !== displayStartBit) return -1
  const bits = getSignalBits(msb, length, 'motorola')
  for (const b of bits) { if (b < 0 || b > maxBit) return -1 }
  return msb
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
 * lie within [0, maxBit].
 *
 * @param {number} length
 * @param {string} byteOrder - "intel" | "motorola"
 * @param {number} dlc - 报文数据长度（字节数）
 * @returns {{minStart: number, maxStart: number}}  (-1, -1) when impossible
 */
export function validStartBitRangeOptimized(length, byteOrder, dlc) {
  const maxBit = 8 * dlc - 1
  if (length > maxBit + 1) {
    return { minStart: -1, maxStart: -1 }
  }

  if (byteOrder === 'intel') {
    return { minStart: 0, maxStart: maxBit - length + 1 }
  }

  // Motorola: 使用暴力搜索寻找合法范围（新算法允许任意 start_bit）
  let minStart = -1
  let maxStart = -1

  for (let s = 0; s <= maxBit; s++) {
    const bits = getSignalBits(s, length, 'motorola')
    const allValid = Array.from(bits).every(b => b >= 0 && b <= maxBit)
    if (allValid) {
      if (minStart === -1) minStart = s
      maxStart = s
    }
  }

  return { minStart, maxStart }
}

/**
 * Find the nearest valid start_bit to a candidate value.
 * Uses the new Motorola algorithm that allows any start_bit position.
 *
 * @param {number} candidate
 * @param {number} length
 * @param {string} byteOrder
 * @param {number} dlc - 报文数据长度（字节数）
 * @returns {number} nearest valid start_bit, or -1 if none exists
 */
export function clampStartBit(candidate, length, byteOrder, dlc) {
  const maxBit = 8 * dlc - 1
  if (length > maxBit + 1) return -1

  if (byteOrder === 'intel') {
    return Math.max(0, Math.min(maxBit - length + 1, candidate))
  }

  // Motorola: 使用新算法，允许任意 start_bit
  // 策略：从 candidate 开始，向两侧寻找最近的合法位置

  // 先检查 candidate 本身是否合法
  const candidateBits = getSignalBits(candidate, length, 'motorola')
  const candidateValid = Array.from(candidateBits).every(b => b >= 0 && b <= maxBit)
  if (candidateValid) return candidate

  // 向下寻找
  let bestS = -1
  let bestDist = Infinity

  for (let s = candidate - 1; s >= 0; s--) {
    const bits = getSignalBits(s, length, 'motorola')
    const allValid = Array.from(bits).every(b => b >= 0 && b <= maxBit)
    if (allValid) {
      const dist = candidate - s
      if (dist < bestDist) {
        bestDist = dist
        bestS = s
      }
      break  // 找到第一个合法位置即可
    }
  }

  // 向上寻找
  for (let s = candidate + 1; s <= maxBit; s++) {
    const bits = getSignalBits(s, length, 'motorola')
    const allValid = Array.from(bits).every(b => b >= 0 && b <= maxBit)
    if (allValid) {
      const dist = s - candidate
      if (dist < bestDist || (dist === bestDist && s < bestS)) {
        bestDist = dist
        bestS = s
      }
      break  // 找到第一个合法位置即可
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
