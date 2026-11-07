# StudentRiskGuard Repository Instructions

## What this project is

StudentRiskGuard is a debt-pressure self-check and rational-consumption education Agent for Chinese university students. It is an MVP for the MINMAX AI Agent Hackathon.

The product is not a lending, credit approval, underwriting, collection, or credit-report product.

## Read before changing code

Read in this order:

1. `StudentRiskGuard商业计划书.docx`
2. `docs/00_商业计划书开发摘要.md`
3. `docs/01_MVP开发实施方案.md`
4. `docs/02_分工与排期.md`
5. `docs/03_任务清单.csv`
6. `docs/04_接口与数据契约.md`
7. `docs/05_Agent工具调用与Prompt规范.md`
8. `docs/06_Demo与验收清单.md`
9. `docs/07_Codex交接提示词.md`
10. `docs/08_模块开发任务卡.md`
11. `docs/09_模块任务清单.csv`
12. `docs/10_提交级核心链路验收.md`
13. `docs/11_匿名问卷设计与数据收集计划.md`
14. `docs/12_问卷题目清单.csv`
15. `docs/13_问卷数据字段与评分卡映射.csv`
16. `docs/14_问卷工作任务清单.csv`
17. `docs/16_Agent开发逻辑与最小框架.md`

Only work on one module at a time. For M0-M9, use the separate computer and statistics task lanes in `docs/08_模块开发任务卡.md` and `docs/09_模块任务清单.csv`. State the module ID, role, task IDs, and changed files in the final response. Do not start the next module until the joint gate is satisfied.

## Survey and calibration rules

The economy/statistics owner must run survey track S0-S5 in parallel with M1-M3. M0 may start immediately. Before the M0 gate, only confirm that the questionnaire field mapping covers the model fields. Full questionnaire wording, publication, and survey responses are not required for M0. Do not block M1-M6 on survey collection; use the draft scorecard until calibration is ready. S4-S5 calibration/freeze must be completed before M7 deployment, or the initial parameter version must be retained with an explicit sample limitation. Survey raw responses must never enter the app repository, logs, frontend, or demo data.

## Hard constraints

- Do not collect or process credit-bureau data.
- Do not evaluate loan approval, credit limit, or lending eligibility.
- Do not recommend lenders, lending products, installment platforms, or borrowing.
- Do not persist personal financial details in the MVP.
- The report explanation model must receive only structured AssessmentResult, never raw user text.
- Current-turn user text may be sent only to the dedicated extraction, education, or scenario model needed for the current task.
- Full chat history and complete financial profiles must not be sent to any LLM.
- Raw text must not be persisted, logged, written to a database, or written to localStorage.
- All numerical results must come from deterministic Python code.
- The LLM may explain structured tool results and may perform constrained extraction, education, or scenario-extraction tasks; it must not calculate deterministic metrics.
- Demo and test data must be synthetic.
- Do not commit `.env`, API keys, real statements, or personal data.

## Required MVP chain

```text
User input
-> anonymous in-memory session
-> Agent calls run_risk_assessment(session_id)
-> deterministic calculation tool
-> structured result
-> DeepSeek explanation
-> safety validation
-> web report
```

The primary demo must show a real `run_risk_assessment` tool call. A direct deterministic fallback is allowed only as a degraded mode.

## Submission gate

Mandatory order: M0 -> (M1 computer and M2 statistics in parallel) -> M3 -> M4 -> M5 -> M6 -> M7 -> M8. M9 is optional and off the critical path.

M1 and M2 may run in parallel only after M0 passes. M3 cannot start until both M1 and M2 are complete. M7 is the first point at which the project can be called a submittable Agent; M8 only packages and freezes the submission.


M0-M7 are the mandatory submission gates. Completing M0-M7 means the project has a public, runnable Agent with the full core chain. M8 is packaging and freeze only. M9 is optional.

The core chain is not complete unless all of the following are demonstrated:

- A public URL opens the app.
- A user can submit the synthetic S-03 sample.
- The service creates an in-memory anonymous session.
- DeepSeek returns a real `run_risk_assessment` tool call.
- The deterministic tool returns a complete `AssessmentResult`.
- DeepSeek returns a schema-valid explanation without recalculating values.
- Safety checks pass or a template fallback is returned.
- The webpage shows the report.

## Architecture rules

- Streamlit is the primary MVP UI.
- FastAPI is an adapter over the same services, not a second calculation implementation.
- Pydantic v2 models define request and response contracts.
- Keep calculation logic in `src/riskguard/core/`.
- Keep session state in process memory only.
- No database, vector store, CSV persistence, or browser localStorage for personal details.
- No LangChain, CrewAI, AutoGen, or RAG in the MVP.

## File ownership

Economy/statistics owner primarily writes:

- `src/riskguard/core/`
- `src/riskguard/data/`
- `tests/test_metrics.py`
- `tests/test_irr.py`
- `tests/test_scorecard.py`
- `tests/test_cashflow.py`
- `contracts/scorecard.example.yaml`
- `contracts/scorecard.example.json`
- `contracts/demo_cases.json`

Computer owner primarily writes:

- `app.py`
- `src/riskguard/models/`
- `src/riskguard/services/`
- `src/riskguard/tools/`
- `src/riskguard/agent/`
- `src/riskguard/api/`
- `src/riskguard/ui/`
- remaining tests
- `Dockerfile`
- `.env.example`
- `README.md`

Shared contract changes require review from both owners.

## Data and field rules

- Currency: CNY.
- Rates are decimals, for example 12% is `0.12`.
- `monthly_disposable_allowance` means stable living money after necessary expenses.
- Do not add identity, credit, account, or platform-account fields.
- Reject negative amounts, zero total income, invalid periods, and malformed debt records.

## Definition of done

A task is complete only when:

- The requested files or UI exist.
- The acceptance condition in the task table is met.
- Relevant tests pass or a manual verification is documented.
- No hard constraint is violated.
- No real personal data or secret is added.
- The final response lists the task ID, changed files, commands run, test result, and open issues.

## Current state

At handoff time, this repository contains the business plan and development documents, but not the application code yet. The first implementation task should follow the dependency order in `docs/03_任务清单.csv`.

