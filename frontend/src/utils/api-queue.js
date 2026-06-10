 /**
 * API 请求队列工具类
 * 
 * 解决乐观更新的并发安全问题：
 * 1. 防抖（Debounce）：500ms 内同一 key 只执行最后一次修改
 * 2. 队列（Queue）：同一 key 的请求串行执行，防止乱序
 * 3. 超时（Timeout）：5000ms 超时自动失败并触发回滚
 * 
 * 使用示例：
 * ```javascript
 * const queue = new ApiQueue({ debounceDelay: 500, timeout: 5000 })
 * 
 * // 入队请求
 * queue.enqueue(
 *   'signal_abc123_start_bit',  // key：同一 key 串行执行
 *   () => api('PUT', '/api/messages/1/signals/abc123', { start_bit: 10 }),
 *   { start_bit: 5 },  // fallbackValue：超时/失败时的回滚值
 *   (sig) => { sig.start_bit = 5 }  // onRollback：回滚函数
 * )
 * 
 * // 组件卸载时清理
 * queue.cleanup()
 * ```
 */
export class ApiQueue {
  /**
   * @param {Object} options
   * @param {number} options.debounceDelay - 防抖延迟（ms），默认 500ms
   * @param {number} options.timeout - 超时时间（ms），默认 5000ms
   */
  constructor({ debounceDelay = 500, timeout = 5000 } = {}) {
    this.debounceDelay = debounceDelay
    this.timeout = timeout

    // 队列存储：key -> QueueEntry
    /** @type {Map<string, QueueEntry>} */
    this.queues = new Map()

    // 防抖定时器：key -> Timer ID
    /** @type {Map<string, number>} */
    this.debounceTimers = new Map()

    // 活跃请求：key -> { timeoutTimer, abortController }
    /** @type {Map<string, ActiveRequest>} */
    this.activeRequests = new Map()
  }

  /**
   * 入队请求
   * 
   * @param {string} key - 队列键（格式：`signal_${uuid}_${field}` 或 `message_${id}_${field}`）
   * @param {Function} apiCall - API 调用函数，返回 Promise
   * @param {*} fallbackValue - 超时/失败时的回滚值
   * @param {Function} onRollback - 回滚函数 (fallbackValue) => void
   * @returns {Promise<any>} API 调用结果
   */
  enqueue(key, apiCall, fallbackValue, onRollback) {
    // 1. 清除该 key 的防抖定时器（如果存在）
    const existingTimer = this.debounceTimers.get(key)
    if (existingTimer) {
      clearTimeout(existingTimer)
    }

    // 2. 获取或创建队列条目
    let entry = this.queues.get(key)
    if (!entry) {
      entry = {
        key,
        pending: [],  // 等待执行的请求队列
        running: false,  // 是否正在执行
      }
      this.queues.set(key, entry)
    }

    // 3. 创建 Promise 包装器
    return new Promise((resolve, reject) => {
      // 将请求推入队列
      entry.pending.push({
        apiCall,
        fallbackValue,
        onRollback,
        resolve,
        reject,
      })

      // 设置防抖定时器
      const timerId = setTimeout(() => {
        this.debounceTimers.delete(key)
        this._executeQueue(key)
      }, this.debounceDelay)

      this.debounceTimers.set(key, timerId)
    })
  }

  /**
   * 执行队列中的请求（串行执行）
   * @param {string} key 
   * @private
   */
  async _executeQueue(key) {
    const entry = this.queues.get(key)
    if (!entry || entry.pending.length === 0) {
      // 队列为空，清理
      this.queues.delete(key)
      return
    }

    // 如果正在执行，等待完成
    if (entry.running) {
      return
    }

    entry.running = true

    // 取出最后一次请求（防抖后的最新值）
    const lastRequest = entry.pending[entry.pending.length - 1]

    // 清除之前的所有请求（只保留最后一次）
    for (let i = 0; i < entry.pending.length - 1; i++) {
      const req = entry.pending[i]
      // 中间请求直接 resolve（不执行，不失败）
      req.resolve({ skipped: true, reason: 'debounced' })
    }
    entry.pending = [lastRequest]

    try {
      // 执行 API 调用
      const result = await this._executeWithTimeout(key, lastRequest)
      lastRequest.resolve(result)
    } catch (error) {
      // 超时或失败，执行回滚
      lastRequest.onRollback(lastRequest.fallbackValue)
      lastRequest.reject(error)
    } finally {
      entry.running = false
      entry.pending = []

      // 如果队列中还有新请求，继续执行
      if (entry.pending.length > 0) {
        this._executeQueue(key)
      } else {
        // 队列清空，清理
        this.queues.delete(key)
      }
    }
  }

  /**
   * 带超时的 API 执行
   * @param {string} key 
   * @param {Object} request 
   * @returns {Promise<any>}
   * @private
   */
  _executeWithTimeout(key, request) {
    return new Promise((resolve, reject) => {
      const timeoutTimer = setTimeout(() => {
        this.activeRequests.delete(key)
        reject(new Error(`API request timeout after ${this.timeout}ms (key: ${key})`))
      }, this.timeout)

      this.activeRequests.set(key, { timeoutTimer })

      request.apiCall()
        .then(result => {
          this.activeRequests.delete(key)
          clearTimeout(timeoutTimer)
          resolve(result)
        })
        .catch(error => {
          this.activeRequests.delete(key)
          clearTimeout(timeoutTimer)
          reject(error)
        })
    })
  }

  /**
   * 清理所有队列和定时器
   * 在组件卸载时调用，防止内存泄漏
   */
  cleanup() {
    // 清理防抖定时器
    for (const [key, timerId] of this.debounceTimers) {
      clearTimeout(timerId)
    }
    this.debounceTimers.clear()

    // 清理超时定时器
    for (const [key, activeReq] of this.activeRequests) {
      clearTimeout(activeReq.timeoutTimer)
    }
    this.activeRequests.clear()

    // 清理队列
    for (const [key, entry] of this.queues) {
      // 拒绝所有待处理的请求
      for (const req of entry.pending) {
        req.reject(new Error('Queue cleaned up'))
      }
    }
    this.queues.clear()

    console.log('[ApiQueue] cleanup() completed')
  }

  /**
   * 获取队列状态（调试用）
   * @returns {Object}
   */
  getStatus() {
    return {
      queueCount: this.queues.size,
      activeRequestCount: this.activeRequests.size,
      debounceTimerCount: this.debounceTimers.size,
      queues: Array.from(this.queues.keys()),
    }
  }
}

/**
 * @typedef {Object} QueueEntry
 * @property {string} key
 * @property {Array<QueueRequest>} pending
 * @property {boolean} running
 */

/**
 * @typedef {Object} QueueRequest
 * @property {Function} apiCall
 * @property {*} fallbackValue
 * @property {Function} onRollback
 * @property {Function} resolve
 * @property {Function} reject
 */

/**
 * @typedef {Object} ActiveRequest
 * @property {number} timeoutTimer
 */

// 副作用：防止 Vite Tree Shaking 移除本模块
if (typeof window !== 'undefined') window.__ApiQueueLoaded__ = true
