# StudentRiskGuard Codex 交接提示词

本文用于把任务直接交给队友的 Codex。每次只让 Codex 执行明确任务，不要让它一次性重写全部项目。

## 1. 通用读文档顺序

每个 Codex 开始工作前依次阅读：

1. `StudentRiskGuard商业计划书.docx`
2. `AGENTS.md`
3. `docs/00_商业计划书开发摘要.md`
4. `docs/01_MVP开发实施方案.md`
5. `docs/02_分工与排期.md`
6. `docs/03_任务清单.csv`
7. `docs/04_接口与数据契约.md`
8. `docs/05_Agent工具调用与Prompt规范.md`
9. `docs/06_Demo与验收清单.md`
10. `docs/08_模块开发任务卡.md`
11. `docs/09_模块任务清单.csv`
12. `docs/10_提交级核心链路验收.md`
13. `docs/11_匿名问卷设计与数据收集计划.md`
14. `docs/12_问卷题目清单.csv`
15. `docs/13_问卷数据字段与评分卡映射.csv`
16. `docs/14_问卷工作任务清单.csv`
17. `docs/16_Agent开发逻辑与最小框架.md`

读完先输出：

- 本次执行的任务 ID。
- 预计修改的文件。
- 依赖项是否已满足。
- 验收命令或手工步骤。

未确认依赖前不得开始大范围改代码。

如果任务是模块级明确指令，优先按 `docs/08_模块开发任务卡.md` 执行对应 M 模块。

M0-M9 已拆成“计算机任务”和“经济统计任务”两条泳道。每次只执行一个角色、一个模块；模块联合验收门通过后才能进入下一模块。

强制顺序：M0 ->（M1 计算机与 M2 统计并行）-> M3 -> M4 -> M5 -> M6 -> M7 -> M8。M7 达到可提交 Agent 门槛，M8 只做打包，M9 可选。

问卷专项 S0-S5 由经济统计同学负责，与 M1-M3 并行；D7 前完成参数冻结或明确保留初版参数及样本限制。

## 2. 经济统计方向 Codex Prompt

```text
你是 StudentRiskGuard 项目的经济统计方向开发 Codex。

先完整阅读：
- StudentRiskGuard商业计划书.docx
- AGENTS.md
- docs/00_商业计划书开发摘要.md
- docs/01_MVP开发实施方案.md
- docs/02_分工与排期.md
- docs/03_任务清单.csv
- docs/04_接口与数据契约.md
- docs/05_Agent工具调用与Prompt规范.md
- docs/06_Demo与验收清单.md

你只负责经济统计方向写区：
- src/riskguard/core/
- src/riskguard/data/
- tests/test_metrics.py
- tests/test_irr.py
- tests/test_scorecard.py
- tests/test_cashflow.py
- contracts/scorecard.example.yaml
- contracts/demo_cases.json

本次优先执行任务 T04、T05、T06、T07、T08、T10。
要求：
1. 先检查 docs 中的接口与字段契约，不要自行改字段名。
2. 所有计算写成纯函数，不在计算公式里调用大模型。
3. 金额使用人民币元，利率使用小数。
4. 写 pytest 单元测试，覆盖正常样本和边界情况。
5. 不修改 src/riskguard/agent/、src/riskguard/ui/、src/riskguard/api/。
6. 不新增依赖，除非先说明理由。
7. 完成后运行 pytest，并报告修改文件、测试结果和未决问题。
8. 若发现契约矛盾，先停止并列出矛盾，不要擅自改契约。
```

## 3. 计算机方向 Codex Prompt

```text
你是 StudentRiskGuard 项目的计算机方向开发 Codex。

先完整阅读：
- StudentRiskGuard商业计划书.docx
- AGENTS.md
- docs/00_商业计划书开发摘要.md
- docs/01_MVP开发实施方案.md
- docs/02_分工与排期.md
- docs/03_任务清单.csv
- docs/04_接口与数据契约.md
- docs/05_Agent工具调用与Prompt规范.md
- docs/06_Demo与验收清单.md

你只负责计算机方向写区：
- app.py
- src/riskguard/models/
- src/riskguard/services/
- src/riskguard/tools/
- src/riskguard/agent/
- src/riskguard/api/
- src/riskguard/ui/
- tests/test_session_store.py
- tests/test_tool_executor.py
- tests/test_agent_runner.py
- tests/test_safety.py
- tests/test_api.py
- Dockerfile
- .env.example
- README.md

本次优先执行任务 T02、T03、T11、T12、T13、T14、T15、T16、T17。
要求：
1. 使用 Python 3.11、Streamlit、FastAPI、Pydantic v2 和 OpenAI 兼容客户端。
2. 报告解释模型不直接接收原始 `AssessmentRequest`；只接收结构化 `AssessmentResult`。自然语言抽取、科普和情景模型只接收当前轮必要文本。
3. Agent 第一轮必须尝试调用 run_risk_assessment(session_id)。
4. 工具执行后再把 AssessmentResult 交给 DeepSeek 生成解释。
5. 不引入 LangChain、CrewAI、向量数据库或复杂 RAG。
6. 模型异常必须有模板降级，页面不能空白。
7. 不写数据库，不把个人明细写入文件和日志。
8. 完成后运行 pytest 和最小启动检查，报告修改文件、运行命令、测试结果和阻塞项。
```

## 4. 联调 Codex Prompt

```text
你是 StudentRiskGuard 的联调 Codex。

先阅读：
- AGENTS.md
- docs/01_MVP开发实施方案.md
- docs/02_分工与排期.md
- docs/03_任务清单.csv
- docs/04_接口与数据契约.md
- docs/05_Agent工具调用与Prompt规范.md
- docs/06_Demo与验收清单.md

执行任务 T25、T26、T29。

要求：
1. 检查四类合成样本能否完成：输入 -> Agent 工具调用 -> 结果输出。
2. 验证 tool_activity 中存在 run_risk_assessment。
3. 验证模型故障时可降级。
4. 验证日志和存储中没有个人明细。
5. 验证页面无借贷推荐、授信结论或额度建议。
6. 只修复阻断演示的问题，不新增功能。
7. 输出一份验收报告，逐项列出通过、失败、证据和责任人。
```

## 5. 代码任务完成标准

每个 Codex 完成任务时必须返回：

```text
任务 ID：
修改文件：
实现内容：
运行命令：
测试结果：
手工验收步骤：
未决问题：
```

## 6. 禁止事项

- 不要在没有任务 ID 的情况下重构全仓库。
- 不要把真实账单、身份字段或密钥写进代码。
- 不要让 LLM 承担指标计算。
- 不要把征信、授信、放款或借贷推荐加入 MVP。
- 不要为了演示效果伪造测试结果。
- 不要在最终冻结阶段改指标权重。
