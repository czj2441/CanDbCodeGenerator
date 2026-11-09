# 信号 offset / 最小值 / 最大值物理量程校验 — 设计

> 日期：2026-11-09
> 状态：待确认

## 背景

信号的 `offset`、`min_val`、`max_val` 目前只有“是有限数字”的检查：

- `app/ws/handlers/signal_handlers.py::_validate_signal_fields` 拒绝非数字与 NaN/Infinity；
- `app/models/database.py::validate_signal` 只校验 `value_type` 与 `length` 的匹配（float=32 / double=64）；
- 数据完整性检查没有相关错误类型。

因此，一个 8 位无符号信号可以保存 `min_val=-5`、`max_val=256` 这类物理上不可表示的值，导入的 DBC 也无法在“数据错误”面板中暴露此类问题。

## 目标

用 `value_type`、`length`（以及 `factor`、`offset`）推导出信号可表示的物理量程，并校验 `min_val` / `max_val`：

1. 新增 / 编辑 / 批量编辑 / MCP 修改时，非法值被阻断并返回明确错误；
2. DBC 导入或历史文件中的非法值，通过数据完整性检查显示为数据错误；
3. 修改 `length`、`value_type`、`factor`、`offset` 导致原有 `min_val` / `max_val` 失效时，同样被检出。

## 配套功能：一键填充物理量程

在信号属性面板新增“自动计算”按钮，按当前信号的 `length`、`value_type`、`factor`、`offset` 计算 `[p_min, p_max]`，并写入 `min_val` / `max_val`。

- **位置**：`frontend/src/components/SignalPanel.vue` 的“最小值 / 最大值”一行末尾，仅选中信号时显示。
- **行为**：点击后由后端用与校验相同的 helper 计算，并**一次原子写入两个字段**（新增 WS 动作 `fit_signal_range`），避免先写 min 再写 max 的中间态被校验拒绝。
- **覆盖**：直接覆盖当前 `min_val` / `max_val`，不弹确认框；操作进入撤销栈，可撤销。
- **禁用条件**：`factor == 0` 时按钮禁用（量程退化为单点，且该状态本身已由 `factor_zero` 报错）。
- **数值精度**：写入精确的 `p_min` / `p_max`，不做四舍五入；float/double 会得到 `±3.4e38` / `±1.8e308` 量级的值。
- **计算位置**：复用后端 helper，前端不重复实现公式，避免规则漂移。

## 非目标

- 不校验 `factor` 是否合理；`factor == 0` 继续由现有 `factor_zero` 完整性错误负责。
- 不单独限制 `offset` 的上下限。`offset` 是平移量，物理值 `p(0) = offset` 必然落在可表示范围内；它只参与物理量程计算。
- 不改变 DBC 导入的成功/失败行为。导入仍保持宽松，问题通过数据错误提示。
- 不做前端输入过程的实时校验；仍由后端返回错误后 toast 提示。
- 不给批量新增面板、表格行或 MCP 增加“一键填充”；仅限当前选中信号。

## 规则

对信号 `p(raw) = raw × factor + offset`。

### 原始值范围

| value_type | length | raw_min | raw_max |
|---|---|---|---|
| `uint` | `L` | `0` | `2^L − 1` |
| `int` | `L` | `−2^(L−1)` | `2^(L−1) − 1` |
| `float` | 32 | `−FLT_MAX` | `FLT_MAX` |
| `double` | 64 | `−DBL_MAX` | `DBL_MAX` |

- `FLT_MAX = 3.4028234663852886e38`（IEEE 754 单精度最大有限值）
- `DBL_MAX = 1.7976931348623157e308`（IEEE 754 双精度最大有限值）

### 物理量程

```text
p_min = min(raw_min × factor + offset, raw_max × factor + offset)
p_max = max(raw_min × factor + offset, raw_max × factor + offset)
```

`factor < 0` 时两端自然交换。

### 判定

当且仅当以下条件满足时通过：

```text
min_val ≤ max_val
min_val ≥ p_min
max_val ≤ p_max
```

### 例外与约定

- **`min_val == 0 且 max_val == 0` 视为“未设置”**，跳过上述全部检查。
  原因：Properties/DBC 未提供 min/max 时模型都落为 `0.0`，无法与“真实范围就是 0”区分；若不跳过，offset 不为 0 的导入信号会被大量误报。
- **`factor == 0`** 时跳过量程检查（物理量程退化为单点），避免与现有 `factor_zero` 重复报错。
- **非有限值**（NaN/Infinity）：编辑路径继续由 `_validate_signal_fields` 拦截；完整性路径把非有限 `min_val` / `max_val` 报为范围错误，并把错误载荷中的值转为字符串，避免 WebSocket JSON 序列化产生非标准 `Infinity`/`NaN`。
- **`length < 1`**：量程计算返回退化区间 `(offset, offset)`；完整性检查跳过范围校验，只保留 `signal_length_zero`，避免 `int` 类型负移位崩溃。
- 整数类型精确比较；`float` / `double` 允许 `1e-6` 相对容差。原因：DBC 常把 `FLT_MAX` 写成十进制舍入值 `3.4028235E+38`，作为 float64 解析后略大于精确 `FLT_MAX`，严格比较会误报。

## 实现方案（已选定 A）

### 方案 A：规则集中 + 双层生效（采用）

- 在 `CanDatabase` 增加一个纯函数/静态方法（如 `signal_physical_range(sig)`），由 `Signal` 计算 `(p_min, p_max)`，供校验、完整性检查和“一键填充”三处复用。
- `validate_signal()`：在现有 `value_type`/`length` 检查之后追加量程校验 → 阻断新增、编辑、批量编辑、批量新增、MCP 路径。
- `_validate_single_message_integrity()`：追加非阻断错误 → 导入/历史文件可见。
- 新增 WS 动作 `fit_signal_range`：
  - 位于 `app/ws/handlers/signal_handlers.py`，返回更新后的信号；
  - 用同一 helper 计算 `p_min` / `p_max`，原子写入 `min_val` / `max_val`；
  - 复用现有 undo（`type: signal_update`）、`signal_updated` / `status_changed` 事件与 `push_data_errors()`；
  - 注册到 `app/server/lifecycle.py`，并加入 `app/ws/router.py` 的 `WRITE_OPERATIONS`。

### 未采用

- **B：只做编辑阻断**。改动小，但导入的坏数据仍然静默存在。
- **C：只做完整性提示**。编辑仍可写入坏数据，不满足“有效性检查”的预期。

## 错误结构

### 阻断错误（`validate_signal` → `HandlerError`）

| error_code | 条件 | details 关键字段 |
|---|---|---|
| `signal_min_max_invalid` | `min_val > max_val` | `field`, `min_val`, `max_val` |
| `signal_min_out_of_range` | `min_val < p_min` | `field`, `value`, `min_allowed`, `max_allowed` |
| `signal_max_out_of_range` | `max_val > p_max` | `field`, `value`, `min_allowed`, `max_allowed` |

### 完整性错误（`_validate_single_message_integrity`）

`type` 与上表 `error_code` 相同，另带 `msg_key` / `msg_id` / `msg_id_hex` / `signal_name` / `message`，沿用现有完整性错误结构。

### 前端

- `frontend/src/i18n.js`
  - `toast.validation.signal_min_max_invalid`
  - `toast.validation.signal_min_out_of_range`
  - `toast.validation.signal_max_out_of_range`
  - `dataErrors.type.*` 对应的三条中文描述
  - `panel.autoFitRange`（按钮文案 / tooltip）
- `frontend/src/components/DataErrorList.vue`
  - `ERROR_ICONS` 增加三种类型；
  - `errorDescription()` 的插值参数补充 `min_val`、`value`、`min_allowed`、`max_allowed`。
- `frontend/src/components/SignalPanel.vue`
  - 在 min/max 行末尾增加“自动计算”按钮；
  - `factor == 0` 时禁用。
- `frontend/src/stores/signals.js`
  - 新增 `fitSignalRange(sigName, msgKey)`，调用 `fit_signal_range`；失败时沿用 `translateError` + toast。
- 测试：`fit_signal_range` 写入后 `min_val == p_min`、`max_val == p_max`，并生成可撤销的 undo 快照。

## 测试

### 单元测试（`tests/test_validate_data_integrity.py` 或新增文件）

- uint8：`0/255` 通过；`-1` 与 `256` 分别报 `signal_min_out_of_range` / `signal_max_out_of_range`；
- int8：`-128/127` 通过；`-129` 与 `128` 越界；
- float32 / double64：超大值越界、边界值通过；
- `factor = 2`、`offset = 10`：物理量程随之变化，边界正确；
- `factor = -1`：端点交换后仍正确；
- `min_val > max_val` → `signal_min_max_invalid`；
- `min_val == 0 且 max_val == 0` → 无错误（即使 offset 很大）；
- `factor == 0` → 只有 `factor_zero`，没有量程错误。

### 编辑路径测试

- 修改 `max_val` 超出量程被拒绝（WS handler / MCP）；
- 修改 `length` 从 8 到 4 使原 `max_val=255` 失效，被拒绝；
- 修改 `value_type` 使原有 min/max 失效，被拒绝；
- 批量编辑中单个信号失败不中断其余信号（沿用现有批量语义）。

### 一键填充测试

- uint8、factor=0.5、offset=-10 的信号点击后写入 `min_val=-10`、`max_val=117.5`；
- int8、factor=-2、offset=0 的信号写入 `min_val=-254`、`max_val=256`（端点交换）；
- `factor == 0` 时返回错误且不修改字段；
- 填充后立刻通过 `validate_signal()`，并可通过 undo 恢复原值。

### 回归

- 现有 `tests/test_validate_data_integrity.py`、`tests/test_mcp_tools_signals.py`、`tests/test_dbc_attributes.py` 全绿。

## 影响与兼容

- 现有测试与默认数据大量使用 `min_val = max_val = 0.0`，按“未设置”约定不受影响。
- `data/ui-test-attr-ext-float.properties` 中的 `SigB`（uint8，`-5/256`）将成为可检出的非法样例。
- 已保存的非法数据不会被自动修改，只在错误面板中提示。