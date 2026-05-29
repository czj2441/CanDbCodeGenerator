const API_BASE = import.meta.env.DEV ? '' : 'http://localhost:8080'

let currentSessionId = localStorage.getItem('canmatrix_session_id') || ''

export function getSessionId() {
  return currentSessionId
}

export function setSessionId(id) {
  currentSessionId = id
  localStorage.setItem('canmatrix_session_id', id)
}

export function clearSession() {
  currentSessionId = ''
  localStorage.removeItem('canmatrix_session_id')
  localStorage.removeItem('canmatrix_file_name')
}

export async function api(method, path, body) {
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
  const res = await fetch(API_BASE + path, opts)
  const json = await res.json()
  if (!res.ok || !json.success) {
    throw new Error(json.error || `HTTP ${res.status}`)
  }
  return json.data
}
