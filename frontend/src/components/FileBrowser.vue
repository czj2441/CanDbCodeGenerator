<template>
  <div class="file-browser">
    <div class="browser-header">
      <div class="brand-logo">Can<span>DbCodeGenerator</span></div>
      <div class="header-actions">
        <button
          class="btn-toggle-files"
          :class="{ active: showAllFiles }"
          @click="showAllFiles = !showAllFiles"
          :title="showAllFiles ? '显示所有文件' : '仅显示我的文件'"
        >
          {{ showAllFiles ? '所有文件' : '我的文件' }}
        </button>
        <div class="btn-group">
          <button class="btn-icon" @click="createNew" :title="t('browser.newFileTooltip')">
            <FilePlus :size="16" />
          </button>
          <button class="btn-icon" @click="triggerImport" :title="t('browser.importFileTooltip')">
            <Upload :size="16" />
          </button>
          <button class="btn-icon" @click="manualRefresh" :disabled="isRefreshing" :title="t('browser.refreshTooltip')">
            <RefreshCw :size="16" :class="{ 'spin': isRefreshing }" />
          </button>
          <button 
            v-if="selectedFiles.length > 0" 
            class="btn-icon btn-danger-icon"
            :disabled="deleting"
            :title="t('browser.deleteSelectedTooltip')"
            @click="confirmDelete"
          >
            <Trash2 :size="16" />
          </button>
        </div>
        <button 
          class="debug-icon-btn" 
          :class="{ active: showDebug }"
          @click="showDebug = !showDebug; if (showDebug) loadSnapshotDebug()"
          title="Snapshot Debug"
        >
          <Wrench :size="14" />
        </button>
      </div>
      <div class="header-spacer"></div>
      <div class="header-right">
        <!-- 搜索工具栏 -->
        <div class="filter-bar">
          <div class="search-wrapper">
            <input
              v-model="searchQuery"
              class="search-input"
              type="text"
              :placeholder="t('browser.searchPlaceholder')"
            />
            <button
              v-if="searchQuery"
              class="search-clear-btn"
              @click="searchQuery = ''"
              :title="t('browser.searchClear')"
            >✕</button>
          </div>
          <span class="result-count" v-if="searchQuery">
            {{ t('browser.resultCount', { shown: displayedFiles.length, total: files.length }) }}
          </span>
        </div>
        <button class="btn-icon" @click="ui.toggleTheme" title="切换主题">
          <Moon v-if="ui.theme === 'dark'" :size="16" />
          <Sun v-else :size="16" />
        </button>
        <div class="user-menu-wrapper" @click.stop>
          <button class="user-menu-btn" @click="toggleUserMenu">
            {{ authStore.username }}
            <ChevronDown :size="14" />
          </button>
          <div v-if="userMenuOpen" class="user-menu-dropdown">
            <div class="user-menu-header">
              <span class="user-menu-name">{{ authStore.username }}</span>
              <span class="user-menu-role">{{ authStore.role }}</span>
            </div>
            <div class="user-menu-divider"></div>
            <div v-if="authStore.isAdmin" class="user-menu-item" @click="userMgmtOpen = true; userMenuOpen = false">
              用户管理
            </div>
            <div class="user-menu-item" @click="changePwdOpen = true; userMenuOpen = false">
              修改密码
            </div>
            <div class="user-menu-divider"></div>
            <div class="user-menu-item user-menu-danger" @click="requestLogout">
              退出登录
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 表格形式文件列表 -->
    <div class="table-container">
      <table class="file-table">
        <thead>
          <tr>
            <th class="col-checkbox">
              <input 
                type="checkbox" 
                :checked="selectAll" 
                :indeterminate="!selectAll && selectedFiles.length > 0"
                @change="toggleSelectAll"
              />
            </th>
            <th class="col-name sortable" @click.stop="toggleSort('name')">
              {{ t('browser.colName') }} <span class="sort-icon">{{ getSortIcon('name') }}</span>
            </th>
            <th class="col-messages sortable" @click.stop="toggleSort('message_count')">
              {{ t('browser.colMessages') }} <span class="sort-icon">{{ getSortIcon('message_count') }}</span>
            </th>
            <th class="col-signals sortable" @click.stop="toggleSort('signal_count')">
              {{ t('browser.colSignals') }} <span class="sort-icon">{{ getSortIcon('signal_count') }}</span>
            </th>
            <th class="col-time sortable" @click.stop="toggleSort('mtime')">
              {{ t('browser.colTime') }} <span class="sort-icon">{{ getSortIcon('mtime') }}</span>
            </th>
            <th class="col-owner">所有者</th>
            <th class="col-status">{{ t('browser.colStatus') }}</th>
            <th class="col-actions">{{ t('browser.colActions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="initialLoading && files.length === 0">
            <td colspan="8" class="loading-state">
              <div class="loading-content">
                <div class="browser-spinner"></div>
                <p class="loading-text">{{ t('browser.loading') }}</p>
              </div>
            </td>
          </tr>
          <tr v-else-if="files.length === 0">
            <td colspan="8" class="empty-state">
              <div class="empty-state-content">
                <div class="empty-icon">📂</div>
                <p class="empty-title">{{ t('browser.emptyTitle') }}</p>
                <p class="empty-desc">{{ t('browser.emptyDesc') }}</p>
                <button class="empty-btn" @click="createNew">{{ t('browser.emptyNewBtn') }}</button>
                <button class="empty-btn empty-btn-secondary" @click="triggerImport">{{ t('browser.emptyImportBtn') }}</button>
                <ul class="empty-hints">
                  <li>{{ t('browser.emptyHint1') }}</li>
                  <li>{{ t('browser.emptyHint2') }}</li>
                  <li>{{ t('browser.emptyHint3') }}</li>
                </ul>
              </div>
            </td>
          </tr>
          <tr v-else-if="displayedFiles.length === 0">
            <td colspan="8" class="empty-state filter-empty">
              <div class="empty-state-content">
                <div class="empty-icon">🔍</div>
                <p class="empty-title">{{ t('browser.noResults') }}</p>
                <p class="empty-desc">{{ t('browser.noResultsHint') }}</p>
              </div>
            </td>
          </tr>
          <tr
            v-for="file in displayedFiles"
            :key="file.file_name"
            class="file-row"
            :class="{ 
              'locked': file.is_locked,
              'selected': selectedFiles.includes(file.file_name),
              'opening': openingSessionId === file.file_name,
              'readonly-row': file.owner && !file.can_write
            }"
            @click="toggleSelectFile(file)"
            @contextmenu="onFileContextMenu($event, file)"
          >
            <td class="col-checkbox" @click.stop>
              <input 
                type="checkbox" 
                :checked="selectedFiles.includes(file.file_name)"
                :disabled="file.is_locked"
                @change="toggleSelectFile(file)"
              />
            </td>
            <td class="col-name" @click.stop="open(file)">
              <span class="file-name-link">{{ file.name }}</span>
              <span v-if="file.owner && !file.can_write" class="readonly-badge" title="只读 — 非所有者">🔒</span>
              <span v-else-if="!file.owner" class="unowned-badge" title="无所有者 — 全员只读">⚪</span>
            </td>
            <td class="col-messages">{{ file.message_count }}</td>
            <td class="col-signals">{{ file.signal_count }}</td>
            <td class="col-time">{{ formatTime(file.mtime) }}</td>
            <td class="col-owner">
              <span v-if="file.owner" class="owner-name">{{ file.owner }}</span>
              <span v-else class="no-owner">—</span>
            </td>
            <td class="col-status">
              <span v-if="file.is_locked" class="lock-badge">{{ t('browser.locked') }}</span>
              <span v-else-if="file.is_modified" class="unsaved-badge">{{ t('browser.unsaved') }}</span>
              <span v-else-if="file.has_snapshot" class="snapshot-badge" title="有未保存的恢复数据，打开后可恢复">↻ 有恢复数据</span>
            </td>
            <td class="col-actions" @click.stop>
              <button
                v-if="!file.is_locked || !file.can_write"
                class="open-btn"
                :title="t('browser.openTooltip')"
                @click="open(file)"
              >{{ t('browser.open') }}</button>
              <button 
                v-else 
                class="steal-btn"
                :title="t('browser.stealTooltip')"
                @click="confirmSteal(file)"
              >{{ t('browser.steal') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Snapshot Debug 面板 -->
    <div class="snapshot-debug" v-if="showDebug">
      <div class="debug-header" @click="debugExpanded = !debugExpanded">
        <span>🔧 Snapshot Debug</span>
        <span class="debug-toggle">{{ debugExpanded ? '▼' : '▶' }}</span>
      </div>
      <div class="debug-content" v-if="debugExpanded">
        <div class="debug-section">
          <h4>内存 Session ({{ snapshotDebug.in_memory?.length || 0 }})</h4>
          <table v-if="snapshotDebug.in_memory?.length">
            <tr><th>Session</th><th>文件</th><th>Modified</th><th>报文</th><th>Undo/Redo</th></tr>
            <tr v-for="s in snapshotDebug.in_memory" :key="s.session_id">
              <td>{{ s.session_id.slice(0, 8) }}</td>
              <td>{{ s.file_name }}</td>
              <td :class="{ 'modified-yes': s.modified }">{{ s.modified ? '✓ 脏' : '—' }}</td>
              <td>{{ s.message_count }}</td>
              <td>{{ s.undo_count }}/{{ s.redo_count }}</td>
            </tr>
          </table>
        </div>
        <div class="debug-section">
          <h4>磁盘快照 ({{ snapshotDebug.on_disk?.length || 0 }})</h4>
          <table v-if="snapshotDebug.on_disk?.length">
            <tr><th>Session</th><th>文件</th><th>快照时间</th><th>大小</th><th>报文数</th></tr>
            <tr v-for="s in snapshotDebug.on_disk" :key="s.session_id">
              <td>{{ s.session_id.slice(0, 8) }}</td>
              <td>{{ s.file_name }}</td>
              <td>{{ formatTime(s.snapshotted_at) }}</td>
              <td>{{ (s.size_bytes / 1024).toFixed(1) }}KB</td>
              <td>{{ s.message_count }}</td>
            </tr>
          </table>
          <p v-else class="debug-empty">无快照文件</p>
        </div>
      </div>
    </div>

    <!-- 抢占确认对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="stealModalOpen" class="modal-overlay" @mousedown.self="closeStealModal">
          <div class="modal-box" @click.stop>
            <h3>{{ t('browser.stealConfirmTitle') }}</h3>
            <p>
              <strong>{{ stealingFile?.name }}</strong><br>
              {{ t('browser.stealConfirmDesc') }}
            </p>
            <div class="modal-actions">
              <button class="btn btn-cancel" @click="closeStealModal">{{ t('browser.stealCancel') }}</button>
              <button class="btn btn-confirm" @click="executeSteal">{{ t('browser.stealConfirm') }}</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 删除确认对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="deleteModalOpen" class="modal-overlay" @mousedown.self="closeDeleteModal">
          <div class="modal-box" @click.stop>
            <h3>{{ t('browser.deleteConfirmTitle') }}</h3>
            <p>
              {{ t('browser.deleteConfirmDesc', { count: pendingDeleteFiles.length }) }}
              <ul class="file-list-preview">
                <li v-for="(file, idx) in displayedDeleteFiles" :key="file.session_id">
                  {{ file.name }}
                </li>
                <li v-if="pendingDeleteFiles.length > 5" class="more-files">
                  {{ t('browser.deleteMoreFiles', { count: pendingDeleteFiles.length }) }}
                </li>
              </ul>
            </p>
            <div class="modal-actions">
              <button class="btn btn-cancel" @click="closeDeleteModal">{{ t('browser.deleteConfirmCancel') }}</button>
              <button class="btn btn-danger" :disabled="deleting" @click="executeDelete">
                {{ deleting ? t('browser.deleting') : t('browser.deleteConfirmDelete') }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 新建文件对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="newFileModalOpen" class="modal-overlay" @mousedown.self="closeNewFileModal">
          <div class="modal-box" @click.stop>
            <h3>{{ t('browser.newFileTitle') }}</h3>
            <p>{{ t('browser.newFileLabel') }}</p>
            <input
              ref="newFileInputRef"
              v-model="newFileName"
              class="new-file-input"
              :placeholder="t('browser.newFilePlaceholder')"
              @keydown.enter="executeNewFile"
              @keydown.escape="closeNewFileModal"
            />
            <div class="modal-actions">
              <button class="btn btn-cancel" @click="closeNewFileModal">{{ t('browser.newFileCancel') }}</button>
              <button class="btn btn-confirm" @click="executeNewFile">
                {{ t('browser.newFileCreate') }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 导入确认对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="importConfirmOpen" class="modal-overlay" @mousedown.self="importConfirmOpen = false">
          <div class="modal-box" @click.stop>
            <h3>{{ t('browser.importConfirmTitle') }}</h3>
            <p>{{ t('browser.importConfirmDesc') }}</p>
            <p class="import-filename"><strong>{{ pendingImportFile?.file.name }}</strong></p>
            <div class="modal-actions">
              <button class="btn btn-cancel" @click="importConfirmOpen = false">{{ t('browser.importConfirmCancel') }}</button>
              <button class="btn btn-confirm" @click="executeImport">{{ t('browser.importConfirmBtn') }}</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 隐藏的文件输入 -->
    <input
      ref="importFileInput"
      type="file"
      accept=".dbc,.properties"
      style="display: none"
      @change="handleImportFileSelect"
    />

    <!-- 右键菜单 -->
    <Teleport to="body">
      <div
        v-if="contextMenuOpen"
        class="ctx-menu"
        :style="{ left: contextMenuPos.x + 'px', top: contextMenuPos.y + 'px' }"
        @click.stop
      >
        <div v-if="authStore.isAdmin && contextMenuFile?.owner" class="ctx-item" @click="openTransferOwnerModal">
          转移所有权
        </div>
        <div v-if="authStore.isAdmin && !contextMenuFile?.owner" class="ctx-item" @click="executeTakeOver">
          接管文件
        </div>
        <div v-if="!authStore.isAdmin && !contextMenuFile?.owner" class="ctx-item disabled">
          无所有者（仅管理员可操作）
        </div>
        <div v-if="contextMenuFile?.owner && !contextMenuFile?.can_write" class="ctx-item disabled">
          只读 — 所有者: {{ contextMenuFile?.owner }}
        </div>
      </div>
    </Teleport>

    <!-- 转移所有权对话框 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="transferOwnerModalOpen" class="modal-overlay" @mousedown.self="closeTransferOwnerModal">
          <div class="modal-box" @click.stop>
            <h3>转移文件所有权</h3>
            <p>将 <strong>{{ transferOwnerFile?.name }}</strong> 的所有权转移给：</p>
            <select v-model="transferOwnerTarget" class="new-file-input">
              <option value="" disabled>选择用户...</option>
              <option v-for="u in userList" :key="u.username" :value="u.username">
                {{ u.username }} ({{ u.role }})
              </option>
            </select>
            <div class="modal-actions">
              <button class="btn btn-cancel" @click="closeTransferOwnerModal">取消</button>
              <button class="btn btn-confirm" :disabled="!transferOwnerTarget" @click="executeTransferOwner">确认转移</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 底部状态栏 -->
    <div class="browser-footer">
      <ConnectionStatus :status="connectionStatus" />
      <span class="version-tag">{{ manualVersion }} {{ autoVersion }}</span>
    </div>

    <!-- 用户管理 Modal -->
    <UserManagementModal v-model:visible="userMgmtOpen" />

    <!-- 修改密码 Modal -->
    <ChangePasswordModal v-model:visible="changePwdOpen" />

    <!-- 退出登录确认 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="logoutConfirmOpen" class="modal-overlay" @mousedown.self="logoutConfirmOpen = false">
          <div class="modal-box" @click.stop>
            <h3>退出登录</h3>
            <p>确定要退出当前账号吗？</p>
            <div class="modal-actions">
              <button class="btn btn-cancel" @click="logoutConfirmOpen = false">取消</button>
              <button class="btn btn-confirm" @click="confirmLogout">确认退出</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { getSessionId } from '../api/client.js'
import { useUiStore } from '../stores/uiStore.js'
import { useAuthStore } from '../stores/authStore.js'
import { t } from '../i18n.js'
import { WsSyncClient } from '../utils/ws-client.js'
import { setConnectionStatus, connectionStatus } from '../stores/connectionHealth.js'
import { FilePlus, Upload, Trash2, Wrench, KeyRound, LogOut, ChevronDown, Moon, Sun, RefreshCw } from '@lucide/vue'
import ConnectionStatus from './ConnectionStatus.vue'
import UserManagementModal from './UserManagementModal.vue'
import ChangePasswordModal from './ChangePasswordModal.vue'

const manualVersion = typeof __MANUAL_VERSION__ !== 'undefined' ? __MANUAL_VERSION__ : 'dev'
const autoVersion = typeof __AUTO_VERSION__ !== 'undefined' ? __AUTO_VERSION__ : 'dev'

const emit = defineEmits(['open', 'new', 'import'])

const files = ref([])
const openingSessionId = ref(null)  // 防止重复点击
const stealModalOpen = ref(false)
const stealingFile = ref(null)
const deleteModalOpen = ref(false)
const pendingDeleteFiles = ref([])
const selectedFiles = ref([])  // 存储选中的 file_name
const deleting = ref(false)
const newFileModalOpen = ref(false)
const newFileName = ref('')
const initialLoading = ref(true)

// ── 权限相关 ──
const authStore = useAuthStore()
const ui = useUiStore()
const showAllFiles = ref(false)  // 默认只显示当前用户拥有的文件
const contextMenuOpen = ref(false)
const contextMenuPos = ref({ x: 0, y: 0 })
const contextMenuFile = ref(null)
const transferOwnerModalOpen = ref(false)
const transferOwnerFile = ref(null)
const transferOwnerTarget = ref('')
const userList = ref([])  // 管理员获取的用户列表
const userMgmtOpen = ref(false)  // 用户管理 Modal
const changePwdOpen = ref(false)    // 修改密码 Modal
const userMenuOpen = ref(false)     // 用户下拉菜单
const logoutConfirmOpen = ref(false) // 退出确认对话框

// ── Snapshot Debug ──
const showDebug = ref(false)
const debugExpanded = ref(false)
const snapshotDebug = ref({ in_memory: [], on_disk: [] })

// ── 搜索/排序 ──
const searchQuery = ref('')
const sortField = ref('mtime')     // 默认按修改时间
const sortOrder = ref('desc')      // 默认降序（最新的在前）

const newFileInputRef = ref(null)
const importFileInput = ref(null)
const importConfirmOpen = ref(false)
const pendingImportFile = ref(null)
let wsClient = null       // FileBrowser 独立 WS 连接
const isRefreshing = ref(false)  // 手动刷新加载状态
let _loadPromise = null    // loadFiles 请求去重
let _lastErrorToast = 0    // 错误 toast 节流时间戳
let _browserFailCount = 0  // 连续断连次数（用于 offline→dead 升级）

// Escape 键关闭模态框（优先级：logoutConfirm > userMenu > transferOwnerModal > contextMenu > stealModal > deleteModal > newFileModal > importConfirm）
function handleKeydown(e) {
  if (e.key !== 'Escape') return
  if (logoutConfirmOpen.value) { logoutConfirmOpen.value = false; return }
  if (userMenuOpen.value) { userMenuOpen.value = false; return }
  if (transferOwnerModalOpen.value) { closeTransferOwnerModal(); return }
  if (contextMenuOpen.value) { contextMenuOpen.value = false; return }
  if (stealModalOpen.value) { closeStealModal(); return }
  if (deleteModalOpen.value) { closeDeleteModal(); return }
  if (newFileModalOpen.value) { closeNewFileModal(); return }
  if (importConfirmOpen.value) { importConfirmOpen.value = false; return }
}

// 计算属性：是否全选（基于当前显示的文件）
const selectAll = computed(() => {
  const unlockableFiles = displayedFiles.value.filter(f => !f.is_locked)
  return unlockableFiles.length > 0 && unlockableFiles.every(f => selectedFiles.value.includes(f.file_name))
})

// 计算属性：显示在删除弹窗中的文件列表（最多显示5个）
const displayedDeleteFiles = computed(() => {
  return pendingDeleteFiles.value.slice(0, 5)
})

// ── 搜索+排序+权限过滤后的显示列表 ──
const displayedFiles = computed(() => {
  let result = files.value

  // 0. 权限过滤：默认只显示当前用户拥有的文件
  if (!showAllFiles.value) {
    result = result.filter(f => f.owner === authStore.username)
  }

  // 1. 搜索过滤（按 file.name 包含关键字，大小写不敏感）
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    result = result.filter(f => f.name.toLowerCase().includes(q))
  }

  // 2. 排序（浅拷贝避免修改原数组）
  const field = sortField.value
  const order = sortOrder.value === 'asc' ? 1 : -1
  result = [...result].sort((a, b) => {
    let va = a[field], vb = b[field]
    if (typeof va === 'string') {
      return va.localeCompare(vb) * order
    }
    return ((va ?? 0) - (vb ?? 0)) * order
  })

  return result
})

function toggleSort(field) {
  if (sortField.value === field) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortField.value = field
    sortOrder.value = 'asc'
  }
}

function getSortIcon(field) {
  if (sortField.value !== field) return '↕'
  return sortOrder.value === 'asc' ? '↑' : '↓'
}

function loadFiles() {
  // 去重：如果有正在进行的请求，直接返回同一个 Promise
  if (_loadPromise) return _loadPromise

  _loadPromise = (async () => {
    try {
      if (!wsClient?.connected) return
      const result = await wsClient.request('get_sessions', {
        current_session_id: ''  // 文件浏览器不排除任何 session
      })
      files.value = result
      const validIds = new Set(files.value.map(f => f.file_name))
      selectedFiles.value = selectedFiles.value.filter(id => validIds.has(id))
    } catch (e) {
      // 错误 toast 节流：10 秒内最多弹一次
      const now = Date.now()
      if (now - _lastErrorToast > 10_000) {
        _lastErrorToast = now
        useUiStore().showToast(e.message, true)
      }
    } finally {
      initialLoading.value = false
      _loadPromise = null
    }
  })()

  return _loadPromise
}

async function manualRefresh() {
  if (isRefreshing.value) return
  isRefreshing.value = true
  try {
    await loadFiles()
    if (showDebug.value) await loadSnapshotDebug()
  } finally {
    isRefreshing.value = false
  }
}

function handleVisibilityChange() {
  if (!document.hidden) loadFiles()
}

async function loadSnapshotDebug() {
  if (!wsClient?.connected) return
  try {
    snapshotDebug.value = await wsClient.request('get_snapshot_debug', { session_id: '' })
  } catch (e) { /* 静默 */ }
}

// 切换单个文件的选中状态
function toggleSelectFile(file) {
  if (file.is_locked) return  // 锁定的文件不能被选中
  
  const idx = selectedFiles.value.indexOf(file.file_name)
  if (idx === -1) {
    selectedFiles.value.push(file.file_name)
  } else {
    selectedFiles.value.splice(idx, 1)
  }
}

// 全选/取消全选（基于当前显示的文件）
function toggleSelectAll() {
  if (selectAll.value) {
    // 取消全选
    selectedFiles.value = []
  } else {
    // 全选当前显示的所有未锁定文件
    selectedFiles.value = displayedFiles.value
      .filter(f => !f.is_locked)
      .map(f => f.file_name)
  }
}

// 确认删除
function confirmDelete() {
  if (selectedFiles.value.length === 0) return
  
  // 获取选中的文件对象
  pendingDeleteFiles.value = files.value.filter(f => selectedFiles.value.includes(f.file_name))
  deleteModalOpen.value = true
}

// 关闭删除弹窗
function closeDeleteModal() {
  deleteModalOpen.value = false
  pendingDeleteFiles.value = []
}

// 执行批量删除
async function executeDelete() {
  if (pendingDeleteFiles.value.length === 0) return
  
  deleting.value = true
  const ui = useUiStore()
  let successCount = 0
  let failedCount = 0
  
  try {
    for (const file of pendingDeleteFiles.value) {
      try {
        await wsClient.request('delete_file', {
          file_name: file.file_name,
          current_session_id: getSessionId() || ''
        })
        successCount++
      } catch (e) {
        console.error(`Failed to delete ${file.name}:`, e)
        failedCount++
      }
    }
    
    if (successCount > 0) {
      ui.showToast(t('toast.filesDeleted', { count: successCount }))
    }
    if (failedCount > 0) {
      ui.showToast(t('toast.deleteFailedCount', { count: failedCount }), true)
    }
    
    selectedFiles.value = []
    await loadFiles()
  } catch (e) {
    ui.showToast(t('toast.deleteFailed') + ': ' + e.message, true)
  } finally {
    deleting.value = false
    closeDeleteModal()
  }
}

async function open(file) {
  // 防止重复点击
  if (openingSessionId.value === file.file_name) return
  openingSessionId.value = file.file_name

  try {
    // 预检查：刷新文件列表获取最新锁状态和权限
    await loadFiles()
    const fresh = files.value.find(f => f.file_name === file.file_name)
    if (!fresh) {
      useUiStore().showToast(t('toast.fileLocked'), true)
      return
    }
    // 刷新后如果文件已被其他 session 锁定（且当前用户有编辑意图），拒绝打开
    if (fresh.is_locked && fresh.can_write) {
      useUiStore().showToast(t('toast.fileLocked'), true)
      return
    }
    // 使用最新数据
    emit('open', { fileName: fresh.file_name, readOnly: !fresh.can_write })
  } finally {
    openingSessionId.value = null
  }
}

function confirmSteal(file) {
  stealingFile.value = file
  stealModalOpen.value = true
}

function closeStealModal() {
  stealModalOpen.value = false
  stealingFile.value = null
}

async function executeSteal() {
  if (!stealingFile.value) return
  const targetSid = stealingFile.value.session_id || ''
  const targetFileName = stealingFile.value.name
  
  try {
    const ui = useUiStore()
    
    await wsClient.request('steal_lock', {
      target_session_id: targetSid,
      current_session_id: getSessionId() || ''
    })
    
    ui.showToast(t('toast.stealSuccess') + ': ' + targetFileName)
    closeStealModal()
    await loadFiles()
    
    const updatedFile = files.value.find(f => f.name === targetFileName)
    if (updatedFile) {
      open(updatedFile)
    }
  } catch (e) {
    const ui = useUiStore()
    ui.showToast(t('toast.stealFailed') + ': ' + e.message, true)
    closeStealModal()
  }
}

async function createNew() {
  newFileName.value = 'Untitled'
  newFileModalOpen.value = true
  nextTick(() => {
    newFileInputRef.value?.focus()
    newFileInputRef.value?.select()
  })
}

function closeNewFileModal() {
  newFileModalOpen.value = false
  newFileName.value = ''
}

function executeNewFile() {
  let name = newFileName.value.trim()
  if (name.toLowerCase().endsWith('.properties')) {
    name = name.slice(0, -11)
  }
  if (!name) {
    name = 'Untitled'
  }
  closeNewFileModal()
  emit('new', name)
}

// ── 导入功能 ──
function triggerImport() {
  if (importFileInput.value) {
    importFileInput.value.click()
  }
}

function handleImportFileSelect(event) {
  const file = event.target.files[0]
  if (!file) return

  // 重置 file input，允许重复选择同一文件
  event.target.value = ''

  const ext = file.name.split('.').pop().toLowerCase()
  const supportedFormats = ['dbc', 'properties']

  if (!supportedFormats.includes(ext)) {
    useUiStore().showToast(t('browser.importUnsupported', { ext }), true)
    return
  }

  pendingImportFile.value = { file, format: ext }
  importConfirmOpen.value = true
}

async function executeImport() {
  if (!pendingImportFile.value) return

  const { file, format } = pendingImportFile.value
  importConfirmOpen.value = false

  try {
    const content = await file.text()
    emit('import', { format, content, filename: file.name })
  } catch (e) {
    useUiStore().showToast(`导入失败: ${e.message}`, true)
  } finally {
    pendingImportFile.value = null
  }
}

function formatTime(ts) {
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

// ── 右键菜单 ──
function onFileContextMenu(event, file) {
  event.preventDefault()
  event.stopPropagation()
  contextMenuFile.value = file
  contextMenuPos.value = { x: event.clientX, y: event.clientY }
  contextMenuOpen.value = true
}

function closeContextMenu() {
  contextMenuOpen.value = false
  contextMenuFile.value = null
}

// ── 用户菜单 ──
function toggleUserMenu(e) {
  e.stopPropagation()
  userMenuOpen.value = !userMenuOpen.value
}

function closeUserMenu() {
  userMenuOpen.value = false
}

// 点击外部关闭右键菜单和用户菜单
function handleClickOutside() {
  closeContextMenu()
  closeUserMenu()
}

// ── 退出登录 ──
function requestLogout() {
  userMenuOpen.value = false
  logoutConfirmOpen.value = true
}

async function confirmLogout() {
  logoutConfirmOpen.value = false
  await authStore.logout()
  window.dispatchEvent(new CustomEvent('auth-expired'))
}

// ── 转移所有权 ──
function openTransferOwnerModal() {
  if (!contextMenuFile.value) return
  transferOwnerFile.value = contextMenuFile.value
  transferOwnerTarget.value = ''
  closeContextMenu()
  // 加载用户列表
  if (authStore.isAdmin) {
    authStore.fetchUsers().then(users => {
      userList.value = users.filter(u => u.username !== authStore.username)
    }).catch(e => {
      useUiStore().showToast('获取用户列表失败: ' + e.message, true)
    })
  }
  transferOwnerModalOpen.value = true
}

function closeTransferOwnerModal() {
  transferOwnerModalOpen.value = false
  transferOwnerFile.value = null
  transferOwnerTarget.value = ''
}

async function executeTransferOwner() {
  if (!transferOwnerFile.value || !transferOwnerTarget.value) return
  try {
    await authStore.changeFileOwner(transferOwnerFile.value.file_name || transferOwnerFile.value.name, transferOwnerTarget.value)
    useUiStore().showToast(`文件所有权已转移给 ${transferOwnerTarget.value}`)
    closeTransferOwnerModal()
    await loadFiles()
  } catch (e) {
    useUiStore().showToast('转移所有权失败: ' + e.message, true)
  }
}

// ── 接管文件（管理员将无主文件设为自己所有） ──
async function executeTakeOver() {
  if (!contextMenuFile.value) return
  const file = contextMenuFile.value
  closeContextMenu()
  try {
    await authStore.changeFileOwner(file.file_name || file.name, authStore.username)
    useUiStore().showToast(`已接管文件: ${file.name}`)
    await loadFiles()
  } catch (e) {
    useUiStore().showToast('接管文件失败: ' + e.message, true)
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  // 点击其他位置关闭右键菜单
  window.addEventListener('click', handleClickOutside)
  // 建立 FileBrowser 独立 WS 连接
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsPort = parseInt(location.port) + 1
  const wsUrl = `${protocol}//${location.hostname}:${wsPort}/ws`

  wsClient = new WsSyncClient({
    url: wsUrl,
    getSessionId: () => '',  // 服务端自动创建 session
    getToken: () => useAuthStore().token,
    onMessage: (msg) => {
      // 收到锁状态变更广播时立即刷新文件列表
      if (msg.type === 'lock_stolen' || msg.type === 'file_locked') loadFiles()
    },
    onStatusChange: (status) => {
      if (status === 'connected') {
        _browserFailCount = 0
        setConnectionStatus('connected')
        loadFiles()  // 连接成功后加载文件列表
      } else if (status === 'disconnected') {
        // 重连中：连续失败多次后升级为 dead
        _browserFailCount++
        setConnectionStatus(_browserFailCount >= 3 ? 'dead' : 'offline')
      } else if (status === 'auth_required') {
        // 4010: token 失效，清除认证并通知父组件跳转登录页
        const auth = useAuthStore()
        auth.clearAuth()
        window.dispatchEvent(new CustomEvent('auth-expired'))
      } else if (status === 'session_invalid' || status === 'permanent_failure') {
        // WS 永久断开，停止刷新并通知用户
        setConnectionStatus('dead')
        initialLoading.value = false
        useUiStore().showToast(t('toast.sessionLost'), true)
      }
    }
  })
  wsClient.connect()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('click', handleClickOutside)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  if (wsClient) {
    wsClient.disconnect()
    wsClient = null
  }
})
</script>

<style scoped>
.file-browser {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
  color: var(--text);
  overflow: hidden;
}

.brand-logo {
  font-size: 20px;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: -0.3px;
  margin-right: 16px;
}
.brand-logo span { color: var(--text); }

.browser-header {
  display: flex;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  position: relative;
  z-index: 10;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* 表格容器 */
.table-container {
  flex: 1;
  overflow: auto;
  padding: 0 24px 16px;
  position: relative;
}

.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.file-table thead {
  position: sticky;
  top: 0;
  background: var(--bg-panel);
  z-index: 1;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.file-table th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  color: var(--text-dim);
  border-bottom: 2px solid var(--border);
  white-space: nowrap;
}

.file-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.file-row {
  cursor: pointer;
  transition: background 150ms;
}
.file-row:hover {
  background: var(--bg-hover);
}
.file-row.selected {
  background: var(--bg-active);
}
.file-row.selected:hover {
  background: var(--bg-hover);
}
.file-row.locked {
  opacity: 0.6;
}

.empty-state { text-align: center; padding: 80px 24px !important; }
.empty-state-content { max-width: 360px; margin: 0 auto; }
.empty-icon { font-size: 48px; margin-bottom: 16px; }
.empty-title { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.empty-desc { color: var(--text-muted); font-size: 13px; line-height: 1.6; margin-bottom: 24px; }
.empty-btn {
  background: var(--accent); color: #fff; border: none;
  padding: 12px 32px; border-radius: var(--radius);
  font-size: 15px; font-weight: 600; cursor: pointer;
  margin-bottom: 32px;
}
.empty-btn:hover { opacity: 0.9; }
.empty-btn-secondary {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
  margin-left: 8px;
}
.empty-btn-secondary:hover {
  background: var(--bg-hover);
}
.empty-hints {
  list-style: none; padding: 0; text-align: left;
  font-size: 12px; color: var(--text-dim); line-height: 2;
}
.empty-hints li::before { content: '→ '; color: var(--accent); }

/* ── 初始加载状态 ── */
.loading-state { text-align: center; padding: 80px 24px !important; }
.loading-content { max-width: 360px; margin: 0 auto; }
.browser-spinner {
  width: 32px; height: 32px;
  border: 2px solid var(--border-light);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: browser-spin 0.8s linear infinite;
  margin: 0 auto 16px;
}
.loading-text { color: var(--text-muted); font-size: 13px; }
@keyframes browser-spin { to { transform: rotate(360deg); } }
.spin { animation: browser-spin 0.8s linear infinite; }

/* ── 正在打开的文件行 ── */
.file-row.opening {
  opacity: 0.5;
  pointer-events: none;
  transition: opacity 150ms ease;
}

/* 列宽控制 */
.col-checkbox {
  width: 40px;
  text-align: center;
}
.col-name {
  min-width: 200px;
  font-weight: 500;
}
.col-messages,
.col-signals {
  width: 80px;
  text-align: center;
}
.col-time {
  width: 180px;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 12px;
}
.col-status {
  width: 180px;
}
.col-actions {
  width: 120px;
  text-align: center;
}

.file-name-link {
  color: var(--accent);
  cursor: pointer;
}
.file-name-link:hover {
  text-decoration: underline;
}

.lock-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  background: var(--warn);
  color: #fff;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
}

.unsaved-badge {
  display: inline-block;
  padding: 2px 8px;
  background: var(--danger);
  color: #fff;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
}

.snapshot-badge {
  display: inline-block;
  padding: 2px 8px;
  background: var(--accent);
  color: #fff;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
  cursor: help;
}

.open-btn {
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 6px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  margin-left: 12px;
  font-weight: 500;
}
.open-btn:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}
.open-btn:disabled {
  border-color: var(--border);
  color: var(--text-muted);
  cursor: not-allowed;
}

.steal-btn {
  background: var(--warn);
  border: 1px solid var(--warn);
  color: #fff;
  padding: 6px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  margin-left: 12px;
  font-weight: 500;
}
.steal-btn:hover {
  opacity: 0.9;
}

/* 模态对话框样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1600;
}

.modal-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  max-width: 500px;
  width: 90%;
  box-shadow: var(--shadow);
}

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.modal-box h3 {
  margin: 0 0 12px 0;
  font-size: 18px;
  font-weight: 600;
}

.modal-box p {
  margin: 0 0 20px 0;
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.5;
}

.import-filename {
  word-break: break-all;
  margin-bottom: 16px !important;
}

.file-list-preview {
  margin: 12px 0 0 0;
  padding-left: 20px;
  font-size: 13px;
}

.file-list-preview li {
  margin: 4px 0;
  color: var(--text);
}

.more-files {
  color: var(--text-muted);
  font-style: italic;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn {
  padding: 8px 16px;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
  border: 1px solid transparent;
}

.btn-cancel {
  background: transparent;
  border-color: var(--border);
  color: var(--text);
}
.btn-cancel:hover {
  background: var(--bg-raised);
}

.btn-confirm {
  background: var(--warn);
  color: #fff;
  border-color: var(--warn);
}
.btn-confirm:hover {
  opacity: 0.9;
}

.btn-danger {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
}
.btn-danger:hover:not(:disabled) {
  opacity: 0.9;
}
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 底部版本栏 */
.browser-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 26px;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.version-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.6;
}

.new-file-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  margin-bottom: 12px;
  outline: none;
}
.new-file-input:focus {
  border-color: var(--accent);
}

/* ── 搜索/排序 ── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0;
}

.header-spacer { flex: 1; }
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-wrapper {
  position: relative;
  flex: 0 1 240px;
}

.search-input {
  width: 100%;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  outline: none;
}
.search-input:focus { border-color: var(--accent); }

.search-clear-btn {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
  padding: 2px 6px;
}
.search-clear-btn:hover { color: var(--text); }

.result-count {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.sortable { cursor: pointer; user-select: none; }
.sortable:hover { color: var(--text); }
.sort-icon { font-size: 11px; margin-left: 4px; opacity: 0.6; }

.filter-empty { padding: 48px 24px !important; }

/* ── Snapshot Debug 按钮 ── */
.debug-icon-btn {
  opacity: 0.3;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  padding: 4px;
  cursor: pointer;
  color: var(--text-muted);
  transition: opacity 150ms;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.debug-icon-btn:hover { opacity: 0.7; }
.debug-icon-btn.active { opacity: 1; border-color: var(--accent); color: var(--accent); }

.snapshot-debug {
  border-top: 1px solid var(--border);
  padding: 8px 16px;
  font-size: 12px;
  max-height: 300px;
  overflow-y: auto;
}
.debug-header {
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  font-weight: 600;
  padding: 4px 0;
}
.debug-content { padding: 8px 0; }
.debug-section { margin-bottom: 12px; }
.debug-section h4 { margin: 0 0 4px; font-size: 12px; color: var(--text-dim); }
.debug-section table { width: 100%; border-collapse: collapse; font-size: 11px; }
.debug-section th, .debug-section td {
  padding: 2px 6px; border: 1px solid var(--border); text-align: left;
}
.modified-yes { color: var(--accent); font-weight: 600; }
.debug-empty { color: var(--text-dim); font-style: italic; }

/* ── 权限相关样式 ── */
.btn-toggle-files {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-dim);
  padding: 6px 12px;
  border-radius: var(--radius);
  font-size: 12px;
  cursor: pointer;
  font-weight: 500;
  margin-right: 8px;
  transition: all 150ms;
}
.btn-toggle-files.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.btn-toggle-files:hover:not(.active) {
  background: var(--bg-hover);
}

.col-owner {
  width: 100px;
  white-space: nowrap;
}
.owner-name {
  display: inline-block;
  padding: 2px 8px;
  background: var(--bg-hover);
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-dim);
}
.no-owner {
  color: var(--text-muted);
  font-size: 11px;
}

.readonly-badge {
  display: inline-block;
  margin-left: 6px;
  font-size: 12px;
  cursor: help;
  vertical-align: middle;
}
.unowned-badge {
  display: inline-block;
  margin-left: 6px;
  font-size: 11px;
  cursor: help;
  vertical-align: middle;
  opacity: 0.5;
}

.file-row.readonly-row {
  opacity: 0.75;
}

/* 右键菜单 */
.ctx-menu {
  position: fixed;
  z-index: 2000;
  min-width: 180px;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 4px 0;
  user-select: none;
}
.ctx-item {
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text);
  transition: background 100ms;
}
.ctx-item:hover:not(.disabled) {
  background: var(--bg-hover);
}
.ctx-item.disabled {
  opacity: 0.4;
  cursor: default;
  font-size: 12px;
}

.user-menu-wrapper { position: relative; }
.user-menu-btn {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 10px; border-radius: var(--radius);
  background: var(--bg-panel); border: 1px solid var(--border);
  color: var(--text); font-size: 13px; cursor: pointer;
  transition: var(--transition);
}
.user-menu-btn:hover { background: var(--bg-hover); }
.user-menu-dropdown {
  position: absolute; top: 100%; right: 0; margin-top: 4px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius-sm); box-shadow: var(--shadow);
  z-index: 100; min-width: 160px; overflow: hidden;
}
.user-menu-header { padding: 10px 14px; }
.user-menu-name { display: block; font-size: 13px; font-weight: 600; }
.user-menu-role { display: block; font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.user-menu-divider { height: 1px; background: var(--border); margin: 4px 0; }
.user-menu-item { padding: 8px 14px; font-size: 13px; cursor: pointer; }
.user-menu-item:hover { background: var(--bg-hover); }
.user-menu-danger { color: var(--danger); }
</style>
