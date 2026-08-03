/**
 * 全局连接健康状态模块
 *
 * 统一管理 FileBrowser / Editor 两种模式下的后端连接状态。
 * 所有 overlay（offline / dead）均读取此模块，不再依赖 editor store 内部字段。
 */
import { ref } from 'vue'

/** 全局连接状态：'connecting' | 'connected' | 'offline' | 'dead' */
export const connectionStatus = ref('connecting')

/** 是否曾经连接成功过（用于区分"首次连接中"与"断连重连中"） */
export const hasBeenConnected = ref(false)

/**
 * 更新连接状态。
 * 当 status === 'connected' 时自动将 hasBeenConnected 置为 true。
 */
export function setConnectionStatus(status) {
  if (status === 'connected') hasBeenConnected.value = true
  connectionStatus.value = status
}

/** 重置连接状态（会话拆卸时调用） */
export function resetConnection() {
  connectionStatus.value = 'connecting'
  hasBeenConnected.value = false
}
