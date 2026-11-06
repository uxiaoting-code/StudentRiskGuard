# M4 Agent 工具调用链实现记录

- 模块：M4 Agent 工具调用链
- 日期：2026-11-04
- 依赖：M0 最终契约、M1 模型、M2 内核、M3 会话/工具/API
- 状态：技术实现通过；真实 DeepSeek Key 调用和统计内容审核待完成
- 任务：T15、T16、T17

## 1. 已实现

### C-M4-1 AgentRunner 状态机

- `src/riskguard/agent/runner.py`
- 先校验 session，再请求模型工具调用。
- 第一轮要求调用 `run_risk_assessment(session_id)`。
- 工具执行后进入第二轮解释。
- 解释失败进入确定性模板降级。

### C-M4-2 第一轮工具调用

- `src/riskguard/agent/prompts.py`
- 模型消息只包含 `session_id` 和任务指令。
- 不发送收入、债务、订阅、存款等原始明细。
- 强制使用 `run_risk_assessment` 工具。
- 没有 tool_call 时最多重试一次。

### C-M4-3 工具执行与解释

- `src/riskguard/agent/runner.py`
- 通过 M3 `ToolExecutor` 读取会话并调用 M2。
- 工具结果写入 `role=tool` 消息。
- 第二轮只接收结构化 `AssessmentResult`。
- 解释必须是严格 JSON，并符合 `Explanation` Pydantic 模型。

### C-M4-4 降级

- `src/riskguard/agent/fallback.py`
- 模型配置缺失、超时、无工具调用、工具异常或解释非法时，直接调用 M2 工具。
- 返回 `status=degraded`、`degraded=true` 和模板解释。
- 确定性计算结果仍可展示。

### C-M4-5 tool_activity

- 记录工具名、成功状态和耗时。
- 不暴露模型思维链、系统 Prompt、API Key 或原始工具参数。
- `/api/v1/agent/assess` 返回 `AgentResponse`。

### C-M4-6 会话绑定保护

- `src/riskguard/agent/runner.py`
- 工具参数必须且只能包含当前会话的 `session_id`；模型试图切换到其他会话时，直接降级并重新执行当前会话的确定性评估。

### DeepSeek 客户端

- `src/riskguard/agent/deepseek.py`
- 使用 `httpx` 调用 OpenAI 兼容 `/chat/completions`。
- 支持 tools、tool_choice、response_format。
- 未配置 API Key 时明确失败并进入后端降级。

## 2. 验证结果

```text
55 passed, 1 warning
```

测试覆盖：

- 假模型返回工具调用。
- 工具结果进入第二轮解释。
- 解释 JSON 合法。
- 解释不含阿拉伯数字。
- 解释只能引用实际风险维度。
- 模型不接收原始财务明细。
- 模型不能把工具调用切换到其他匿名会话。
- 无 tool_call 时降级。
- 非法解释时降级。
- DeepSeek HTTP 客户端正确发送 tools、tool_choice 和认证头。
- 未配置 API Key 时抛出明确配置错误。

真实 Uvicorn 验证（未配置 Key）：

```json
{
  "status": "degraded",
  "degraded": true,
  "risk_level": "中风险",
  "tool": "run_risk_assessment",
  "tool_status": "succeeded"
}
```

说明模型不可用时，确定性计算结果仍然可以返回。

## 3. 未完成项

- 由于当前环境没有 DeepSeek API Key，未执行真实 DeepSeek 网络调用。
- 经济统计同学尚未审核 Prompt 边界、建议范围和禁止表达。
- M6 的完整安全规则（数值白名单、违规意图测试集）尚未实现。
- M5 页面、Agent 执行状态动画和结果展示尚未实现。

## 4. 当前门禁

```text
C-M4-1：通过
C-M4-2：代码完成，真实 DeepSeek tool_call 待 Key 验证
C-M4-3：通过（假模型与契约测试）
C-M4-4：通过
C-M4-5：通过
S-M4：等待经济统计审核
联合门禁：条件通过
```

## 5. 下一步

M5 可基于当前 Agent API 开始页面开发；M4 正式验收前需要：

- 配置 `DEEPSEEK_API_KEY`。
- 用真实 DeepSeek 调用验证一次 tool_call。
- 经济统计同学审核 Prompt 和解释边界。

## 6. M4-B 增量实现

M4-B 在 M4-A 后增加：

- `src/riskguard/agent/chat.py`：统一对话编排器；
- `src/riskguard/agent/intents.py`：确定性意图路由；
- `src/riskguard/services/education_service.py`：审核卡片检索和受约束回答；
- `src/riskguard/services/scenario_service.py`：临时新增分期和 M2 重算；
- `src/riskguard/services/conversation_store.py`：结构化上下文状态；
- `src/riskguard/services/scenario_store.py`：临时情景存储；
- `retrieve_education_topic` 和 `simulate_new_installment` 工具；
- `POST /api/v1/agent/chat`。

安全边界：科普只使用卡片内容；情景模拟不修改原会话；报告模型不接收原始自然语言；违规解释降级为安全模板。真实 DeepSeek 和统计内容审核仍未完成。
