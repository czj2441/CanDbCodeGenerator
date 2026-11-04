# CanMatrix MCP 评估数据集

本目录存放 `canmatrix_mcp` MCP 服务器的评估题目与固定种子数据说明。

## 种子数据：EvalSeed.properties

评估题目全部针对同一份**固定不变**的种子数据——一个含 3 个报文、7 个信号、1 个值描述表、
1 个已知数据完整性错误的 properties 文件（`EvalSeed.properties`）。题目只要求**只读**工具，
答案不会随时间变化。

### 如何用 MCP 工具造出种子数据

用 PAT 认证连上 MCP 服务器后，执行一次 `canmatrix_import_file` 即可内联导入以下 properties
内容（`format="properties"`）。文件内的 `database.name=EvalSeed` 决定了生成的文件名
`EvalSeed.properties`；导入即落盘，之后数据不再改动。

工具调用（伪代码）：

```
canmatrix_import_file(
    file_name="EvalSeed.properties",
    format="properties",
    content=<下方 SEED_CONTENT 整段字符串>
)
```

`SEED_CONTENT`：

```properties
database.name=EvalSeed

messages.0x100.name=EngineStatus
messages.0x100.dlc=8
messages.0x100.cycle_time=100
messages.0x100.signals.EngineSpeed.name=EngineSpeed
messages.0x100.signals.EngineSpeed.start_bit=0
messages.0x100.signals.EngineSpeed.length=16
messages.0x100.signals.EngineSpeed.byte_order=intel
messages.0x100.signals.EngineSpeed.factor=0.5
messages.0x100.signals.EngineSpeed.offset=-10
messages.0x100.signals.EngineSpeed.unit=rpm
messages.0x100.signals.EngineTemp.name=EngineTemp
messages.0x100.signals.EngineTemp.start_bit=16
messages.0x100.signals.EngineTemp.length=8
messages.0x100.signals.EngineTemp.byte_order=intel
messages.0x100.signals.EngineTemp.offset=40
messages.0x100.signals.EngineTemp.unit=degC
messages.0x100.signals.EngineLoad.name=EngineLoad
messages.0x100.signals.EngineLoad.start_bit=24
messages.0x100.signals.EngineLoad.length=8
messages.0x100.signals.EngineLoad.byte_order=intel
messages.0x100.signals.EngineLoad.factor=0.01

messages.0x200.name=BodyControl
messages.0x200.dlc=8
messages.0x200.cycle_time=50
messages.0x200.signals.DoorState.name=DoorState
messages.0x200.signals.DoorState.start_bit=0
messages.0x200.signals.DoorState.length=2
messages.0x200.signals.DoorState.byte_order=intel
messages.0x200.signals.DoorState.value_table_name=Vt_DoorState
messages.0x200.signals.WindowPos.name=WindowPos
messages.0x200.signals.WindowPos.start_bit=8
messages.0x200.signals.WindowPos.length=8
messages.0x200.signals.WindowPos.byte_order=intel

messages.0x300.name=BrakeStatus
messages.0x300.dlc=8
messages.0x300.cycle_time=200
messages.0x300.signals.BrakePressure.name=BrakePressure
messages.0x300.signals.BrakePressure.start_bit=0
messages.0x300.signals.BrakePressure.length=8
messages.0x300.signals.BrakePressure.byte_order=intel
messages.0x300.signals.BrakeFault.name=BrakeFault
messages.0x300.signals.BrakeFault.start_bit=8
messages.0x300.signals.BrakeFault.length=8
messages.0x300.signals.BrakeFault.byte_order=intel
messages.0x300.signals.BrakeFault.factor=0

value_tables.Vt_DoorState={"0": "Closed", "1": "Open", "2": "Ajar"}
```

> 等价地，也可用 `canmatrix_create_file(name="EvalSeed")` 新建空文件，再依次
> `canmatrix_add_message`、`canmatrix_add_signal`、`canmatrix_add_value_table` 逐步搭建；
> 但上面一次 `canmatrix_import_file` 最可复现，推荐作为评估的标准造数方式。

### 种子数据要点（自验结论）

| 项 | 值 |
|---|---|
| 文件名 | `EvalSeed.properties` |
| 报文数 / 信号数 | 3 / 7 |
| 信号数最多的报文 | `EngineStatus`（0x100，3 个信号） |
| 数据错误 | `BrakeStatus`（0x300）中 `BrakeFault` 的 `factor=0`，type=`factor_zero` |
| 值描述表 | `Vt_DoorState` = `{"0": "Closed", "1": "Open", "2": "Ajar"}` |

## 评估题目

题目见同目录 `canmatrix_mcp_evals.xml`，格式遵循 mcp-builder 评估指南：
`<evaluation><qa_pair><question>…</question><answer>…</answer></qa_pair>…</evaluation>`。
全部为只读、单答案可字符串验证、需 ≥3 次工具调用才能得出。
