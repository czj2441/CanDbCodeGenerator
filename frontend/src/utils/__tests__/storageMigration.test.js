/**
 * storageMigration 单元测试
 *
 * Run with: node --test src/utils/__tests__/storageMigration.test.js
 */
import { describe, it } from 'node:test'
import assert from 'node:assert'
import { migrateLegacyStorage, migrateStorage } from '../storageMigration.js'

function fakeStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  return {
    get length() { return map.size },
    key(i) { return Array.from(map.keys())[i] ?? null },
    getItem(k) { return map.has(k) ? map.get(k) : null },
    setItem(k, v) { map.set(k, String(v)) },
    removeItem(k) { map.delete(k) },
  }
}

describe('migrateStorage', () => {
  it('复制旧键到新键并删除旧键，不碰其他键', () => {
    const storage = fakeStorage({
      canmatrix_theme: 'light',
      canmatrix_bottom_tab: 'log',
      unrelated: 'keep',
    })

    assert.strictEqual(migrateStorage(storage), 2)
    assert.strictEqual(storage.getItem('candb_theme'), 'light')
    assert.strictEqual(storage.getItem('candb_bottom_tab'), 'log')
    assert.strictEqual(storage.getItem('canmatrix_theme'), null)
    assert.strictEqual(storage.getItem('canmatrix_bottom_tab'), null)
    assert.strictEqual(storage.getItem('unrelated'), 'keep')
  })

  it('新键已存在时保留新值，并仍清理旧键', () => {
    const storage = fakeStorage({
      canmatrix_theme: 'light',
      candb_theme: 'dark',
    })

    assert.strictEqual(migrateStorage(storage), 0)
    assert.strictEqual(storage.getItem('candb_theme'), 'dark')
    assert.strictEqual(storage.getItem('canmatrix_theme'), null)
  })

  it('保留空字符串值（不能被 falsy 判断丢弃）', () => {
    const storage = fakeStorage({ canmatrix_bottom_tab: '' })

    assert.strictEqual(migrateStorage(storage), 1)
    assert.strictEqual(storage.getItem('candb_bottom_tab'), '')
  })

  it('重复执行保持幂等', () => {
    const storage = fakeStorage({ canmatrix_session_id: 'sid-1' })

    assert.strictEqual(migrateStorage(storage), 1)
    assert.strictEqual(migrateStorage(storage), 0)
    assert.strictEqual(storage.getItem('candb_session_id'), 'sid-1')
    assert.strictEqual(storage.getItem('canmatrix_session_id'), null)
  })

  it('storage 为空时返回 0', () => {
    assert.strictEqual(migrateStorage(null), 0)
    assert.strictEqual(migrateStorage(undefined), 0)
  })

  it('migrateLegacyStorage 同时迁移 localStorage 与 sessionStorage', () => {
    const localStorage = fakeStorage({ canmatrix_auth_token: 'token-1' })
    const sessionStorage = fakeStorage({ canmatrix_session_id: 'sid-1' })
    const previousWindow = globalThis.window

    globalThis.window = { localStorage, sessionStorage }
    try {
      assert.strictEqual(migrateLegacyStorage(), 2)
      assert.strictEqual(localStorage.getItem('candb_auth_token'), 'token-1')
      assert.strictEqual(sessionStorage.getItem('candb_session_id'), 'sid-1')
      assert.strictEqual(localStorage.getItem('canmatrix_auth_token'), null)
      assert.strictEqual(sessionStorage.getItem('canmatrix_session_id'), null)
    } finally {
      if (previousWindow === undefined) delete globalThis.window
      else globalThis.window = previousWindow
    }
  })
})
