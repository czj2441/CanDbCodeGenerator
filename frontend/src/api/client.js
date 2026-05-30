const API_BASE = import.meta.env.DEV ? '' : 'http://localhost:8080'

let currentSessionId = sessionStorage.getItem('canmatrix_session_id') || ''

const RECENT_KEY = 'canmatrix_recent_sessions'
const RECENT_MAX = 10

export function getSessionId() {
  return currentSessionId
}

export function setSessionId(id) {
  currentSessionId = id
  sessionStorage.setItem('canmatrix_session_id', id)
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

export async function api(method, path, body) {
  const t0 = performance.now()
  console.log(`[API] → ${method} ${path} START`, { hasBody: !!body, sessionId: currentSessionId ? 'yes' : 'no' })

  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (currentSessionId) {
    opts.headers['X-Session-Id'] = currentSessionId
  }
  if (body !== undefined && body !== null) {
    opts.body = JSON.stringify(body)
  }

  const t1 = performance.now()
  console.log(`[API]   ${method} ${path} fetch() called (+${(t1 - t0).toFixed(1)}ms)`)

  const res = await fetch(API_BASE + path, opts)

  const t2 = performance.now()
  console.log(`[API]   ${method} ${path} response received (+${(t2 - t0).toFixed(1)}ms, status=${res.status})`)

  const json = await res.json()

  const t3 = performance.now()
  console.log(`[API]   ${method} ${path} JSON parsed (+${(t3 - t0).toFixed(1)}ms, success=${json.success})`)

  if (!res.ok || !json.success) {
    console.error(`[API] ✗ ${method} ${path} FAILED:`, json.error || `HTTP ${res.status}`)
    throw new ApiError(json.error || `HTTP ${res.status}`, json.details, res.status)
  }

  console.log(`[API] ✓ ${method} ${path} DONE (+${(t3 - t0).toFixed(1)}ms total)`)
  return json.data
}
