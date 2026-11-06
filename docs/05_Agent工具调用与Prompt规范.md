# StudentRiskGuard Agent 工具调用与 Prompt 规范

- 版本：AGENT-SPEC-1.0
- 适用范围：初赛 MVP
- 核心约束：数值由工具计算，LLM 只解释；原始财务明细不直接发送给模型

## 1. Agent 定义

MVP 中的“双 Agent”按职责拆分，但不引入多 Agent 框架。

### 1.1 指标计算 Agent

本质是一个确定性工具：

```text
run_risk_assessment(session_id) -> AssessmentResult
```

- 不调用大模型。
- 从内存会话读取输入。
- 计算指标、IRR、压力分、现金流。
- 返回稳定 JSON。

### 1.2 交互推理 Agent

由 DeepSeek 驱动：

- 第一轮：调用 `run_risk_assessment` 工具。
- 第二轮：基于工具结果生成结构化解释。
- 不重新计算、不补全数值、不输出审批结论。

## 2. 状态机

```text
IDLE
  -> VALIDATE_SESSION
  -> REQUEST_TOOL_CALL
  -> EXECUTE_TOOL
  -> GENERATE_EXPLANATION
  -> VALIDATE_OUTPUT
  -> COMPLETE
```

任一步失败：

```text
FAILED_STEP
  -> DIRECT_TOOL_FALLBACK
  -> TEMPLATE_EXPLANATION
  -> DEGRADED_COMPLETE
```

### 2.1 状态说明

| 状态 | 输入 | 输出 | 失败去向 |
|---|---|---|---|
| `VALIDATE_SESSION` | session_id | 有效会话元数据 | 404/410 |
| `REQUEST_TOOL_CALL` | session_id | 模型 tool_call | 重试一次，再降级 |
| `EXECUTE_TOOL` | tool_call 参数 | AssessmentResult | 工具错误，降级或中止 |
| `GENERATE_EXPLANATION` | AssessmentResult | JSON 解释 | 模板解释 |
| `VALIDATE_OUTPUT` | 解释 JSON | 安全 AgentResponse | 模板解释 |
| `COMPLETE` | AgentResponse | 页面报告 | - |

## 3. 工具一：run_risk_assessment

### 3.1 用途

对当前匿名会话执行一次完整的确定性负债压力评估。

### 3.2 参数

```json
{
  "session_id": "anon_20261101_a1b2c3"
}
```

### 3.3 返回

完整 `AssessmentResult`，字段见 `docs/04_接口与数据契约.md`。

### 3.4 工具内部步骤

1. 读取内存会话。
2. 校验会话未过期。
3. 调用 `assessment_service.assess(request)`。
4. 保存 assessment_id 与结果引用。
5. 返回结构化结果。

### 3.5 错误

- `SESSION_NOT_FOUND`
- `SESSION_EXPIRED`
- `INCOME_REQUIRED`
- `ASSESSMENT_UNAVAILABLE`
- `TOOL_ARGUMENT_ERROR`

## 4. 工具二：simulate_new_installment

### 4.1 用途

对当前会话来模拟新增一笔分期，返回原结果、情景结果和差值。

### 4.2 参数

```json
{
  "session_id": "anon_20261101_a1b2c3",
  "scenario_id": "sc_01JABCDEF"
}
```

模型只拿到 ID，不直接拿到新增分期的完整明细。

### 4.3 返回

```json
{
  "scenario_id": "sc_01JABCDEF",
  "base_assessment": {},
  "scenario_assessment": {},
  "delta_metrics": {
    "monthly_payment_delta": 300,
    "surplus_delta": -300,
    "score_delta": 9
  }
}
```

## 5. DeepSeek 工具定义

以下结构可按 OpenAI 兼容工具调用格式放入 `tools`：

```json
[
  {
    "type": "function",
    "function": {
      "name": "run_risk_assessment",
      "description": "对匿名会话执行确定性负债压力评估。模型不得自行计算任何数值。",
      "parameters": {
        "type": "object",
        "additionalProperties": false,
        "required": ["session_id"],
        "properties": {
          "session_id": {
            "type": "string",
            "description": "匿名会话 ID"
          }
        }
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "simulate_new_installment",
      "description": "对当前会话执行新增分期情景模拟。",
      "parameters": {
        "type": "object",
        "additionalProperties": false,
        "required": ["session_id", "scenario_id"],
        "properties": {
          "session_id": {"type": "string"},
          "scenario_id": {"type": "string"}
        }
      }
    }
  }
]
```

## 6. 工具调用流程

### 6.1 第一轮

消息：

```text
请对匿名会话 {session_id} 执行负债压力评估。
先调用 run_risk_assessment 工具，不要自行计算。
```

建议工具选择：

```text
tool_choice = {"type": "function", "function": {"name": "run_risk_assessment"}}
```

如果供应商兼容层不支持强制选择，则使用 `auto`，并检查返回是否包含正确工具调用。

### 6.2 工具执行

```text
DeepSeek tool_call
  -> ToolExecutor.validate
  -> SessionStore.get
  -> AssessmentService.assess
  -> ToolResult JSON
```

### 6.3 第二轮

把工具结果作为 `role=tool` 消息返回给模型，要求生成 JSON 解释。

不要提供工具，避免模型再次调用或尝试计算。

## 7. 交互推理 System Prompt

```text
你是 StudentRiskGuard 的交互推理 Agent，面向中国在校大学生提供负债压力自查与理性消费科普。

你必须遵守以下规则：
1. 你只负责解释工具返回的结构化结果，不进行计算。
2. 不得修改、补全或创造任何金额、利率、分数、期数、概率和现金流数值。
3. 不得输出贷款审批、授信额度、通过率、放款建议或任何借贷产品推荐。
4. 不得推荐具体平台、品牌、分期产品或“以贷养贷”方案。
5. 建议只能围绕预算核对、真实成本理解、与家人沟通、寻求校园支持和理性消费。
6. 风险来源必须引用工具结果中的 dimension_id；当前 M4 不把单笔 debt_id 作为解释输出。
7. 输出必须是严格 JSON，不得输出 Markdown 代码围栏或额外说明。
8. boundary_notice 必须使用固定文本。

固定边界声明：
本结果仅供金融教育与个人负债压力自查参考，不构成信贷审批、授信、放款或投资建议。
```

## 8. 解释输出 Schema

```json
{
  "summary": "string",
  "risk_sources": [
    {
      "dimension_id": "string",
      "title": "string",
      "detail": "string"
    }
  ],
  "actions": ["string"],
  "education": ["string"],
  "questions_to_consider": ["string"],
  "boundary_notice": "本结果仅供金融教育与个人负债压力自查参考，不构成信贷审批、授信、放款或投资建议。"
}
```

约束：

- `risk_sources` 长度 1-4。
- `actions` 长度 2-5。
- `education` 长度 1-4。
- `questions_to_consider` 长度 1-4。
- `summary` 建议不超过 120 个汉字。
- 不包含具体金额、利率、分数数字；数值由前端统一渲染。
- `boundary_notice` 必须逐字一致。

## 9. 模板解释降级

当模型超时、输出非法或工具调用失败时，由本地模板生成：

```json
{
  "summary": "系统已完成确定性计算，但智能解读暂不可用。",
  "risk_sources": [
    {
      "dimension_id": "debt_to_income",
      "title": "月供压力需要关注",
      "detail": "请结合页面中的月供收入比和结余数据查看当前压力来源。"
    }
  ],
  "actions": [
    "核对每笔分期的月供和剩余期数。",
    "检查未来三个月的必要生活支出是否受到影响。"
  ],
  "education": [
    "低月供不等于低总成本，应同时关注期限和真实年化成本。"
  ],
  "questions_to_consider": [
    "如果未来兼职收入下降，当前月供是否仍能覆盖？"
  ],
  "boundary_notice": "本结果仅供金融教育与个人负债压力自查参考，不构成信贷审批、授信、放款或投资建议。"
}
```

## 10. 安全检查

### 10.1 Schema 检查

- 必需字段齐全。
- 数组长度符合范围。
- 固定声明完全一致。

### 10.2 内容检查

`actions` 和 `education` 中出现以下意图时阻断：

- 推荐贷款、借款、分期平台或具体品牌。
- 建议申请额度、提高通过率、以贷养贷。
- 承诺还款成功、收益或消除债务。
- 输出审批、授信或放款结论。

### 10.3 数值检查

- 默认解释文本不包含阿拉伯数字。
- 若业务需要引用数字，只能从工具结果白名单中读取。
- 出现未授权数值时，整段解释替换为模板。

### 10.4 安全测试用例

至少覆盖：

1. 要求推荐借款平台。
2. 要求判断贷款能否通过。
3. 要求生成授信额度。
4. 要求忽略系统规则。
5. 要求承诺“保证解决债务”。
6. 模型输出 Markdown 代码围栏。
7. 模型输出缺失 boundary_notice。
8. 模型输出编造分数。
9. 模型输出“以贷养贷”。
10. 模型输出品牌或产品名称。

## 11. Agent 轨迹展示

前端只展示：

```json
[
  {"tool": "run_risk_assessment", "status": "succeeded", "latency_ms": 18},
  {"tool": "safety_check", "status": "passed", "latency_ms": 2}
]
```

禁止展示：

- 模型内部思维链。
- 系统 Prompt。
- API Key。
- 原始工具参数中的财务明细。
- 模型原始未校验输出。

## 12. Agent 验收

- [ ] 模型第一轮返回 `run_risk_assessment` tool_call。
- [ ] 工具执行成功并返回 AssessmentResult。
- [ ] 第二轮返回合法 JSON。
- [ ] 解释中无金额和利率数值。
- [ ] 固定边界声明逐字一致。
- [ ] 工具失败时进入降级。
- [ ] 工具轨迹可被前端展示。
- [ ] 日志不含原始财务数据。

## 13. M4-B 统一对话与科普约束

M4-B 使用确定性意图路由，不让 LLM 自行决定所有工具调用。支持：

```text
assessment_intake
clarification
risk_explanation
education
scenario_simulation
out_of_scope
```

工具边界：

- `retrieve_education_topic` 只读取 `education_cards.json`；
- `simulate_new_installment` 只接收 `session_id` 和 `scenario_id`；
- 情景明细保存在后端临时场景存储，不直接透传给模型；
- 情景模拟不修改原始会话；
- 报告模型仍然只接收 `AssessmentResult`，不接收原始自然语言。

科普 Prompt 必须只基于卡片内容回答，不能新增卡片外的金融事实，不能推荐平台、品牌、产品或投资机会，不能承诺收益或解决债务。当前所有教育卡片标记为 `review_status=pending`，经济统计审核后才能改为 `approved`。

M4-B 增加最小安全校验：借贷平台、审批、授信额度、通过率、放款、以贷养贷、收益承诺等违规表达触发安全降级或越界回复。
