# StudentRiskGuard

大学生负债压力自检与理性消费科普 Agent。当前仓库处于 M1 工程骨架阶段，尚未实现 M2 统计计算内核。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
```

Streamlit 页面：

```powershell
streamlit run app.py
```

FastAPI 健康检查：

```powershell
uvicorn riskguard.api.main:app --app-dir src --reload
```

打开 `http://127.0.0.1:8000/health`。

## 边界

本工具仅用于金融教育与个人负债压力自查，不采集征信数据，不评估贷款资格，不推荐借贷产品，不提供授信或放款功能。
