/**
 * WebSocket Client — 前后端数据同步连接管理
 * 
 * 重连策略：指数退避（1s → 2s → 4s → ... → max 30s），无限次
 * 关闭码分类：4xxx 停止重连并通知 permanent_failure，其他码正常重连
 */

// ═══════════════════════════════════════════
// 前端 WS 诊断
// ═══════════════════════════════════════════

export const WsFrontendDiag = {
  _enabled: false,
  _counters: {
    connects: 0, disconnects: 0, msg_received: 0, msg_dropped: 0,
    lock_stolen: 0, full_sync: 0, signal_updated: 0
  },
  _timings: {},
  _lastVersion: 0,

  enable()  { this._enabled = true; console.log('[WS-DIAG] enabled') },
  disable() { this._enabled = false },

  _init() {
    if (new URLSearchParams(location.search).get('ws_debug') === '1'
        || localStorage.getItem('ws_debug') === '1') {
      this.enable()
    }
  },

  _log(level, event, data = {}) {
    if (!this._enabled) return
    const record = { ts: performance.now(), level, event, ...data }
    console.log(`[WS-DIAG] ${event}`, record)
  },

  count(name) {
    if (!this._enabled) return
    this._counters[name] = (this._counters[name] || 0) + 1
  },

  /** 返回 stop 函数 */
  timeStart(label) {
    if (!this._enabled) return () => {}
    const t0 = performance.now()
    return () => {
      const elapsed = performance.now() - t0
      const arr = this._timings[label] || (this._timings[label] = [])
      arr.push(elapsed)
      if (arr.length > 100) arr.shift()
    }
  },

  snapshot() {
    const avg = {}
    for (const [k, v] of Object.entries(this._timings)) {
      if (v.length) avg[k] = {
        avg_ms: Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100) / 100,
        samples: v.length
      }
    }
    return { enabled: this._enabled, counters: { ...this._counters }, timings: avg }
  }
}

// 挂载到 window 供 CLI 脚本访问
if (typeof window !== 'undefined') {
  window.__ws_diag__ = WsFrontendDiag
}
WsFrontendDiag._init()


// ═══════════════════════════════════════════
// API Error
// ═══════════════════════════════════════════

export class ApiError extends Error {
  constructor(message, code, details) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.details = details || {}
  }
}


// ═══════════════════════════════════════════
// WsSyncClient
// ═══════════════════════════════════════════

export class WsSyncClient {
  constructor({ url, sessionId, onMessage, onStatusChange }) {
    this.url = url
    this.sessionId = sessionId
    this.onMessage = onMessage
    this.onStatusChange = onStatusChange
    this._requestCounter = 0
    this._pendingRequests = new Map()  // requestId → { resolve, reject, timer }
    this._requestTimeout = 30000       // 30s
    this.baseDelay = 1000
    this.maxDelay = 30000
    this._intentionalClose = false
    this._reconnectAttempt = 0
    this._pingTimer = null
    this._reconnectTimer = null
    this.ws = null
    this.connected = false
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return
    this._intentionalClose = false

    try {
      this.ws = new WebSocket(this.url)
    } catch (e) {
      console.error('[WsSyncClient] WebSocket creation failed:', e)
      this._scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.connected = true
      this._reconnectAttempt = 0
      WsFrontendDiag.count('connects')

      // 发送 hello 握手（必须在 onStatusChange 之前，
      // 否则回调中发出的请求会早于 hello 到达服务器）
      this.ws.send(JSON.stringify({
        type: 'hello',
        session_id: this.sessionId,
        data_version: 0
      }))

      // 通知上层连接已建立（此回调可能触发 loadFiles 等请求）
      this.onStatusChange?.('connected')

      this._startPing()
    }

    this.ws.onmessage = (event) => this._handleMessage(event)

    this.ws.onclose = (event) => {
      this.connected = false
      this._stopPing()
      WsFrontendDiag.count('disconnects')
      this._cleanupPendingRequests()

      if (this._intentionalClose) {
        this.onStatusChange?.('disconnected')
        return
      }

      // 4xxx 关闭码 = 永久失败，停止重连
      if (event.code >= 4000 && event.code < 5000) {
        console.warn(`[WsSyncClient] Permanent failure: code=${event.code} reason=${event.reason}`)
        this.onStatusChange?.('permanent_failure')
        return
      }

      this.onStatusChange?.('disconnected')
      this._scheduleReconnect()
    }

    this.ws.onerror = () => { /* onclose follows */ }
  }

  disconnect() {
    this._intentionalClose = true
    this._stopPing()
    this._cancelReconnect()
    this._cleanupPendingRequests()
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    this.connected = false
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  /**
   * 请求-响应模式：发送请求并返回 Promise。
   * @param {string} type 消息类型
   * @param {object} data 消息数据
   * @param {number} [timeout] 可选，覆盖默认超时（ms）
   * @returns {Promise<object>} 响应数据
   */
  request(type, data, timeout) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return reject(new Error('Connection lost'))
      }
      const requestId = `r${++this._requestCounter}_${Date.now()}`
      const timer = setTimeout(() => {
        this._pendingRequests.delete(requestId)
        reject(new Error(`Request ${type} timed out`))
      }, timeout || this._requestTimeout)

      this._pendingRequests.set(requestId, { resolve, reject, timer })
      this.send({ type, requestId, data })
    })
  }

  /**
   * 消息处理分叉：
   * - ok/error → 匹配 pending promise
   * - 其他 → onMessage 广播回调
   */
  _handleMessage(event) {
    try {
      const msg = JSON.parse(event.data)

      if (msg.type === 'ok' || msg.type === 'error') {
        // 响应 → 匹配 pending promise
        const pending = this._pendingRequests.get(msg.requestId)
        if (pending) {
          clearTimeout(pending.timer)
          this._pendingRequests.delete(msg.requestId)
          if (msg.type === 'ok') {
            // data_version 只从广播更新（_applyWsMessage 中），不从 ok 响应更新
            // 防止自身操作的广播被版本号去重丢弃
            pending.resolve(msg.data)
          } else {
            pending.reject(new ApiError(msg.message, msg.code, msg.details))
          }
        }
      } else {
        // 广播 → 走 store 处理链路
        this.onMessage?.(msg)
      }
    } catch (e) {
      console.error('[WsSyncClient] parse error:', e)
    }
  }

  /** 重连时清理所有未完成请求 */
  _cleanupPendingRequests() {
    for (const [id, pending] of this._pendingRequests) {
      clearTimeout(pending.timer)
      pending.reject(new Error('Connection lost'))
    }
    this._pendingRequests.clear()
  }

  _scheduleReconnect() {
    if (this._intentionalClose) return
    this._cancelReconnect()
    const delay = Math.min(
      this.baseDelay * Math.pow(2, this._reconnectAttempt),
      this.maxDelay
    )
    this._reconnectAttempt++
    console.log(`[WsSyncClient] Reconnecting in ${delay}ms (attempt ${this._reconnectAttempt})`)
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null
      this.connect()
    }, delay)
  }

  _cancelReconnect() {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }
  }

  _startPing() {
    this._stopPing()
    this._pingTimer = setInterval(() => {
      this.send({ type: 'ping' })
    }, 10000)  // 10s 心跳
  }

  _stopPing() {
    if (this._pingTimer) {
      clearInterval(this._pingTimer)
      this._pingTimer = null
    }
  }
}
