# backend_calculator.py
# StudentRiskGuard M2 后端计算引擎
# 纯 Python 计算：DTI、IRR、四维打分、现金流推演
# 不调用大模型、不读写数据库、不依赖网络

import json
import os
import math

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCORECARD_PATH = os.path.join(BASE_DIR, "scorecard.json")


# ============================================================
# IRR 计算：优先用 numpy_financial，没有则用二分法兜底
# ============================================================
def _irr_bisection(cashflows, low=-0.9999, high=10.0, tol=1e-7, max_iter=1000):
    """二分法求 IRR；现金流无解时返回 None"""
    def npv(rate):
        return sum(cf / ((1 + rate) ** i) for i, cf in enumerate(cashflows))

    f_low = npv(low)
    f_high = npv(high)

    # 端点同号，说明区间内无符号变化
    if f_low * f_high > 0:
        return None

    for _ in range(max_iter):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < tol:
            return mid
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return (low + high) / 2


def _calc_irr_annual(principal, monthly_payment, periods):
    """
    单笔分期年化 IRR：
    现金流 = [剩余本金] + [-月供] * 剩余期数
    返回 (年化IRR, 状态, 说明)
    """
    if principal <= 0 or monthly_payment <= 0 or periods <= 0:
        return None, "invalid_input", "本金/月供/期数必须大于0"

    if monthly_payment * periods < principal:
        return None, "no_solution", "月供×期数<本金，现金流无解"

    cashflows = [principal] + [-monthly_payment] * periods

    try:
        import numpy_financial as npf
        r = npf.irr(cashflows)
        if r is None or (isinstance(r, float) and math.isnan(r)):
            return None, "no_solution", "现金流无解"
    except Exception:
        r = _irr_bisection(cashflows)
        if r is None:
            return None, "no_solution", "现金流无解"

    if r <= -1:
        return None, "invalid", "IRR≤-100%"
    return round(float(r) * 12, 6), "ok", "剩余本金为分母，固定月供至期末"


# ============================================================
# 分档取分与等级映射
# ============================================================
def _score_by_bands(value, bands):
    if value is None:
        return 0
    for band in bands:
        if value < band["upper"]:
            return band["score"]
    return bands[-1]["score"]


def _level_from_score(score, levels):
    for lv in levels:
        if score >= lv["min"]:
            return lv["label"]
    return levels[-1]["label"]


# ============================================================
# 主函数
# ============================================================
def calculate(request, scorecard_path=None, borrow_to_repay=False,
              overdue_strict=False, cognitive_weak=False):
    """
    输入：
      request: AssessmentRequest 字典，字段见 M0 契约
      scorecard_path: scorecard.json 路径；默认同目录
      borrow_to_repay / overdue_strict / cognitive_weak:
        行为标签，由上层从问卷或会话补充，默认 False

    输出：
      AssessmentResult 字典
    """
    sc_path = scorecard_path or SCORECARD_PATH
    with open(sc_path, "r", encoding="utf-8") as f:
        SC = json.load(f)

    rules = SC["rules"]
    scoring = SC["risk_scoring"]
    levels = SC["risk_levels"]

    warnings = []

    # ---------- 1. 收入 ----------
    living = float(request.get("monthly_disposable_allowance", 0))
    part_time = float(request.get("monthly_part_time_income", 0))
    total_income = living + part_time

    if total_income <= 0:
        warnings.append({"code": "W-INCOME-ZERO", "message": "月总收入为0，DTI按分母1e-6处理"})
        income_denom = 1e-6
    else:
        income_denom = total_income

    # ---------- 2. 负债与订阅 ----------
    debts = request.get("debts", []) or []
    subs = request.get("recurring_subscriptions", []) or []

    debt_payment = sum(float(d["monthly_payment"]) for d in debts)
    debt_principal = sum(float(d["remaining_principal"]) for d in debts)
    sub_cost = sum(float(s["monthly_cost"]) for s in subs)
    rigid_outflow = debt_payment + sub_cost

    # ---------- 3. DTI 与结余 ----------
    dti = debt_payment / income_denom
    monthly_surplus = total_income - rigid_outflow
    surplus_rate = monthly_surplus / total_income if total_income > 0 else 0.0

    savings = float(request.get("savings_balance", 0))
    savings_runway = None
    if monthly_surplus < 0 and savings > 0:
        savings_runway = round(savings / abs(monthly_surplus), 2)

    # ---------- 4. 逐笔 IRR ----------
    irr_results = []
    max_irr = None
    for d in debts:
        irr_val, status, assumption = _calc_irr_annual(
            float(d["remaining_principal"]),
            float(d["monthly_payment"]),
            int(d["remaining_periods"])
        )
        irr_results.append({
            "id": d.get("id", ""),
            "label": d.get("label", "分期"),
            "irr_annual": irr_val,
            "status": status,
            "assumption": assumption
        })
        if irr_val is not None and (max_irr is None or irr_val > max_irr):
            max_irr = irr_val
        if status != "ok":
            warnings.append({
                "code": f"W-IRR-{status.upper()}",
                "message": f"{d.get('label','分期')} IRR计算{status}：{assumption}"
            })

    # ---------- 5. 四维打分（读 scorecard.json）----------
    dti_score = _score_by_bands(dti, scoring["dti_bands"])
    inst_score = _score_by_bands(len(debts), scoring["installment_bands"])
    irr_score = _score_by_bands(max_irr, scoring["irr_bands"]) if max_irr is not None else 0

    behavior_candidates = [scoring["behavior_scores"]["normal"]]
    if borrow_to_repay:
        behavior_candidates.append(scoring["behavior_scores"]["borrow_to_repay"])
    if overdue_strict:
        behavior_candidates.append(scoring["behavior_scores"]["overdue_strict"])
    if cognitive_weak:
        behavior_candidates.append(scoring["behavior_scores"]["cognitive_weak"])
    behavior_score = max(behavior_candidates)

    total_score = dti_score + inst_score + irr_score + behavior_score
    risk_level = _level_from_score(total_score, levels)

    # ---------- 6. 主要贡献项 ----------
    contributors = []
    if dti_score >= 24:
        contributors.append(f"DTI偏高({dti:.2%})")
    if inst_score >= 20:
        contributors.append(f"分期笔数偏多({len(debts)}笔)")
    if irr_score >= 15 and max_irr is not None:
        contributors.append(f"存在高IRR分期({max_irr:.2%})")
    if borrow_to_repay:
        contributors.append("存在以贷养贷行为")
    elif overdue_strict:
        contributors.append("存在严格逾期史")
    elif cognitive_weak:
        contributors.append("金融认知薄弱")

    # ---------- 7. 现金流推演 ----------
    forecast_months = int(request.get("forecast_months", 12))
    cashflow = []
    cumulative = 0.0
    savings_now = savings
    for m in range(1, forecast_months + 1):
        active_payment = sum(
            float(d["monthly_payment"]) for d in debts
            if m <= int(d["remaining_periods"])
        )
        month_rigid = active_payment + sub_cost
        month_surplus = total_income - month_rigid
        cumulative += month_surplus
        savings_now = max(0.0, savings_now + month_surplus)
        cashflow.append({
            "month": m,
            "income": round(total_income, 2),
            "debt_payment": round(active_payment, 2),
            "rigid_outflow": round(month_rigid, 2),
            "surplus": round(month_surplus, 2),
            "cumulative": round(cumulative, 2),
            "savings_after": round(savings_now, 2)
        })

    # ---------- 8. 阈值触发的警告（给大模型解释用）----------
    if dti >= rules["dti_ratio"]["threshold_high"]:
        warnings.append({"code": "W-DTI-HIGH", "message": f"DTI={dti:.2%}，≥50%高风险线"})
    elif dti >= rules["dti_ratio"]["threshold_warn"]:
        warnings.append({"code": "W-DTI-MID", "message": f"DTI={dti:.2%}，进入关注区间"})
    if max_irr is not None and max_irr > rules["irr_rate"]["threshold_high"]:
        warnings.append({"code": "W-IRR-REDLINE", "message": f"最高IRR={max_irr:.2%}，超过24%法定红线"})
    if monthly_surplus < 0:
        warnings.append({"code": "W-SURPLUS-NEG", "message": f"月度结余为负({monthly_surplus:.2f}元)"})

    # ---------- 9. 组装 AssessmentResult ----------
    return {
        "metrics": {
            "monthly_total_income": round(total_income, 2),
            "monthly_debt_payment": round(debt_payment, 2),
            "monthly_subscription_cost": round(sub_cost, 2),
            "monthly_rigid_outflow": round(rigid_outflow, 2),
            "total_remaining_principal": round(debt_principal, 2),
            "debt_count": len(debts),
            "dti": round(dti, 4),
            "monthly_surplus": round(monthly_surplus, 2),
            "surplus_rate": round(surplus_rate, 4),
            "savings_runway_months": savings_runway
        },
        "irr_results": irr_results,
        "risk": {
            "score": total_score,
            "level": risk_level,
            "dimension_scores": {
                "dti_risk": dti_score,
                "installment_risk": inst_score,
                "irr_risk": irr_score,
                "behavior_risk": behavior_score
            },
            "max_scores": scoring["max_scores"],
            "major_contributors": contributors
        },
        "cashflow_series": cashflow,
        "assumptions": {
            "currency": "CNY",
            "income_stable": True,
            "forecast_months": forecast_months,
            "irr_basis": "remaining_principal + fixed_monthly_payment",
            "cashflow_basis": "fixed_income_no_shock",
            "notes": [
                "收入按当前水平固定，未模拟失业/减薪",
                "订阅费计入刚性支出，不计入负债、不计算IRR",
                "存款仅用于现金流缓冲，不计入收入"
            ]
        },
        "warnings": warnings,
        "model_version": "M2-FREEZE-2026.11.03",
        "parameter_version": SC.get("version", "unknown")
    }


# ============================================================
# 自测：用 m2_regression_kit.json 跑回归
# ============================================================
if __name__ == "__main__":
    import sys

    kit_path = os.path.join(BASE_DIR, "m2_regression_kit.json")
    if not os.path.exists(kit_path):
        print(f"未找到 {kit_path}，跳过自测。")
        sys.exit(0)

    with open(kit_path, "r", encoding="utf-8") as f:
        kit = json.load(f)

    print("=" * 60)
    print("M2 后端计算引擎回归测试")
    print("=" * 60)

    all_pass = True
    for sid, case in kit["cases"].items():
        result = calculate(case["request"])
        actual_score = result["risk"]["score"]
        actual_level = result["risk"]["level"]
        expected_level = case["expected_level"]
        expected_score = case.get("expected_score_m0")

        score_ok = True if expected_score is None else abs(actual_score - expected_score) <= 5
        level_ok = actual_level == expected_level
        if not (score_ok and level_ok):
            all_pass = False

        max_irr = max((x["irr_annual"] or 0) for x in result["irr_results"]) if result["irr_results"] else 0
        print(f"\n[{sid}]")
        print(f"  DTI={result['metrics']['dti']:.2%}，笔数={result['metrics']['debt_count']}，最高IRR={max_irr:.2%}")
        print(f"  四维分数：{result['risk']['dimension_scores']}")
        print(f"  总分：{actual_score}（期望 {expected_score}）{'OK' if score_ok else 'FAIL'}")
        print(f"  等级：{actual_level}（期望 {expected_level}）{'OK' if level_ok else 'FAIL'}")

    print("\n" + "=" * 60)
    print("全部通过" if all_pass else "存在不通过项，请检查 scorecard.json 或样本数据")
    print("=" * 60)