# M2 评审材料

状态：**WIP，尚未通过 M0 契约对齐和回归验收，不得直接合并到生产代码。**

## 文件

- `backend_calculator.py`：搭档提供的 M2 确定性计算候选实现。
- `calibration_pipeline.py`：问卷与 BNPL 数据的评分卡校准脚本。
- `scorecard.json`：`scorecard-v2.1-fused-20261103` 派生参数。
- `m2_regression_kit.json`：S-01 至 S-05 回归输入与期望等级。
- `m2_regression_actual.json`：本地运行回归后得到的实际结果。
- `REGRESSION_REPORT.md`：当前不一致项和集成风险。

## 为什么没有放入 src/riskguard/core

当前实现尚未与冻结的 `AssessmentRequest` 和 `AssessmentResult` 完全对齐：

- 输入仍是扁平字段，而冻结契约使用嵌套 `income`。
- 结果字段名与 JSON Schema 不一致。
- 回归样本等级全部不一致。
- IRR 年化实现需要统计方向确认。

在完成修复和双方复核前，这些文件只作为评审材料保留，不能被 M3 直接引用。

## 未提交的原始数据

以下文件包含个人或第三方明细，未上传仓库：

1. `394140754_按序号_大学生负债压力自检与金融认知调查_214_214(1).xlsx`
   - SHA256：`843BE6A98E1E2E08789E30E8DD2AC4A46E8B78726B02D8BBD6A4DA7110099A4D`
   - 原因：214 份原始问卷，包含来源/IP 等元数据。
2. `Buy_Now_Pay_Later_BNPL_CreditRisk_Dataset.csv`
   - SHA256：`780CDB1EEC43519B0764059563D89258EF1D9E4CEF3B1FFDEAB9622D6976B1BD`
   - 原因：包含 `user_id`、`credit_score`、`location` 等字段，且来源/许可需单独确认。

需要复现分析时，请将原始文件放在仓库外，并通过修改 `calibration_pipeline.py` 顶部路径或另建本地配置加载。

## 本地运行

```powershell
python analysis/m2/backend_calculator.py
```

安装校准脚本依赖：

```powershell
python -m pip install -r analysis/m2/requirements-analysis.txt
```

正式合并前必须完成：

- 修复输入结构以匹配 `contracts/assessment_request.schema.json`。
- 修复输出结构以匹配 `contracts/assessment_result.schema.json`。
- 让 S-01 至 S-05 的等级回归通过。
- 由经济统计同学确认 IRR 年化、风险等级方向和订阅/存款口径。
