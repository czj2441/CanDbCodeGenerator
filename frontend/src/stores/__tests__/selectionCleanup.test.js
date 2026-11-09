import { test, beforeEach } from 'node:test'
import assert from 'node:assert'
import { createPinia, setActivePinia } from 'pinia'

// 在导入 store 之前准备浏览器全局变量的最小替身。
const storage = new Map()
globalThis.localStorage = {
  getItem: (k) => (storage.has(k) ? storage.get(k) : null),
  setItem: (k, v) => storage.set(k, String(v)),
  removeItem: (k) => storage.delete(k),
}
globalThis.location = { search: '', protocol: 'http:', host: 'localhost' }
globalThis.window = globalThis
globalThis.document = { activeElement: null }
globalThis.requestAnimationFrame = () => 0
globalThis.cancelAnimationFrame = () => {}

const { useCoreStore } = await import('../coreStore.js')
const { useUiStore } = await import('../uiStore.js')
const {
  beginPendingEdit, peekPendingEdit, clearPendingEdit, PENDING_EDIT_OWNERS,
} = await import('../../composables/pendingEdit.js')

beforeEach(() => {
  setActivePinia(createPinia())
  clearPendingEdit(PENDING_EDIT_OWNERS.signalPanel)
  clearPendingEdit(PENDING_EDIT_OWNERS.messagePanel)
  clearPendingEdit(PENDING_EDIT_OWNERS.valueTablePanel)
})

test('删除其他报文中的同名信号不影响当前选中和待提交编辑', () => {
  const editor = useCoreStore()
  const ui = useUiStore()
  editor.selectedMsgKey = 100
  ui.selectedSignalName = 'Speed'
  beginPendingEdit(PENDING_EDIT_OWNERS.signalPanel, { msgKey: 100, signalName: 'Speed' })

  editor._applyWsMessage({
    type: 'signal_deleted',
    data: { msg_key: 200, signal_name: 'Speed' },
    data_version: 1,
  })

  assert.equal(ui.selectedSignalName, 'Speed')
  assert.deepEqual(peekPendingEdit(PENDING_EDIT_OWNERS.signalPanel), {
    msgKey: 100,
    signalName: 'Speed',
  })
})

test('删除当前报文的选中信号会清空选中并取消待提交编辑', () => {
  const editor = useCoreStore()
  const ui = useUiStore()
  editor.selectedMsgKey = 100
  ui.selectedSignalName = 'Speed'
  beginPendingEdit(PENDING_EDIT_OWNERS.signalPanel, { msgKey: 100, signalName: 'Speed' })

  editor._applyWsMessage({
    type: 'signal_deleted',
    data: { msg_key: 100, signal_name: 'Speed' },
    data_version: 1,
  })

  assert.equal(ui.selectedSignalName, null)
  assert.equal(peekPendingEdit(PENDING_EDIT_OWNERS.signalPanel), null)
})
test('字符串 msgKey 也能识别动态报文 tab', () => {
  const ui = useUiStore()
  ui.openTabs = [{ msgKey: '0x100:std' }]
  ui.activeTabId = '0x100:std'

  assert.equal(ui.isAnyMessageTabActive, true)
  assert.equal(ui.activeMessageTab.msgKey, '0x100:std')

  ui.activeTabId = 'messages'
  assert.equal(ui.isAnyMessageTabActive, false)
  assert.equal(ui.activeMessageTab, null)
})
