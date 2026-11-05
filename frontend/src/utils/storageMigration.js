/**
 * 浏览器存储键迁移：canmatrix_* -> candb_*
 *
 * 品牌重命名后 localStorage / sessionStorage 的键前缀从 canmatrix_ 改为 candb_。
 * 该模块在应用启动、任何 store 读取存储之前执行一次，把旧键值迁移到新键：
 *   - 只处理 canmatrix_ 前缀，不影响其他站点/调试键
 *   - 新键不存在时才复制旧值；新键已存在时保留新值（新值优先）
 *   - 迁移后删除旧键，重复执行幂等
 *   - 存储不可用（隐私模式/浏览器策略）时静默跳过，不能阻断应用启动
 */

const LEGACY_PREFIX = 'canmatrix_'
const NEW_PREFIX = 'candb_'

/**
 * 迁移单个 Storage 实例（localStorage 或 sessionStorage）。
 * @param {Storage|null|undefined} storage
 * @returns {number} 实际复制到新键的数量
 */
export function migrateStorage(storage) {
  if (!storage) return 0

  let migrated = 0
  try {
    // 先收集再删除：删除键会改变 storage 的索引顺序
    const legacyKeys = []
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i)
      if (key && key.startsWith(LEGACY_PREFIX)) legacyKeys.push(key)
    }

    for (const legacyKey of legacyKeys) {
      const newKey = NEW_PREFIX + legacyKey.slice(LEGACY_PREFIX.length)
      const value = storage.getItem(legacyKey)
      if (value !== null && storage.getItem(newKey) === null) {
        storage.setItem(newKey, value)
        migrated++
      }
      storage.removeItem(legacyKey)
    }
  } catch (e) {
    // 浏览器禁用存储时不能让迁移阻断启动
    console.warn('[storage-migration] skipped:', e)
  }
  return migrated
}

/**
 * 迁移当前页面的 localStorage 与 sessionStorage。
 * 必须在 Pinia store 初始化之前调用（见 src/main.js）。
 * @returns {number} 两个 Storage 中实际复制的键总数
 */
export function migrateLegacyStorage() {
  if (typeof window === 'undefined') return 0

  let migrated = 0
  for (const storageName of ['localStorage', 'sessionStorage']) {
    try {
      migrated += migrateStorage(window[storageName])
    } catch (e) {
      // 某些浏览器在禁用存储时连访问 getter 都会抛异常
      console.warn(`[storage-migration] ${storageName} inaccessible:`, e)
    }
  }
  return migrated
}
