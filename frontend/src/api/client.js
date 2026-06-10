const API_BASE = import.meta.env.DEV ? '' : 'http://localhost:8080'

let currentSessionId = sessionStorage.getItem('canmatrix_session_id') || ''

// ── 多标签页冲突检测 ──

const TAB_CHANNEL = new BroadcastChannel('canmatrix_tab_sync')
const TAB_ID = crypto.randomUUID()
let tabChannelInitialized = false
let beforeunloadHandler = null

/**
 * 初始化多标签页同步
 * 在应用启动时调用一次
 * @param {Function} onStolen - 当前 session 被抢占时的回调
 */
export function initTabSync(onStolen) {
  if (tabChannelInitialized) return
  tabChannelInitialized = true

  // 监听其他标签页的消息
  TAB_CHANNEL.onmessage = (event) => {
    const { type, tabId, stolenSessionId } = event.data
    console.log(`[TabSync] onmessage received: type=${type}, tabId=${tabId}, my TAB_ID=${TAB_ID}, currentSessionId=${currentSessionId}`)

    if (type === 'session_stolen' && tabId !== TAB_ID) {
      // 当前 session 被其他标签页抢占
      console.log(`[TabSync] session_stolen received: stolenSessionId=${stolenSessionId}, currentSessionId=${currentSessionId}, match=${stolenSessionId === currentSessionId}`)
      if (stolenSessionId && stolenSessionId === currentSessionId) {
        console.log(`[TabSync] session_stolen MATCHED! calling onStolen callback`)
        onStolen?.(stolenSessionId)
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

/**
 * 通知其他标签页指定 session 已被抢占
 */
export function notifySessionStolen(stolenSessionId) {
  console.log(`[TabSync] notifySessionStolen: sending session_stolen message for session ${stolenSessionId}`)
  TAB_CHANNEL.postMessage({
    type: 'session_stolen',
    tabId: TAB_ID,
    stolenSessionId: stolenSessionId,
    timestamp: Date.now()
  })
  console.log(`[TabSync] notifySessionStolen: message sent, my TAB_ID=${TAB_ID}`)
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
  // 只有当 extraHeaders 中没有显式设置 X-Session-Id 时，才使用 currentSessionId
  if (!('X-Session-Id' in extraHeaders) && currentSessionId) {
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