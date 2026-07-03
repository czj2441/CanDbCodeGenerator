let currentSessionId = sessionStorage.getItem('canmatrix_session_id') || ''

export function getSessionId() {
  return currentSessionId
}

export function setSessionId(id) {
  currentSessionId = id
  sessionStorage.setItem('canmatrix_session_id', id)
}
