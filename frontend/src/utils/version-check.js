/**
 * 版本比较 — 全局唯一真相来源
 *
 * 所有 WS 连接（编辑器 + 文件浏览器）的版本比较统一走此模块。
 * 由 WsSyncClient._handleMessage() 拦截 pong / server_version 后调用 checkVersionHash()。
 */
import { ref } from 'vue'

// 编译时注入的前端版本哈希
const CLIENT_HASH = typeof __AUTO_VERSION__ !== 'undefined'
  ? __AUTO_VERSION__.split('_')[0] : ''

// 全局响应式状态（App.vue overlay 直接绑定）
export const versionMismatch = ref(false)
export const serverVersionInfo = ref(null)

/**
 * 比较前后端版本哈希 — 所有 WS 连接统一调用此函数
 * @param {object} data - 后端推送的版本数据 { auto_version, manual_version, hash }
 */
export function checkVersionHash(data) {
  if (!data?.auto_version) return
  serverVersionInfo.value = data
  const serverHash = (data.auto_version || '').split('_')[0]
  versionMismatch.value = !!(
    CLIENT_HASH && CLIENT_HASH !== 'dev' &&
    serverHash && CLIENT_HASH !== serverHash
  )
}
