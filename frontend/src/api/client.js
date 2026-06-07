const API_BASE = import.meta.env.DEV ? '' : 'http://localhost:8080'

let currentSessionId = sessionStorage.getItem('canmatrix_session_id') || ''

const RECENT_KEY = 'canmatrix_recent_sessions'
const RECENT_MAX = 10

// ── 多标签页冲突检测 ──

const TAB_CHANNEL = new BroadcastChannel('canmatrix_tab_sync')
const TAB_ID = crypto.randomUUID()
let tabChannelInitialized = false
let beforeunloadHandler = null

/**
 * 初始化多标签页冲突检测
 * 在应用启动时调用一次
 */
export function initTabSync(onConflict) {
  if (tabChannelInitialized) return
  tabChannelInitialized = true

  // 声明当前标签页的 session
  TAB_CHANNEL.postMessage({
    type: 'tab_register',
    tabId: TAB_ID,
    sessionId: currentSessionId,
    timestamp: Date.now()
  })

  // 监听其他标签页的 session 变更
  TAB_CHANNEL.onmessage = (event) => {
    const { type, tabId, sessionId } = event.data

    if (type === 'tab_register' && tabId !== TAB_ID) {
      // 检测到其他标签页，检查是否编辑不同 session
      if (currentSessionId && sessionId && currentSessionId !== sessionId) {
        onConflict?.(currentSessionId, sessionId)
      }
    } else if (type === 'session_change' && tabId !== TAB_ID) {
      // 其他标签页切换了 session
      if (currentSessionId && sessionId && currentSessionId !== sessionId) {
        onConflict?.(currentSessionId, sessionId)
      }
    }
  }

  // 页面关闭时清理
  beforeunloadHandler = () => {
    TAB_CHANNEL.postMessage({
      type: 'tab_unregister',
      tabId: TAB_ID,
      timestamp: Date.now()
    })
  }
  window.addEventListener('beforeunload', beforeunloadHandler)
}

/**
 * 清理多标签页同步资源
 */
export function cleanupTabSync() {
  if (beforeunloadHandler) {
    window.removeEventListener('beforeunload', beforeunloadHandler)
    beforeunloadHandler = null
  }
  // 不要 close TAB_CHANNEL，保持 channel 开放以便重新初始化
  // 只清理 onmessage handler 停止处理消息
  if (TAB_CHANNEL) {
    TAB_CHANNEL.onmessage = null
  }
  tabChannelInitialized = false
}

/**
 * 通知其他标签页当前 session 已变更
 */
export function notifySessionChange(newSessionId) {
  TAB_CHANNEL.postMessage({
    type: 'session_change',
    tabId: TAB_ID,
    sessionId: newSessionId,
    timestamp: Date.now()
  })
}

export function getSessionId() {
  return currentSessionId
}

export function setSessionId(id) {
  currentSessionId = id
  sessionStorage.setItem('canmatrix_session_id', id)
  // 通知其他标签页
  notifySessionChange(id)
}

export function clearSession() {
  currentSessionId = ''
  sessionStorage.removeItem('canmatrix_session_id')
  sessionStorage.removeItem('canmatrix_file_name')
}

export function addRecentSession(id, fileName) {
  if (!id) return
  const raw = localStorage.getItem(RECENT_KEY) || '[]'
  let list = []
  try { list = JSON.parse(raw) } catch (_) {}
  list = list.filter(item => item.session_id !== id)
  list.unshift({ session_id: id, file_name: fileName || '', timestamp: Date.now() })
  if (list.length > RECENT_MAX) list = list.slice(0, RECENT_MAX)
  localStorage.setItem(RECENT_KEY, JSON.stringify(list))
}

export function getRecentSessions() {
  const raw = localStorage.getItem(RECENT_KEY) || '[]'
  try { return JSON.parse(raw) } catch (_) { return [] }
}

export function removeRecentSession(id) {
  const raw = localStorage.getItem(RECENT_KEY) || '[]'
  let list = []
  try { list = JSON.parse(raw) } catch (_) {}
  list = list.filter(item => item.session_id !== id)
  localStorage.setItem(RECENT_KEY, JSON.stringify(list))
}

export class ApiError extends Error {
  constructor(message, details, status) {
    super(message)
    this.details = details
    this.status = status
  }
}

export async function api(method, path, body, extraHeaders = {}) {
  const t0 = performance.now()
  if (import.meta.env.DEV) {
    console.log(`[API] → ${method} ${path} START`, { hasBody: !!body, sessionId: currentSessionId ? 'yes' : 'no' })
  }

  const opts = {
    method,
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
  }
  if (currentSessionId) {
    opts.headers['X-Session-Id'] = currentSessionId
  }
  if (body !== undefined && body !== null) {
    opts.body = JSON.stringify(body)
  }

  const t1 = performance.now()
  if (import.meta.env.DEV) {
    console.log(`[API]   ${method} ${path} fetch() called (+${(t1 - t0).toFixed(1)}ms)`)
  }

  const res = await fetch(API_BASE + path, opts)

  const t2 = performance.now()
  if (import.meta.env.DEV) {
    console.log(`[API]   ${method} ${path} response received (+${(t2 - t0).toFixed(1)}ms, status=${res.status})`)
  }

  const json = await res.json()

  const t3 = performance.now()
  if (import.meta.env.DEV) {
    console.log(`[API]   ${method} ${path} JSON parsed (+${(t3 - t0).toFixed(1)}ms, success=${json.success})`)
  }

  if (!res.ok || !json.success) {
    if (import.meta.env.DEV) {
      console.error(`[API] ✗ ${method} ${path} FAILED:`, json.error || `HTTP ${res.status}`)
    }
    throw new ApiError(json.error || `HTTP ${res.status}`, json.details, res.status)
  }

  if (import.meta.env.DEV) {
    console.log(`[API] ✓ ${method} ${path} DONE (+${(t3 - t0).toFixed(1)}ms total)`)
  }
  return json.data
}
