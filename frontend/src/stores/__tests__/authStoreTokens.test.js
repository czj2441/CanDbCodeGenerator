/**
 * authStore 个人MCP访问令牌 (PAT) actions 单元测试
 *
 * 逐一断言三个 action 对 /api/tokens 端点的 method / headers / body 与返回值：
 *   - listTokens:  GET  /api/tokens        → 解析后的 data 数组
 *   - createToken: POST /api/tokens        → 解析后的 data（含一次性明文 token）
 *   - revokeToken: DELETE /api/tokens/{id} → Promise<void>
 *
 * Run with: node --test src/stores/__tests__/authStoreTokens.test.js
 */
import { describe, it, beforeEach } from 'node:test'
import assert from 'node:assert'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../authStore.js'

const SESSION_TOKEN = 'session-token-abc'

function stubLocalStorage() {
  const store = new Map([['canmatrix_auth_token', SESSION_TOKEN]])
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
    clear: () => store.clear(),
  }
}

/** 伪造 fetch：记录每次调用并返回预设 JSON 响应 */
function stubFetch(jsonBody) {
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options })
    return {
      ok: true,
      status: 200,
      json: async () => (typeof jsonBody === 'function' ? jsonBody() : jsonBody),
    }
  }
  return calls
}

/** 统一断言：三个 action 都必须带 Bearer + JSON 头 */
function assertAuthHeaders(options) {
  assert.strictEqual(options.headers['Authorization'], `Bearer ${SESSION_TOKEN}`)
  assert.strictEqual(options.headers['Content-Type'], 'application/json')
}

describe('authStore.listTokens', () => {
  let auth
  beforeEach(() => {
    stubLocalStorage()
    setActivePinia(createPinia())
    auth = useAuthStore()
  })

  it('GET /api/tokens 带 Bearer 头、无 body，返回解析后的 data 数组', async () => {
    const data = [
      { id: 't1', name: 'ci-bot', created_at: 1730000000.5, expires_at: null, last_used_at: 1730000100.0 },
      { id: 't2', name: 'laptop', created_at: 1730000200.0, expires_at: 1730864200.0, last_used_at: null },
    ]
    const calls = stubFetch({ success: true, data })

    const result = await auth.listTokens()

    assert.strictEqual(calls.length, 1)
    assert.strictEqual(calls[0].url, '/api/tokens')
    assert.strictEqual(calls[0].options.method || 'GET', 'GET')
    assertAuthHeaders(calls[0].options)
    assert.strictEqual(calls[0].options.body, undefined)
    assert.deepStrictEqual(result, data)
  })

  it('success: false 时抛出含后端错误文案的 Error', async () => {
    stubFetch({ success: false, error: '此操作不支持个人MCP访问令牌' })
    await assert.rejects(() => auth.listTokens(), { message: '此操作不支持个人MCP访问令牌' })
  })
})

describe('authStore.createToken', () => {
  let auth
  beforeEach(() => {
    stubLocalStorage()
    setActivePinia(createPinia())
    auth = useAuthStore()
  })

  it('POST /api/tokens 携带 {name, expires_days} body，返回含明文 token 的 data', async () => {
    const data = {
      id: 't9', name: 'ci-bot', username: 'alice',
      token: 'pat_' + 'a'.repeat(64),
      created_at: 1730000000.5, expires_at: 1730000000.5 + 90 * 86400,
    }
    const calls = stubFetch({ success: true, data })

    const result = await auth.createToken('ci-bot', 90)

    assert.strictEqual(calls.length, 1)
    assert.strictEqual(calls[0].url, '/api/tokens')
    assert.strictEqual(calls[0].options.method, 'POST')
    assertAuthHeaders(calls[0].options)
    assert.deepStrictEqual(JSON.parse(calls[0].options.body), { name: 'ci-bot', expires_days: 90 })
    // createToken 返回解析后的 data，含一次性明文 token
    assert.deepStrictEqual(result, data)
    assert.strictEqual(result.token, 'pat_' + 'a'.repeat(64))
  })

  it('expiresDays 为 null（永不过期）时 body 携带 expires_days: null', async () => {
    const calls = stubFetch({
      success: true,
      data: { id: 't10', name: 'forever', username: 'alice', token: 'pat_' + 'b'.repeat(64), created_at: 1.0, expires_at: null },
    })

    await auth.createToken('forever', null)

    assert.strictEqual(calls[0].options.method, 'POST')
    assert.deepStrictEqual(JSON.parse(calls[0].options.body), { name: 'forever', expires_days: null })
  })

  it('success: false 时抛出含后端错误文案的 Error', async () => {
    stubFetch({ success: false, error: 'expires_days 必须在 1-3650 之间' })
    await assert.rejects(() => auth.createToken('bad', 0), { message: 'expires_days 必须在 1-3650 之间' })
  })
})

describe('authStore.revokeToken', () => {
  let auth
  beforeEach(() => {
    stubLocalStorage()
    setActivePinia(createPinia())
    auth = useAuthStore()
  })

  it('DELETE /api/tokens/{id} 带 Bearer 头、无 body，返回 undefined', async () => {
    const calls = stubFetch({ success: true })

    const result = await auth.revokeToken('tok-1')

    assert.strictEqual(calls.length, 1)
    assert.strictEqual(calls[0].url, '/api/tokens/tok-1')
    assert.strictEqual(calls[0].options.method, 'DELETE')
    assertAuthHeaders(calls[0].options)
    assert.strictEqual(calls[0].options.body, undefined)
    assert.strictEqual(result, undefined)
  })

  it('token id 经 URL 编码后拼进路径', async () => {
    const calls = stubFetch({ success: true })

    await auth.revokeToken('a/b c')

    assert.strictEqual(calls[0].url, '/api/tokens/a%2Fb%20c')
  })

  it('success: false（如 404 非本人/不存在）时抛出含后端错误文案的 Error', async () => {
    stubFetch({ success: false, error: '令牌不存在' })
    await assert.rejects(() => auth.revokeToken('missing'), { message: '令牌不存在' })
  })
})
