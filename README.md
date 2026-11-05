# StudentRiskGuard

大学生负债压力自检与理性消费科普 Agent。当前仓库已完成 M0 契约、M1 工程骨架、M2 确定性统计计算内核、M3 会话/工具/API 层和 M4 Agent 工具调用链；M5 页面闭环尚未实现。

## 当前状态

- M0：最终契约已冻结。
- M1：Pydantic 模型与 JSON Schema 对齐。
- M2：DTI、IRR、评分卡、现金流和存款缓冲已完成，五套 Demo 通过。
- M3：内存会话、ToolExecutor、确定性评估 API 已完成。
- M4：AgentRunner 两轮工作流、DeepSeek 适配、解释 JSON 和安全降级已完成。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

当前测试数量：54。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,research]"
```

Streamlit 页面骨架：

```powershell
streamlit run app.py
```

FastAPI：

```powershell
uvicorn riskguard.api.main:app --app-dir src --reload
```

打开：

```text
http://127.0.0.1:8000/docs
```

## M3 API

### 创建匿名会话

```http
POST /api/v1/sessions
```

请求体为 `AssessmentRequest`，会话只存在内存中，默认 TTL 30 分钟。

### 查看会话元数据

```http
GET /api/v1/sessions/{session_id}
```

只返回笔数、订阅数和预测期，不返回收入金额或债务明细。

### 删除会话

```http
DELETE /api/v1/sessions/{session_id}
```

### 运行确定性评估

```http
POST /api/v1/assessments
```

请求：

```json
{"session_id": "demo-s03"}
```

响应为完整 `AssessmentResult`。

### 运行 Agent 评估

```http
POST /api/v1/agent/assess
```

请求：

```json
{"session_id": "demo-s03"}
```

返回 `AgentResponse`，包含 `assessment`、`explanation` 和 `tool_activity`。真实 DeepSeek 调用需要配置 `DEEPSEEK_API_KEY`；未配置时自动返回模板降级结果。

### 工具入口

```http
POST /api/v1/tools/run_risk_assessment
```

工具参数只接受 `session_id`。

```http
GET /api/v1/tools
```

返回可供 M4 使用的工具定义。

## M2 校准产出

- `docs/23_M2研究对象与模型校准报告.docx`
- `docs/23_M2研究对象分析摘要.json`
- `docs/22_M2统计内核实现记录.md`
- `docs/24_M2输入输出与契约说明.md`
- `contracts/m2_final_contract.json`
- `src/riskguard/core/scorecard.json`

## 重新生成 M2 报告

原始问卷和 BNPL 文件不在仓库中，通过参数传入本地路径：

```powershell
python scripts/build_m2_research_report.py `
  --questionnaire "本地问卷.xlsx" `
  --bnpl "本地BNPL.csv"
```

## 边界

本工具仅用于金融教育与个人负债压力自查，不采集征信数据，不评估贷款资格，不推荐借贷产品，不提供授信或放款功能。
