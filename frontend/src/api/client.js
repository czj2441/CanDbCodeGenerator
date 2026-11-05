// 延迟读取：确保 main.js 完成旧存储键迁移后再访问 sessionStorage
let currentSessionId = null

export function getSessionId() {
  if (currentSessionId === null) {
    currentSessionId = sessionStorage.getItem('candb_session_id') || ''
  }
  return currentSessionId
}

export function setSessionId(id) {
  currentSessionId = id
  sessionStorage.setItem('candb_session_id', id)
}
