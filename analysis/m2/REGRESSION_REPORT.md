# M2 候选实现回归报告

- 日期：2026-11-03
- 评分卡版本：`scorecard-v2.1-fused-20261103`
- 结论：**不通过，不能合并到生产主线**

## 回归结果

| 样本 | 期望等级 | 实际等级 | 期望分数 | 实际分数 | 结果 |
|---|---|---|---:|---:|---|
| S-01 | 低风险 | 高风险 | 8 | 20 | 等级不一致 |
| S-02 | 关注 | 中风险 | 44 | 54 | 等级不一致 |
| S-03 | 中风险 | 关注 | 59 | 66 | 等级不一致 |
| S-04 | 高风险 | 低风险 | 85 | 85 | 分数一致但等级相反 |
| S-05 | 低风险 | 高风险 | - | 36 | 等级不一致 |

## 阻塞问题

### 1. 风险等级方向疑似反向

当前计算把四维风险扣分相加，分数越高应代表压力越大。但 `scorecard.json` 的等级表是：

```text
80-100：低风险
60-79：关注
40-59：中风险
0-39：高风险
```

这与风险扣分方向相反，导致 S-04 得到 85 分却被判定为低风险。

### 2. 输入结构与 M0 契约不一致

冻结契约使用：

```json
{
  "income": {
    "monthly_disposable_allowance": 2200,
    "monthly_part_time_income": 800
  }
}
```

当前 `calculate()` 读取的是：

```python
request.get("monthly_disposable_allowance")
```

因此不能直接接收 Pydantic `AssessmentRequest.model_dump()`。

### 3. 输出结构与 AssessmentResult 契约不一致

主要差异：

- `metrics.monthly_total_income` vs 契约 `income_total`
- `metrics.monthly_debt_payment` vs 契约 `monthly_payment_total`
- `metrics.total_remaining_principal` vs 契约 `remaining_debt_total`
- `metrics.dti` vs 契约 `debt_to_income_ratio`
- `irr_results[].irr_annual` vs 契约 `annualized_irr`
- `risk.dimension_scores` vs 契约 `risk.dimensions`
- `risk.major_contributors` vs 契约 `risk.top_contributors`
- 现金流缺少契约字段：`month_index`、`cumulative_surplus`
- 缺少 `assessment_id`、`request_id`
- `warnings` 是对象数组，契约要求字符串数组
- `assumptions.income_stable` vs 契约 `income_constant`

### 4. IRR 年化口径需复核

当前实现返回：

```python
round(float(r) * 12, 6)
```

冻结文档要求真实年化：

```text
(1 + r_monthly) ** 12 - 1
```

需要经济统计同学确认并修正。

## 结论

这批文件适合作为 M2 评审候选，不适合直接接入 M3 或合并到 main。修复后应重新运行 S-01 至 S-05 回归，并通过 `AssessmentResult` Schema 校验。
