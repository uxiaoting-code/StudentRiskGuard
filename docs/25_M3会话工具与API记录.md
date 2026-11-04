# M3 会话、工具与 API 实现记录

- 模块：M3 会话、工具与 API
- 日期：2026-11-04
- 依赖：M0 最终契约、M1 模型、M2 最终内核
- 状态：技术实现通过；经济统计人工复核待完成
- 任务：T11、T12、T13、T14

## 1. 已实现

### C-M3-1 内存 SessionStore

- `src/riskguard/services/session_store.py`
- 默认 TTL 1800 秒。
- 支持 create/get/delete/purge_expired。
- 区分 SessionNotFound、SessionExpired、SessionAlreadyExists。
- 线程安全。
- 不写数据库、不写文件。

### C-M3-2 AssessmentService

- `src/riskguard/services/assessment_service.py`
- 只调用 M2 的 `run_assessment`。
- 不复制 DTI、IRR、评分或现金流公式。
- `assess_session(session_id)` 从会话读取请求并执行 M2。

### C-M3-3 ToolExecutor

- `src/riskguard/tools/definitions.py`
- `src/riskguard/tools/executor.py`
- 工具名固定为 `run_risk_assessment`。
- 参数只接受 `session_id`。
- 额外字段和未知工具被拒绝。
- 返回完整 `AssessmentResult`。

### C-M3-4 API

- `POST /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `DELETE /api/v1/sessions/{session_id}`
- `POST /api/v1/assessments`
- `POST /api/v1/tools/run_risk_assessment`
- `GET /api/v1/tools`
- `GET /health`
- 统一错误结构：`request_id + error.code + error.message`。
- 增加 `X-Request-ID` 响应头。

### C-M3-5 测试

- `tests/test_session_store.py`
- `tests/test_tool_executor.py`
- 扩充 `tests/test_api.py`
- 覆盖 TTL、重复会话、删除、过期、未知工具、额外参数、完整结果、错误码和工具定义。

## 2. 验证结果

```text
47 passed, 1 warning
```

警告为 FastAPI TestClient 的 Starlette 弃用提示，不影响 M3 功能。

## 3. 隐私与边界

- 会话只在进程内存中。
- API 的会话元数据不返回收入和债务金额。
- 工具参数只包含 session_id。
- 原始财务明细不发送给大模型。
- M3 没有调用 DeepSeek。
- M3 没有实现 M4 的 Agent 编排、LLM 解释和安全模板。

## 4. 验收门

- [x] POST /api/v1/sessions 创建会话。
- [x] 工具只接收 session_id。
- [x] 工具返回完整 AssessmentResult。
- [x] API 测试通过。
- [ ] 经济统计同学人工复核工具输出字段。

## 5. 下一步

M4 应实现：

- DeepSeek 第一轮工具调用。
- ToolExecutor 调用链。
- 第二轮解释 JSON。
- AgentResponse 输出。
- 超时、非法输出和安全降级。
