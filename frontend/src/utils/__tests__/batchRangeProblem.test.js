import { describe, it } from 'node:test'
import assert from 'node:assert'
import { analyzeBatchRangeProblem } from '../signalLayout.js'

const UINT8 = { min: 0, max: 255 }

describe('analyzeBatchRangeProblem', () => {
  it('范围未知 / 0/0 未设置 / 合法值 不报错', () => {
    assert.strictEqual(analyzeBatchRangeProblem({
      range: null, minVal: 0, maxVal: 0, valueType: 'uint',
    }), null)
    assert.strictEqual(analyzeBatchRangeProblem({
      range: { min: 10, max: 20 }, minVal: 0, maxVal: 0, valueType: 'uint',
    }), null)
    assert.strictEqual(analyzeBatchRangeProblem({
      range: UINT8, minVal: 0, maxVal: 255, valueType: 'uint',
    }), null)
  })

  it('最小值大于最大值', () => {
    assert.deepStrictEqual(analyzeBatchRangeProblem({
      range: UINT8, minVal: 10, maxVal: 5, valueType: 'uint',
    }), { kind: 'min_max', minVal: 10, maxVal: 5 })
  })

  it('最小值低于可表示范围', () => {
    assert.deepStrictEqual(analyzeBatchRangeProblem({
      range: UINT8, minVal: -1, maxVal: 255, valueType: 'uint',
    }), { kind: 'min_out', value: -1, min: 0, max: 255 })
  })

  it('最大值高于可表示范围', () => {
    assert.deepStrictEqual(analyzeBatchRangeProblem({
      range: UINT8, minVal: 0, maxVal: 256, valueType: 'uint',
    }), { kind: 'max_out', value: 256, min: 0, max: 255 })
  })

  it('float 接受 DBC 常见的 FLT_MAX 十进制舍入值', () => {
    const fmax = 3.4028234663852886e38
    assert.strictEqual(analyzeBatchRangeProblem({
      range: { min: -fmax, max: fmax },
      minVal: 0,
      maxVal: 3.4028235e38,
      valueType: 'float',
    }), null)
    assert.strictEqual(analyzeBatchRangeProblem({
      range: { min: -fmax, max: fmax },
      minVal: 0,
      maxVal: 3.5e38,
      valueType: 'float',
    }).kind, 'max_out')
  })
})