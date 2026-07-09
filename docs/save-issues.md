# "未保存/未落盘" 语义全景分析报告

> 本报告覆盖前端、后端、前后端同步三个维度，识别出 6 大类共 15 个问题。
>
> ⚠️ 修订记录：问题 #1、#2 经代码路径复核后已降级，详见各条目的「代码路径分析」。

## 架构概览

```
浏览器/前端 ──WebSocket──→ ws_server.py (asyncio event loop 线程)
                              │
                              ▼ asyncio.to_thread()
                         ws_router.py → handlers.py (线程池线程)
                              │
                              ▼ 操作内存
                         models.py (CanDatabase, modified=True)
                              │
                              ▼ 定期/手动
                         session_manager.py → _write_file() → 磁盘 .properties
```

**持久化策略**：修改时仅存内存（`db.modified=True`），不立即落盘。依赖手动保存、5 分钟定时自动保存、atexit 保存三种机制。

**前端双标记体系**：`_localDirty`（前端乐观标记）+ `backendDirty`（后端权威状态镜像），Undo/Redo 完全由后端管理。

---

## 严重问题 (MUST FIX)

### ~~1. `_destroy()` / `release_session(abort=True)` 静默丢弃未保存数据~~ [已降级]

- **位置**：`session_manager.py` L715-L776
- **问题**：Session 销毁时不执行保存操作。但经代码路径复核，所有调用方到达此路径时数据实际上安全。
- **代码路径分析**：
  - `release_session(abort=True)` 由 `ReleaseLockHandler` 调用，前端唯一入口是 `doGoBack()`
  - `doGoBack()` 的三条触发路径均保证数据安全：
    1. `goBack()` — 已确认 `!_localDirty && !backendDirty`（无脏数据）
    2. `backAfterDiscard()` — 用户主动选择"放弃更改"
    3. `backAfterSave()` — 先执行 `saveSession()` 再调用 `doGoBack()`
  - 心跳超时清理路径会在 `_destroy()` 前调用 `save()`（见问题 #3）
- **结论**：此路径不存在数据丢失风险，降级为 P3。注释中"丢弃未保存变更"的措辞有误导性，但行为与调用方意图一致。

### ~~2. 偷取锁（Steal Lock）时不保存被偷者数据~~ [已降级]

- **位置**：`handlers.py` L765-L781，`session_manager.py` L759-L776
- **问题**：`StealLockHandler` 调用 `release_session(target_sid)` 时不保存数据。但经代码路径复核，`release_session` **未传 `abort=True`**，走的是仅释放锁的分支，不调用 `_destroy()`。数据最终通过心跳超时清理链保存。
- **代码路径分析**：
  ```
  StealLockHandler
    ├─ release_session(target_sid)           ← 只释放文件锁，不销毁 session
    ├─ fire_lock_released(target_sid)        ← 触发 lock_stolen 广播
    │
    ▼  受害者 Tab 收到 lock_stolen（editor.js L512-530）
    ├─ wsClient.disconnect()                 ← 主动断开 WS
    ├─ resetEditorState()                    ← 清理前端状态
    │
    ▼  WS handler 的 finally 块
    └─ mark_stale(session_id)                ← 心跳设为 ~10 秒后超时
         │
         ▼  ~10 秒后 _cleanup_stale_heartbeats 触发
         ├─ save(sid)                        ← 先保存未落盘数据 ✅
         └─ _destroy(sid)                    ← 再销毁 session
  ```
- **结论**：数据在 ~10 秒延迟后通过心跳清理机制保存，不存在"永久丢失"。真正的风险是 save 失败时仍销毁（归入问题 #3）。

### ~~3. 心跳超时保存失败后仍销毁 Session~~ [已修复]

- **位置**：`session_manager.py` L815-L852
- **问题**：断网/浏览器崩溃触发心跳超时清理，代码尝试保存后无论成功失败都执行 `_destroy()`。保存失败（磁盘满、文件锁定）时数据彻底丢失。
- **修复方案**：Emergency Backup — save 失败时将数据写入 `{sid}_EMERGENCY.properties` 独立备份文件，再正常销毁 session。emergency 写入也失败时打印 CRITICAL 日志（磁盘完全满等极端情况可接受丢失）。

### 4. 桌面版重启后自动保存机制失效

- **位置**：`api_server.py` L792-L808
- **问题**：`_initialized` 标志阻止了后端重启时重新注册自动保存定时器和 atexit 钩子。桌面版通过菜单"重启后端"后，所有自动安全网失效。
- **修复**：将 `_initialized` 拆分为"首次初始化"和"重启重注册"两个逻辑。

---

## 警告 (SHOULD FIX)

### 5. CRUD 操作仅修改内存 + 5 分钟自动保存间隔过长

- **位置**：`handlers.py` 全部 Handler，`api_server.py` L646
- **问题**：所有编辑操作只设 `db.modified=True`，不落盘。自动保存间隔 300 秒（5 分钟），进程崩溃时最多丢失 5 分钟编辑。Undo/Redo 也显式不保存（`session_manager.py` L502-L550）。
- **修复**：缩短间隔至 30-60 秒，或改为 CRUD 操作后 2 秒 debounce 保存。

### 6. 后端自动保存不广播 WS 事件 → 前端"幽灵脏状态"

- **位置**：`session_manager.py` L271-L295（后端），`stores/editor.js` L605（前端）
- **问题**：`save_all_dirty()` 重置 `db.modified=False` 但不发送 `status_changed` 广播。前端 `backendDirty` 保持 `true`，`_localDirty` 也不会被重置。用户关闭页面时看到错误的"未保存"警告。
- **修复**：自动保存成功后向对应 session 的 WS 连接广播 `status_changed: { modified: false, save_error: null }`。

### 7. 导入脏检查遗漏 `_localDirty`

- **位置**：`TopBar.vue` L188
- **问题**：导入文件前的脏检查只查 `backendDirty`，不查 `_localDirty`。若前端已编辑但后端 WS 尚未同步，用户可绕过脏检查直接导入。
- **修复**：改为 `if (store.backendDirty || store._localDirty)`。

### 8. Save 响应与广播的时序竞态

- **位置**：`handlers.py` L516-L533，`ws_router.py` L75-L88
- **问题**：WS dispatch 先 `reply` 再 `broadcast`。保存响应到达前端后 `_localDirty` 被重置，但 `status_changed` 广播可能尚未到达，`backendDirty` 仍为 `true`。用户立即返回文件列表时会看到错误的脏检查对话框。
- **修复**：在 `saveSession()` 收到响应后同时设置 `backendDirty = false`。

### 9. WS 事件广播先于磁盘持久化（前端误判"已保存"）

- **位置**：`ws_router.py` L75-L88
- **问题**：Handler 执行后（内存修改完成），`reply` 和 `broadcast` 都在磁盘写入之前完成。前端 UI 已反映修改，用户认为操作成功，但数据可能因后续崩溃丢失。
- **修复**：在 WS 响应中增加 `persisted: false` 标记，前端显示"保存中"过渡态。

### 10. `json_io.save_json` / `xml_io.save_xml` 非原子写入

- **位置**：`core/json_io.py` L11-L16，`core/xml_io.py` L15-L60
- **问题**：直接写入目标文件，未使用 `tmp + os.replace` 原子写入模式（与 `properties_io.py` 形成对比）。崩溃时文件可能被截断/损坏。
- **修复**：统一采用 `properties_io.py` 的 tmp + os.replace 原子写入模式。

---

## 建议 (CONSIDER)

### 11. `modified` 标志读取竞态

- **位置**：`session_manager.py` L286
- **问题**：`save_all_dirty` 无锁读取 `db.modified`，与 CRUD 操作存在微秒级竞态。被遗漏的修改需等下一个保存周期。
- **修复**：将 `modified` 检查移入 `with_lock()` 上下文，或改用 `threading.Event`。

### 12. 断线重连时 pending 请求被误判为失败

- **位置**：`ws-client.js` L238-L245
- **问题**：断线时立即 reject 所有 pending 请求，但部分请求可能已被后端处理。重连后 `full_sync` 显示操作实际成功，导致用户困惑。
- **修复**：断线时不立即 reject，标记为 "pending/unknown"，重连后对比 `data_version` 告知用户哪些操作成功了。

### 13. `_lastGeneratedMsgId` 模块级变量共享风险

- **位置**：`stores/editor.js` L134
- **问题**：非 store state 的模块级变量，快速连续新建会话时可能基于错误基线生成重复 ID。
- **修复**：移入 store state 中管理。

### 14. 浏览器标签页冻结导致锁超时释放

- **位置**：`session_manager.py` L815-L842
- **问题**：标签页休眠 > 30 秒后心跳超时，锁被释放且 session 销毁。标签页恢复后继续编辑但锁已丢失。
- **修复**：ping handler 中检查 session 存在性，不存在则发送 `lock_stolen` 通知前端。

### 15. 桌面版 `save_file` 桥接非原子写入

- **位置**：`desktop.py` L154-L168
- **问题**：`DesktopApi.save_file()` 直接 `f.write(content)`，无原子保护。
- **修复**：使用 tmp + os.replace 模式。

---

## 问题全景关联图

```
                    ┌─────────────────────┐
                    │ #5 CRUD 不写盘      │
                    │ #5 5分钟间隔过长    │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────────┐ ┌──────────┐ ┌──────────────────┐
    │#6 自动保存不广播│ │#9 WS先于 │ │ Undo/Redo       │
    │ (幽灵脏状态)    │ │ 磁盘     │ │  显式不保存      │
    └────────┬────────┘ └──────────┘ └──────────────────┘
             │
    ┌────────┼────────────────────────────────────┐
    ▼        ▼                                    ▼
┌─────────┐ ┌──────────────┐  ┌──────────────────────┐
│#1 destroy│ │#3 心跳超时   │  │#4 桌面版重启         │
│ (安全路径)│ │ 保存失败     │  │  自动保存失效        │
│ [已降级] │ │ ← 核心汇聚点│  └──────────────────────┘
└─────────┘ └──────────────┘
                 ▲
                 │ ~10秒后走此路径
┌──────────────┐ │
│#2 偷锁       │─┘
│ (最终会保存) │
│ [已降级]     │
└──────────────┘
```

---

## 已正确实现的机制

| 机制 | 说明 |
|------|------|
| `sessionStorage` 标签页隔离 | 每个标签页独立 session_id，避免跨标签页状态污染 |
| 文件锁防并发编辑 | 同一文件同一时间只有一个标签页可以编辑 |
| `full_sync` 重连恢复 | 断线重连时发送权威状态完整同步 |
| 版本号排序 | `data_version` 单调递增，丢弃过期消息 |
| 无乐观更新 | 等待服务器确认后才更新 UI，简化错误处理 |
| Steal Lock 受害者通知 | `broadcast_all` 发送 `lock_stolen` 通知被偷标签页 |

---

## 修复优先级建议

| 优先级 | 编号 | 核心问题 | 影响 |
|--------|------|----------|------|
| ~~P0~~ | ~~#3~~ | ~~心跳超时保存失败仍销毁~~ | **已修复**：Emergency Backup 写入独立备份文件 |
| P1 | #4 | 桌面版重启自动保存失效 | 数据永久丢失 |
| P1 | #5 | 5 分钟间隔过长 | 最多丢失 5 分钟 |
| P1 | #16 | backAfterSave 保存失败仍返回（见下方补充） | 数据永久丢失 |
| P2 | #6 | 幽灵脏状态 | UX 误报 |
| P2 | #8 | Save 响应时序竞态 | 短暂误报 |
| P2 | #2 | 偷锁后 ~10 秒内若进程崩溃数据丢失（边缘） | 边缘数据丢失 |
| P3 | #1 | destroy 不保存（所有调用方数据已安全） | 无实际风险 |
| P3 | #7, #9-#15 | 其余问题 | 边缘场景/体验优化 |

---

## 补充问题：backAfterSave 保存失败仍返回 [已修复]

- **位置**：`App.vue` L171-175（修复前）
- **问题**：用户在"未保存确认对话框"中选择"保存并返回"，但如果保存失败（磁盘满等），代码仍然执行 `doGoBack()` → `releaseSession(abort: true)` → `_destroy()`。用户以为数据已保存，实际数据丢失。
- **修复方案**：
  1. `backAfterSave()` 检查 `saveSession()` 返回值，失败时中止返回
  2. 弹出保存失败警告对话框，提供"继续编辑"和"导出备份"两个选项
  3. "导出备份"通过 `trigger-export` CustomEvent 触发 TopBar 的 `exportFile()` 逻辑
- **涉及文件**：`App.vue`（修复 + 对话框）、`i18n.js`（文案）、`TopBar.vue`（事件监听）
