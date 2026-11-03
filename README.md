# StudentRiskGuard

大学生负债压力自检与理性消费科普 Agent。当前仓库已完成 M0 契约、M1 工程骨架和 M2 确定性统计计算内核；M3 会话、工具与 Agent API 尚未实现。

## M2 状态

M2 已实现并通过核心测试：

- DTI、月度固定支出、结余和负债规模计算。
- 逐笔月度 IRR 与有效年化计算。
- 冻结版四维专家规则评分卡：月供负债收入比 35、多头分期 15、IRR 成本 20、行为与韧性 30。
- 12 个月静态现金流与存款缓冲提示。
- 五套演示样本回归和 24 项自动化测试。
- 213 份有效问卷、10,345 条 BNPL 外部对照的统计分析与图表。

主要产出：

- `docs/23_M2研究对象与模型校准报告.docx`
- `docs/23_M2研究对象分析摘要.json`
- `docs/22_M2统计内核实现记录.md`
- `src/riskguard/core/scorecard.json`

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,research]"
pytest
```

Streamlit 页面骨架：

```powershell
streamlit run app.py
```

FastAPI 健康检查：

```powershell
uvicorn riskguard.api.main:app --app-dir src --reload
```

打开 `http://127.0.0.1:8000/health`。

## 重新生成 M2 报告

原始问卷和 BNPL 文件不在仓库中，通过参数传入本地路径：

```powershell
python scripts/build_m2_research_report.py `
  --questionnaire "本地问卷.xlsx" `
  --bnpl "本地BNPL.csv"
```

## 边界

本工具仅用于金融教育与个人负债压力自查，不采集征信数据，不评估贷款资格，不推荐借贷产品，不提供授信或放款功能。M2 参数仍是开发基线，进入最终提交前需要经济统计同学完成人工复核。
