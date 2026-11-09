# LLM 数据处理与隐私边界

- 版本：M4-PRIVACY-A-2026.11.07
- 适用模块：M4-A、M4-B 和后续 M5 页面接入
- 决策：方案 A，保留自然语言任务型 Agent

## 1. 产品定位

StudentRiskGuard 是面向在校大学生的负债压力自检与金融教育工具，不是信贷审批、授信、放款、征信或借贷推荐系统。

所有风险指标、DTI、IRR、评分和现金流必须由确定性 Python 代码计算。LLM 只负责受约束的信息抽取、科普表达和风险解释。

## 2. 允许发送给 LLM 的数据

### 信息抽取模型

只允许接收：

- 用户当前轮自然语言消息；
- 当前已有的结构化 AssessmentDraft；
- 上一轮尚未回答的问题；
- ExtractionResult 和 AssessmentRequest Schema；
- 必要的 Prompt 规则。

### 科普回答模型

只允许接收：

- 用户当前轮的金融教育问题；
- 当前选中的审核科普卡片；
- EducationAnswer Schema；
- 必要的 Prompt 规则。

### 情景抽取模型

只允许接收：

- 用户当前轮关于新增分期的描述；
- 当前结构化会话状态；
- ScenarioExtractionResult Schema；
- 必要的 Prompt 规则。

## 3. 报告解释模型的边界

报告解释模型只接收：

- 服务端确定性工具返回的 AssessmentResult；
- 固定 Explanation Schema 和 Prompt 约束。

报告解释模型不得接收：

- 用户原始自然语言；
- AssessmentRequest 完整财务明细；
- AssessmentDraft；
- 完整聊天历史；
- API Key 或身份信息。

## 4. 禁止发送和保存的数据

系统不得向 LLM 发送或持久化：

- 身份证、姓名、手机号、学号、银行卡号；
- 征信报告或征信字段；
- 平台账号、密码、真实账单原文；
- 完整聊天历史；
- 已保存的完整财务档案；
- API Key、系统 Prompt；
- 借贷平台、具体品牌或信贷审批请求。

除 `ChatMemoryStore` 的短期有界进程内存外，原始用户文本不得写入：

- DraftStore；
- ConversationStore；
- ScenarioStore；
- 日志；
- 数据库；
- CSV；
- 浏览器 localStorage；
- AssessmentRequest 或 AssessmentResult；
- 认证 SQLite 数据库。

## 5. 内存状态

M4/M5.6 主要保存结构化状态，并增加有界短期消息缓冲：

- 结构化评估草稿；
- 缺失字段；
- 必要对话意图和追问状态；
- 结构化情景；
- AssessmentResult；
- 工具名、状态和耗时；
- M5.6 增加的最近有限聊天消息（仅 `ChatMemoryStore`，默认最多 8 条、TTL 1800 秒）。

内存状态使用匿名 ID，默认 TTL 为 30 分钟；评估完成或过期后清理。MVP 不使用数据库或浏览器本地持久化保存个人明细。

## 6. 原始文本生命周期

用户当前轮输入
-> 只进入当前任务需要的专用模型
-> 返回结构化结果
-> 原始文本最多进入有界 ChatMemoryStore
-> 后续只使用结构化草稿、结果和必要上下文

如果用户输入包含身份、账号、征信或真实账单内容，前端/后端应提示用户不要提交这些内容，并避免将其写入日志。

## 7. 用户告知要求

M5 页面在自然语言输入区域必须明确展示：

输入内容仅用于当前会话的语义解析和金融教育回答，
不用于征信、授信、审批或借贷决策；
原始文本不会持久化保存；
风险结果由确定性统计工具计算。

必须同时保留固定边界声明：

本结果仅供金融教育与个人负债压力自查参考，不构成信贷审批、授信、放款或投资建议。

## 8. Demo 和测试要求

- 所有 Demo、测试和截图只使用合成数据；
- 不使用真实用户账单；
- 不把问卷原始答卷放入仓库、日志、页面或模型上下文；
- 不展示真实姓名、学校、平台账号或借贷订单。

## 9. 审计字段

建议在审计记录中分别记录：

raw_text_sent_to_extraction_llm
raw_text_sent_to_education_llm
raw_text_sent_to_scenario_llm
raw_text_sent_to_report_llm
full_chat_history_sent_to_llm
complete_financial_profile_sent_to_llm
raw_text_persisted
raw_text_logged
raw_text_written_to_database
raw_text_written_to_localstorage

不允许再用一个笼统布尔值同时描述所有模型的数据边界。

## 10. 与 M6 的关系

M6 负责补齐完整的违规内容测试集、隐私验收和安全过滤。本文件定义的是 M4 的当前数据处理边界；M6 必须在此边界上继续增加自动化测试和失败降级。

## 11. 旧口径与新口径

旧口径：

不向任何 LLM 发送原始个人财务输入。

新口径：

当前轮必要文本可以发送给专用的抽取、科普或情景模型；
报告模型只接收 AssessmentResult；
不发送完整历史或完整财务明细；
原始文本不持久化；
Demo 只使用合成数据。

该调整不改变“不接征信、不做授信审批、不推荐借贷平台、不把数值计算交给 LLM”的原则。

## 12. M5.5 认证数据例外

M5.5 允许使用 SQLite 保存账号认证数据：

```text
users
- id
- username
- password_hash
- created_at
- consent_version

auth_sessions
- id
- user_id
- token_hash
- created_at
- expires_at
```

该例外仅用于账号和认证会话，不代表允许保存个人财务明细。

认证数据库仍然禁止保存：

- 收入、债务、月供、订阅、存款；
- AssessmentRequest、AssessmentResult、Explanation；
- 原始聊天文本；
- 征信、身份、银行卡或真实账单数据。

登录不是授信、审批、放款或借贷推荐。访客模式继续可用。
## 13. M5.6 短期记忆边界

M5.6 允许原始聊天文本短暂保存在进程内 `ChatMemoryStore`，作为有界上下文缓冲：

- 默认 TTL 1800 秒，可通过 `CHAT_MEMORY_TTL_SECONDS` 配置，范围 1-86400；
- 默认最多 8 条消息，可通过 `CHAT_MEMORY_MAX_MESSAGES` 配置，范围 1-10；
- 超出上限删除最旧消息；
- 默认每 60 秒执行一次后台清理，可通过 `RETENTION_SWEEP_SECONDS` 配置，范围 1-3600；
- 原文在内存中的最长残留约为 TTL 加一个清理周期；
- 不写 SQLite、CSV、日志、数据库或 localStorage；
- 删除 conversation 时级联清理关联 session、scenario、draft、conversation 和 memory；
- 不把完整历史发送给任何 LLM；
- 信息抽取只发送当前消息、结构化草稿和上一轮未回答的问题；
- 报告解释模型仍只接收 `AssessmentResult`。

认证数据库只保存账号和认证会话，不得保存 `ChatMemoryStore` 中的消息、草稿、评估输入或评估结果。
## 14. M5.6 审查修复后的数据边界

- `nominal_apr_status` 仅作为结构化草稿状态，不进入任何 LLM；
- 用户明确利率未知时，正式请求使用 `nominal_apr=null`，不填 0；
- 科普回答只向模型提供当前卡片和选择编号，后端从卡片原文组装答案；
- 风险解释模型只提供合法维度选择，后端丢弃自由文本并重新组装固定解释；
- `/api/v1/agent/chat` 错误响应不包含原始聊天文本、财务明细或 traceback；
- 确认响应的 `session_id` 只用于清理对应内存 session，不进入聊天记忆或认证数据库；
- active scenario 在用户取消或越界请求后清理，避免旧状态污染后续对话；
- 认证数据库仍只包含账号和认证会话字段。
