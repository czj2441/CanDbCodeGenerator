import { test, afterEach } from 'node:test'
import assert from 'node:assert'
import {
  beginPendingEdit, peekPendingEdit, takePendingEditTarget, clearPendingEdit,
  cancelPendingEdit, remapPendingEditTarget, flushPendingEdit,
  cancelAllPendingEdits, usePanelEdit,
} from '../pendingEdit.js'

const originalDocument = globalThis.document
afterEach(() => {
  cancelAllPendingEdits()
  if (originalDocument === undefined) delete globalThis.document
  else globalThis.document = originalDocument
})
const setActiveElement = (el) => { globalThis.document = { activeElement: el } }

test('begin / peek / take 返回并清除快照', () => {
  beginPendingEdit('a', { name: 'A' })
  assert.deepEqual(peekPendingEdit('a'), { name: 'A' })
  assert.deepEqual(takePendingEditTarget('a'), { name: 'A' })
  assert.equal(peekPendingEdit('a'), null)
})

test('clear 不调用 cancel；cancel 调用回调并清除', () => {
  let cancelled = 0
  beginPendingEdit('b', { name: 'B' }, { cancel: () => { cancelled += 1 } })
  clearPendingEdit('b')
  assert.equal(cancelled, 0)

  let received = null
  beginPendingEdit('c', { name: 'C' }, { cancel: (t) => { received = t.name } })
  cancelPendingEdit('c')
  assert.equal(received, 'C')
  assert.equal(peekPendingEdit('c'), null)
})

test('cancel 的 predicate 返回 false 时保留快照', () => {
  beginPendingEdit('d', { name: 'D' })
  cancelPendingEdit('d', () => false)
  assert.deepEqual(peekPendingEdit('d'), { name: 'D' })
})

test('remap 修改已有快照的目标', () => {
  beginPendingEdit('e', { msgKey: 1, signalName: 'A' })
  remapPendingEditTarget('e', (t) => ({ ...t, signalName: 'B' }))
  assert.deepEqual(peekPendingEdit('e'), { msgKey: 1, signalName: 'B' })
})

test('flush 在注册表为空时不会 blur（保护方向键焦点）', () => {
  let blurred = 0
  setActiveElement({ tagName: 'INPUT', blur: () => { blurred += 1 } })
  flushPendingEdit()
  assert.equal(blurred, 0)
})

test('flush 先 blur 再取消；blur 中能取到旧目标', () => {
  const committed = []
  const state = { selected: 'A' }
  const el = {
    tagName: 'INPUT',
    blur() {
      const t = takePendingEditTarget('f')
      if (t) committed.push(t.signalName)
    },
  }
  setActiveElement(el)
  beginPendingEdit('f', { signalName: state.selected }, { element: el })
  flushPendingEdit()
  state.selected = 'B'
  assert.deepEqual(committed, ['A'])
  assert.equal(peekPendingEdit('f'), null)
})

test('flush 会取消 blur 后仍未消费的快照', () => {
  let cancelled = 0
  const el = { tagName: 'INPUT', blur: () => {} }
  setActiveElement(el)
  beginPendingEdit('g', { name: 'G' }, { cancel: () => { cancelled += 1 }, element: el })
  flushPendingEdit()
  assert.equal(cancelled, 1)
  assert.equal(peekPendingEdit('g'), null)
})

test('flush 不 blur 与快照无关的当前焦点，只清除过期快照', () => {
  let blurred = 0
  const tableInput = { tagName: 'INPUT', blur: () => { blurred += 1 } }
  const staleSelect = { tagName: 'SELECT', blur: () => { blurred += 1 } }
  setActiveElement(tableInput)
  beginPendingEdit('stale', { name: 'X' }, { element: staleSelect })
  flushPendingEdit()
  assert.equal(blurred, 0)
  assert.equal(peekPendingEdit('stale'), null)
})

test('usePanelEdit.commit 使用快照；无快照时回退当前目标', () => {
  const edit = usePanelEdit('h', () => ({ signalName: 'current' }))
  beginPendingEdit('h', { signalName: 'snapshot' })
  let received = null
  edit.commit((t) => { received = t.signalName })
  assert.equal(received, 'snapshot')

  const fallback = usePanelEdit('i', () => ({ signalName: 'fallback' }))
  fallback.commit((t) => { received = t.signalName })
  assert.equal(received, 'fallback')
})

test('blur 取走快照后，下一次 begin 会建立新快照', () => {
  const edit = usePanelEdit('j', () => ({ signalName: 'B' }))
  beginPendingEdit('j', { signalName: 'A' })
  assert.deepEqual(edit.take(), { signalName: 'A' })
  edit.begin()
  let received = null
  edit.commit((t) => { received = t.signalName })
  assert.equal(received, 'B')
})