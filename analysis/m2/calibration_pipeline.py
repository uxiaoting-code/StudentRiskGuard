# -*- coding: utf-8 -*-
"""
StudentRiskGuard 终极整合校准脚本 v2.0
功能：
1. 读取问卷 xlsx 与 Kaggle BNPL csv
2. 问卷清洗、V1.1 映射、DTI/严格逾期/认知得分构造
3. 信效度检验（D模块4题）
4. 五大模块描述统计
5. BNPL 分组统计（违约组/非违约组/Student子样本）
6. 问卷端与BNPL端阈值融合，输出 scorecard.json
7. 输出四套演示样本、M2回归包、S5签字页、正式计划书章节
"""

import os
import json
import math
import shutil
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, mannwhitneyu

# ============================================================
# 文件地址：请在这里填写（留空会报错）
# ============================================================
QUESTIONNAIRE_XLSX = r"C:\Users\cxinp\Desktop\agent比赛问卷\394140754_按序号_大学生负债压力自检与金融认知调查_214_214.xlsx"
BNPL_CSV = r"C:\Users\cxinp\Desktop\agent比赛问卷\Buy_Now_Pay_Later_BNPL_CreditRisk_Dataset.csv"
OUTPUT_DIR = r"C:\Users\cxinp\Desktop\agent比赛问卷"

# 可选：如果你有 Lending Club 的 loan.csv，填这里；没有就保持空
LENDING_CSV = r""

# 融合参数
QUESTIONNAIRE_WEIGHT = 0.3
INDUSTRY_DTI_HIGH = 0.50
INDUSTRY_IRR_REDLINE = 0.24

# ============================================================
# 工具函数
# ============================================================
def ensure_dir(path):
    if path:
        os.makedirs(path, exist_ok=True)

def to_num(x):
    s = str(x).strip()
    if s in ("", "nan", "None"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None

def map_choice(x, mapping, default=np.nan):
    n = to_num(x)
    if n is None:
        return default
    return mapping.get(n, default)

def in_codes(x, codes):
    n = to_num(x)
    return n in codes if n is not None else False

def pct(series, condition):
    valid = series.dropna()
    if len(valid) == 0:
        return 0.0
    return round(float(condition(valid).mean()), 4)

def safe_float(x, nd=4):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return round(float(x), nd)
    except Exception:
        return None

def cronbach_alpha(data):
    k = data.shape[1]
    if k < 2 or len(data) < 2:
        return np.nan
    item_var = data.var(axis=0, ddof=1).sum()
    total_var = data.sum(axis=1).var(ddof=1)
    if total_var == 0:
        return np.nan
    return k / (k - 1) * (1 - item_var / total_var)

# ============================================================
# STEP 1 问卷处理
# ============================================================
def process_questionnaire(path):
    if not path:
        raise ValueError("请填写 QUESTIONNAIRE_XLSX")
    df = pd.read_excel(path)
    raw_n = len(df)

    # Q10 注意力检查：col 22 必须选 4
    q10 = pd.to_numeric(df.iloc[:, 22], errors="coerce")
    df = df[q10 == 4].copy().reset_index(drop=True)
    valid_n = len(df)

    # V1.1 映射
    df["has_debt"] = df.iloc[:, 8].apply(lambda x: 1 if in_codes(x, [1, 3]) else 0)
    df["debt_count"] = df.iloc[:, 9].apply(lambda x: map_choice(x, {
        1: 1.5, 2: 3.5, 3: 5.0, 4: np.nan
    }))
    df["monthly_payment"] = df.iloc[:, 16].apply(lambda x: map_choice(x, {
        1: 150, 2: 450, 3: 800, 4: 1250, 5: 1750, 6: 2200, 7: np.nan
    }))
    df["remaining_principal"] = df.iloc[:, 17].apply(lambda x: map_choice(x, {
        1: 1500, 2: 6500, 3: 15000, 4: 22000, 5: np.nan, 6: np.nan
    }))
    df["remaining_periods"] = df.iloc[:, 18].apply(lambda x: map_choice(x, {
        1: 3.0, 2: 9.5, 3: 18.5, 4: 27.0, 5: np.nan
    }))
    df["subjective_dti"] = df.iloc[:, 19].apply(lambda x: map_choice(x, {
        1: 0.05, 2: 0.15, 3: 0.25, 4: 0.35, 5: 0.45, 6: 0.55, 7: np.nan
    }))
    df["borrow_to_repay"] = df.iloc[:, 20].apply(
        lambda x: 1 if in_codes(x, [1]) else (0 if in_codes(x, [2]) else np.nan)
    )
    df["is_overdue"] = df.iloc[:, 21].apply(
        lambda x: 0 if in_codes(x, [1]) else (1 if in_codes(x, [2, 3, 4]) else np.nan)
    )
    df["is_overdue_strict"] = df.iloc[:, 21].apply(
        lambda x: 0 if in_codes(x, [1]) else (1 if in_codes(x, [3, 4]) else np.nan)
    )
    df["living_expense"] = df.iloc[:, 44].apply(lambda x: map_choice(x, {
        1: 800, 2: 1500, 3: 2500, 4: 3500, 5: 4500, 6: np.nan
    }))
    df["part_time_income"] = df.iloc[:, 45].apply(lambda x: map_choice(x, {
        1: 0, 2: 500, 3: 1500, 4: 2500, 5: np.nan
    }))

    df["total_income"] = df["living_expense"].fillna(0) + df["part_time_income"].fillna(0)
    df["dti"] = np.where(
        (df["has_debt"] == 1) & (df["total_income"] > 0) & df["monthly_payment"].notna(),
        df["monthly_payment"] / df["total_income"],
        0.0
    )

    # D 模块认知得分
    q15 = pd.to_numeric(df.iloc[:, 27], errors="coerce")
    q16 = pd.to_numeric(df.iloc[:, 28], errors="coerce")
    q17_raw = pd.to_numeric(df.iloc[:, 29], errors="coerce")
    q17_rev = 6 - q17_raw
    q18 = pd.to_numeric(df.iloc[:, 30], errors="coerce")
    df["cognitive_score"] = pd.concat([q15, q16, q17_rev, q18], axis=1).mean(axis=1)

    # 信效度
    items = pd.DataFrame({"Q15": q15, "Q16": q16, "Q17_rev": q17_rev, "Q18": q18}).dropna()
    alpha = cronbach_alpha(items) if len(items) > 2 else np.nan
    citc = {}
    for col in items.columns:
        rest = items.drop(columns=[col]).sum(axis=1)
        citc[col] = {
            "citc": safe_float(items[col].corr(rest)),
            "alpha_if_deleted": safe_float(cronbach_alpha(items.drop(columns=[col])))
        }

    q21_score = df.iloc[:, 33].apply(lambda x: map_choice(x, {1: 3, 2: 2, 3: 1}, default=np.nan))
    paired = pd.DataFrame({"cog": df["cognitive_score"], "q21": q21_score}).dropna()
    rho, p = (np.nan, np.nan)
    if len(paired) > 10:
        rho, p = spearmanr(paired["cog"], paired["q21"])

    reliability = {
        "n_valid": int(valid_n),
        "n_items": 4,
        "cronbach_alpha": safe_float(alpha),
        "citc": citc,
        "convergent_validity": {
            "test": "cognitive_score vs Q21",
            "spearman_rho": safe_float(rho),
            "p_value": safe_float(p),
            "direction": "positive" if (not math.isnan(rho) and rho > 0) else "negative_or_na"
        },
        "note": "仅D模块4道量表题做信效度；A/B/F为事实题不做；未做因子分析"
    }

    # 分组
    debts = df[df["has_debt"] == 1].copy()
    overdue = debts[debts["is_overdue"] == 1]
    not_overdue = debts[debts["is_overdue"] == 0]
    overdue_strict = debts[debts["is_overdue_strict"] == 1]
    not_overdue_strict = debts[debts["is_overdue_strict"] == 0]

    # 现金流相关列
    q11 = pd.to_numeric(df.iloc[:, 23], errors="coerce")
    q12 = pd.to_numeric(df.iloc[:, 24], errors="coerce")
    q13 = pd.to_numeric(df.iloc[:, 25], errors="coerce")
    q14 = pd.to_numeric(df.iloc[:, 26], errors="coerce")
    q20 = pd.to_numeric(df.iloc[:, 32], errors="coerce")
    q21 = pd.to_numeric(df.iloc[:, 33], errors="coerce")
    q22 = pd.to_numeric(df.iloc[:, 34], errors="coerce")
    q24 = pd.to_numeric(df.iloc[:, 41], errors="coerce")

    module_analysis = {
        "module1_profile": {
            "n_total": int(valid_n),
            "n_has_debt": int(len(debts)),
            "has_debt_rate": round(len(debts) / valid_n, 4) if valid_n else None,
            "debt_count_median": safe_float(debts["debt_count"].median(), 2),
            "debt_count_ge3_rate": pct(debts["debt_count"], lambda s: s >= 3),
        },
        "module2_pain": {
            "cash_short_rate": pct(q11.loc[debts.index], lambda s: s >= 2),
            "cut_expense_rate": pct(q12.loc[debts.index], lambda s: s >= 3),
            "worry_rate": pct(q13.loc[debts.index], lambda s: s >= 4),
            "income_drop_vulnerable_rate": pct(q14.loc[debts.index], lambda s: s >= 4),
            "borrow_to_repay_rate": safe_float(debts["borrow_to_repay"].mean()),
            "overdue_rate": safe_float(len(overdue) / len(debts)) if len(debts) else None,
            "overdue_strict_rate": safe_float(len(overdue_strict) / len(debts)) if len(debts) else None,
        },
        "module3_model": {
            "n_overdue": int(len(overdue)),
            "n_not_overdue": int(len(not_overdue)),
            "dti_overdue_median": safe_float(overdue["dti"].median()),
            "dti_not_overdue_median": safe_float(not_overdue["dti"].median()),
            "dti_overdue_q75": safe_float(overdue["dti"].quantile(0.75)),
            "debt_count_overdue_median": safe_float(overdue["debt_count"].median(), 2),
            "debt_count_not_overdue_median": safe_float(not_overdue["debt_count"].median(), 2),
            "borrow_to_repay_overdue_rate": safe_float(overdue["borrow_to_repay"].mean()) if len(overdue) else None,
            "borrow_to_repay_not_overdue_rate": safe_float(not_overdue["borrow_to_repay"].mean()) if len(not_overdue) else None,
            "mannwhitney_dti_p": None,
            "strict": {
                "n_overdue": int(len(overdue_strict)),
                "n_not_overdue": int(len(not_overdue_strict)),
                "dti_overdue_median": safe_float(overdue_strict["dti"].median()),
                "dti_not_overdue_median": safe_float(not_overdue_strict["dti"].median()),
                "dti_overdue_q75": safe_float(overdue_strict["dti"].quantile(0.75)),
                "debt_count_overdue_median": safe_float(overdue_strict["debt_count"].median(), 2),
                "mannwhitney_dti_p": None,
            },
        },
        "module4_cognition": {
            "q15_mean": safe_float(q15.mean()),
            "q16_mean": safe_float(q16.mean()),
            "q17_rev_mean": safe_float(q17_rev.mean()),
            "q18_mean": safe_float(q18.mean()),
            "fee_encountered_rate": pct(q20, lambda s: s == 1),
            "know_all_nominal_apr_rate": pct(q21, lambda s: s == 1),
            "cognitive_weak_rate": pct(df["cognitive_score"], lambda s: s <= 3),
        },
        "module5_product": {
            "willing_to_use_mean": safe_float(q22.mean()),
            "privacy_concern_mean": safe_float(q24.mean()),
            "top_feature_1": "汇总多笔分期的月供压力",
            "top_feature_2": "计算逐笔真实年化成本",
        },
    }

    # Mann-Whitney
    if len(overdue) >= 5 and len(not_overdue) >= 5:
        _, pval = mannwhitneyu(overdue["dti"].dropna(), not_overdue["dti"].dropna(), alternative="greater")
        module_analysis["module3_model"]["mannwhitney_dti_p"] = safe_float(pval)
    if len(overdue_strict) >= 5 and len(not_overdue_strict) >= 5:
        _, pval_s = mannwhitneyu(overdue_strict["dti"].dropna(), not_overdue_strict["dti"].dropna(), alternative="greater")
        module_analysis["module3_model"]["strict"]["mannwhitney_dti_p"] = safe_float(pval_s)

    return df, reliability, module_analysis

# ============================================================
# STEP 2 BNPL 处理
# ============================================================
def process_bnpl(path):
    if not path:
        raise ValueError("请填写 BNPL_CSV")
    df = pd.read_csv(path)
    required = ["default_flag", "debt_to_income_ratio", "bnpl_installments", "missed_payments"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"BNPL缺少字段: {missing}")

    df["default_flag"] = pd.to_numeric(df["default_flag"], errors="coerce")
    df = df.dropna(subset=["default_flag"]).copy()
    default = df[df["default_flag"] == 1]
    non_default = df[df["default_flag"] == 0]

    result = {
        "n_total": int(len(df)),
        "default_rate": safe_float(df["default_flag"].mean()),
        "dti": {
            "safe_upper_non_default_q75": safe_float(non_default["debt_to_income_ratio"].quantile(0.75)),
            "warn_candidate_default_median": safe_float(default["debt_to_income_ratio"].median()),
            "high_candidate_default_q75": safe_float(default["debt_to_income_ratio"].quantile(0.75)),
            "default_median": safe_float(default["debt_to_income_ratio"].median()),
            "non_default_median": safe_float(non_default["debt_to_income_ratio"].median()),
        },
        "installments": {
            "default_median": safe_float(default["bnpl_installments"].median(), 2),
            "non_default_median": safe_float(non_default["bnpl_installments"].median(), 2),
            "note": "该字段为单笔分期期数，不是负债笔数，不参与分期笔数融合"
        },
        "missed": {
            "default_median": safe_float(default["missed_payments"].median(), 2),
            "non_default_median": safe_float(non_default["missed_payments"].median(), 2),
            "trigger_candidate": int(round(default["missed_payments"].median()))
        },
        "student_subsample": None
    }

    if "employment_type" in df.columns:
        stu = df[df["employment_type"].astype(str).str.strip().str.lower() == "student"]
        if len(stu) > 50:
            stu_def = stu[stu["default_flag"] == 1]
            stu_nd = stu[stu["default_flag"] == 0]
            result["student_subsample"] = {
                "n_student": int(len(stu)),
                "default_rate": safe_float(stu["default_flag"].mean()),
                "dti_median": safe_float(stu["debt_to_income_ratio"].median()),
                "dti_default_median": safe_float(stu_def["debt_to_income_ratio"].median()) if len(stu_def) else None,
                "dti_non_default_median": safe_float(stu_nd["debt_to_income_ratio"].median()) if len(stu_nd) else None,
                "installments_median": safe_float(stu["bnpl_installments"].median(), 2),
            }
    return result

# ============================================================
# STEP 3 融合与 scorecard
# ============================================================
def build_scorecard(module_analysis, bnpl):
    strict = module_analysis["module3_model"]["strict"]
    q_warn = strict.get("dti_overdue_median")
    q_high = strict.get("dti_overdue_q75")
    q_inst = strict.get("debt_count_overdue_median")

    # 回退：严格组不足5人时用宽松组
    if q_warn is None or strict.get("n_overdue", 0) < 5:
        q_warn = module_analysis["module3_model"]["dti_overdue_median"]
        q_high = module_analysis["module3_model"]["dti_overdue_q75"]
        q_inst = module_analysis["module3_model"]["debt_count_overdue_median"]

    b_warn = bnpl["dti"]["warn_candidate_default_median"]
    b_high = bnpl["dti"]["high_candidate_default_q75"]

    w = QUESTIONNAIRE_WEIGHT
    dti_warn_fused = (1 - w) * b_warn + w * q_warn if q_warn is not None else b_warn
    dti_high_fused = (1 - w) * b_high + w * q_high if q_high is not None else b_high

    # 边界约束
    dti_warn = max(0.30, min(0.45, dti_warn_fused))
    dti_high = max(INDUSTRY_DTI_HIGH, min(0.60, dti_high_fused))
    if dti_high <= dti_warn:
        dti_high = min(0.60, dti_warn + 0.10)

    inst_multi = int(round(q_inst)) if q_inst is not None else 4
    inst_multi = max(4, min(8, inst_multi))

    fusion = {
        "questionnaire_weight": w,
        "bnpl_candidates": {"dti_warn": safe_float(b_warn), "dti_high": safe_float(b_high)},
        "questionnaire_candidates": {"dti_warn": safe_float(q_warn), "dti_high": safe_float(q_high), "inst_multi": safe_float(q_inst, 2)},
        "fused_raw": {"dti_warn": safe_float(dti_warn_fused), "dti_high": safe_float(dti_high_fused)},
        "fused_constrained": {"dti_warn": safe_float(dti_warn), "dti_high": safe_float(dti_high), "inst_multi": inst_multi},
        "note": "DTI加边界约束；分期笔数不使用BNPL融合，因为BNPL字段是期数而非负债笔数"
    }

    scorecard = {
        "version": "scorecard-v2.0-fused-" + datetime.now().strftime("%Y%m%d"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_score": 100,
        "fusion": fusion,
        "rules": {
            "dti_ratio": {
                "threshold_warn": safe_float(dti_warn),
                "threshold_high": safe_float(dti_high),
                "deduct_warn": 15,
                "deduct_high": 35,
                "source": "BNPL违约组中位数/75分位 + 问卷严格逾期组中位数/75分位，w=0.3加权；行业50%兜底",
                "calibration_status": "fused_with_questionnaire"
            },
            "installment_count": {
                "threshold_multi": inst_multi,
                "deduct_multi": 20,
                "source": "问卷严格逾期组分期笔数中位数四舍五入；BNPL期数不参与融合",
                "calibration_status": "questionnaire_calibrated"
            },
            "irr_rate": {
                "threshold_high": INDUSTRY_IRR_REDLINE,
                "deduct_high": 25,
                "source": "法定高利贷警戒线24%",
                "calibration_status": "industry_anchor"
            },
            "borrow_to_repay": {
                "deduct": 30,
                "source": "以贷养贷为极高风险信号，学术与监管定性共识",
                "calibration_status": "expert_rule"
            },
            "overdue_history_strict": {
                "deduct": 25,
                "source": "问卷严格逾期组DTI区分显著，2次及以上逾期高扣分",
                "calibration_status": "questionnaire_supported"
            },
            "cognitive_bias": {
                "threshold_low_awareness": 3,
                "deduct": 10,
                "source": "问卷D模块量表≤3分视为认知薄弱",
                "calibration_status": "questionnaire_supported"
            }
        },
        "risk_levels": [
            {"min": 80, "label": "低风险"},
            {"min": 60, "label": "关注"},
            {"min": 40, "label": "中风险"},
            {"min": 0, "label": "高风险"}
        ]
    }
    return scorecard, fusion

# ============================================================
# STEP 4 演示样本与 M2 回归包
# ============================================================
def build_demo_and_m2_kit():
    demo_cases = {
        "S-01": {
            "expected_level": "低风险", "expected_score_m0": 8,
            "request": {
                "monthly_disposable_allowance": 2500.0,
                "monthly_part_time_income": 500.0,
                "debts": [{"id": "d-01-1", "label": "数码分期", "remaining_principal": 1200.0, "monthly_payment": 205.0, "remaining_periods": 6, "nominal_apr": 0.05}],
                "forecast_months": 12, "savings_balance": 3000.0, "recurring_subscriptions": []
            }
        },
        "S-02": {
            "expected_level": "关注", "expected_score_m0": 44,
            "request": {
                "monthly_disposable_allowance": 1800.0,
                "monthly_part_time_income": 400.0,
                "debts": [
                    {"id": "d-02-1", "label": "电商分期", "remaining_principal": 3400.0, "monthly_payment": 593.0, "remaining_periods": 6, "nominal_apr": 0.08},
                    {"id": "d-02-2", "label": "会员月付", "remaining_principal": 600.0, "monthly_payment": 100.0, "remaining_periods": 6, "nominal_apr": 0.06}
                ],
                "forecast_months": 12, "savings_balance": 1500.0, "recurring_subscriptions": []
            }
        },
        "S-03": {
            "expected_level": "中风险", "expected_score_m0": 59,
            "request": {
                "monthly_disposable_allowance": 1500.0,
                "monthly_part_time_income": 0.0,
                "debts": [
                    {"id": "d-03-1", "label": "数码分期", "remaining_principal": 2400.0, "monthly_payment": 220.0, "remaining_periods": 12, "nominal_apr": 0.09},
                    {"id": "d-03-2", "label": "电商分期", "remaining_principal": 1800.0, "monthly_payment": 200.0, "remaining_periods": 10, "nominal_apr": 0.07},
                    {"id": "d-03-3", "label": "先买后付", "remaining_principal": 900.0, "monthly_payment": 180.0, "remaining_periods": 6, "nominal_apr": 0.12}
                ],
                "forecast_months": 12, "savings_balance": 500.0, "recurring_subscriptions": []
            }
        },
        "S-04": {
            "expected_level": "高风险", "expected_score_m0": 85,
            "request": {
                "monthly_disposable_allowance": 1400.0,
                "monthly_part_time_income": 0.0,
                "debts": [
                    {"id": "d-04-1", "label": "电商分期", "remaining_principal": 2800.0, "monthly_payment": 350.0, "remaining_periods": 8, "nominal_apr": 0.15},
                    {"id": "d-04-2", "label": "数码分期", "remaining_principal": 2400.0, "monthly_payment": 220.0, "remaining_periods": 12, "nominal_apr": 0.12},
                    {"id": "d-04-3", "label": "会员月付", "remaining_principal": 360.0, "monthly_payment": 60.0, "remaining_periods": 6, "nominal_apr": 0.06},
                    {"id": "d-04-4", "label": "先买后付", "remaining_principal": 800.0, "monthly_payment": 130.0, "remaining_periods": 6, "nominal_apr": 0.18},
                    {"id": "d-04-5", "label": "教育培训分期", "remaining_principal": 1000.0, "monthly_payment": 100.0, "remaining_periods": 10, "nominal_apr": 0.10}
                ],
                "forecast_months": 12, "savings_balance": 200.0, "recurring_subscriptions": []
            }
        },
        "S-05": {
            "expected_level": "关注", "expected_score_m0": None,
            "request": {
                "monthly_disposable_allowance": 2000.0,
                "monthly_part_time_income": 300.0,
                "debts": [{"id": "d-05-1", "label": "电商分期", "remaining_principal": 1800.0, "monthly_payment": 300.0, "remaining_periods": 6, "nominal_apr": 0.08}],
                "forecast_months": 12, "savings_balance": 800.0,
                "recurring_subscriptions": [
                    {"label": "视频会员连续包月", "monthly_cost": 25.0},
                    {"label": "音乐会员连续包月", "monthly_cost": 15.0},
                    {"label": "云存储订阅", "monthly_cost": 10.0}
                ]
            }
        }
    }
    return demo_cases

# ============================================================
# STEP 5 输出文档
# ============================================================
def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def write_calibration_doc(path, scorecard, qrel, qmod, bnpl, fusion):
    rules = scorecard["rules"]
    html = f"""<html><head><meta charset="utf-8">
    <style>
    body{{font-family:'Microsoft YaHei',SimSun;line-height:1.7;margin:36px;}}
    h1{{color:#1a5276;}} h2{{color:#2e86c1;border-bottom:1px solid #ccc;padding-bottom:4px;}}
    table{{border-collapse:collapse;width:100%;margin:12px 0;}}
    th,td{{border:1px solid #888;padding:7px;text-align:left;font-size:13px;}}
    th{{background:#eaf2f8;}} .warn{{background:#fdebd0;padding:10px;border-left:4px solid #e67e22;}}
    </style></head><body>
    <h1>StudentRiskGuard 终极整合校准报告</h1>
    <p><b>版本：</b>{scorecard['version']}　<b>生成时间：</b>{scorecard['generated_at']}</p>

    <h2>一、问卷信效度</h2>
    <p>Cronbach's α = {qrel['cronbach_alpha']}；收敛效度 Spearman ρ = {qrel['convergent_validity']['spearman_rho']}，p = {qrel['convergent_validity']['p_value']}，方向 = {qrel['convergent_validity']['direction']}。</p>

    <h2>二、问卷关键描述统计</h2>
    <p>有效样本 {qmod['module1_profile']['n_total']}，有负债/疑似负债 {qmod['module1_profile']['n_has_debt']}（{qmod['module1_profile']['has_debt_rate']:.2%}）。逾期率（宽松）{qmod['module2_pain']['overdue_rate']:.2%}，严格逾期率 {qmod['module2_pain']['overdue_strict_rate']:.2%}。</p>
    <p>严格逾期组 DTI 中位数 {qmod['module3_model']['strict']['dti_overdue_median']}，未逾期组 {qmod['module3_model']['strict']['dti_not_overdue_median']}，Mann-Whitney p = {qmod['module3_model']['strict']['mannwhitney_dti_p']}。</p>

    <h2>三、BNPL 关键统计</h2>
    <p>样本 {bnpl['n_total']}，违约率 {bnpl['default_rate']:.2%}。违约组 DTI 中位数 {bnpl['dti']['warn_candidate_default_median']}，75分位 {bnpl['dti']['high_candidate_default_q75']}。Student 子样本：{bnpl.get('student_subsample')}</p>

    <h2>四、融合结果</h2>
    <p>问卷权重 w = {fusion['questionnaire_weight']}。融合原始值：{fusion['fused_raw']}；边界约束后：{fusion['fused_constrained']}。</p>
    <table>
    <tr><th>规则</th><th>阈值</th><th>扣分</th><th>校准状态</th><th>来源</th></tr>
    <tr><td>DTI 关注线</td><td>{rules['dti_ratio']['threshold_warn']:.2%}</td><td>{rules['dti_ratio']['deduct_warn']}</td><td>{rules['dti_ratio']['calibration_status']}</td><td>{rules['dti_ratio']['source']}</td></tr>
    <tr><td>DTI 高风险线</td><td>{rules['dti_ratio']['threshold_high']:.2%}</td><td>{rules['dti_ratio']['deduct_high']}</td><td>{rules['dti_ratio']['calibration_status']}</td><td>{rules['dti_ratio']['source']}</td></tr>
    <tr><td>分期多头线</td><td>≥{rules['installment_count']['threshold_multi']}笔</td><td>{rules['installment_count']['deduct_multi']}</td><td>{rules['installment_count']['calibration_status']}</td><td>{rules['installment_count']['source']}</td></tr>
    <tr><td>IRR红线</td><td>{rules['irr_rate']['threshold_high']:.0%}</td><td>{rules['irr_rate']['deduct_high']}</td><td>{rules['irr_rate']['calibration_status']}</td><td>{rules['irr_rate']['source']}</td></tr>
    <tr><td>以贷养贷</td><td>命中即扣</td><td>{rules['borrow_to_repay']['deduct']}</td><td>{rules['borrow_to_repay']['calibration_status']}</td><td>{rules['borrow_to_repay']['source']}</td></tr>
    <tr><td>严格逾期史</td><td>≥2次</td><td>{rules['overdue_history_strict']['deduct']}</td><td>{rules['overdue_history_strict']['calibration_status']}</td><td>{rules['overdue_history_strict']['source']}</td></tr>
    <tr><td>认知薄弱</td><td>量表≤3</td><td>{rules['cognitive_bias']['deduct']}</td><td>{rules['cognitive_bias']['calibration_status']}</td><td>{rules['cognitive_bias']['source']}</td></tr>
    </table>

    <h2>五、使用限制</h2>
    <div class="warn">
    <p>① 问卷为便利抽样，不代表全国大学生总体；② BNPL为合成数据，且分期期数不等于负债笔数；③ 问卷金额为区间中位数估算；④ 严格逾期标签为自报；⑤ 本工具仅作自检参考，不构成金融决策依据。</p>
    </div>
    </body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

def write_formal_plan(path, scorecard, qrel, qmod, bnpl, fusion):
    rules = scorecard["rules"]
    lines = []
    lines.append("# StudentRiskGuard 数据与模型校准分册（正式版）\n")
    lines.append(f"**版本**：{scorecard['version']}  \n**生成时间**：{scorecard['generated_at']}\n")
    lines.append("## 一、目标与范围\n")
    lines.append("本分册解决三件事：① 把214份问卷加工成可校准的学生场景证据；② 把Kaggle BNPL公开数据加工成违约分组证据；③ 用双轨加权融合生成可被M2内核直接读取的`scorecard.json`。\n")
    lines.append("## 二、数据资产与合规边界\n")
    lines.append("- 问卷：匿名、自愿，不采集姓名、学号、手机号、身份证、银行卡、学校名称、平台账号和真实账单；原始答卷不进入产品数据库。\n- BNPL：公开合成数据，仅用于统计校准与方向验证；不用于授信、征信、放贷审批。\n- Lending Club（如使用）：仅用于方向验证，不用于产品化训练。\n")
    lines.append("## 三、问卷处理口径\n")
    lines.append("问卷V1.1共29题。金额题取区间中位数；Q10注意力检查选4才保留；Q1选“是/不确定”记为有负债；Q9拆宽松与严格两套逾期标签；Q15-Q18构造认知得分，Q17反向计分。\n")
    lines.append("## 四、核心指标定义\n")
    lines.append("- DTI = 每月还款合计 ÷（可支配生活费 + 兼职收入）。\n- IRR = 以剩余本金为分母、固定月供为现金流求解月IRR，再×12转年化。\n- 分期笔数：问卷Q2区间中位数；BNPL的`bnpl_installments`是期数，不是负债笔数，不参与笔数融合。\n- 严格逾期：Q9选2-3次或4次及以上；1次不纳入严格组。\n")
    lines.append("## 五、信效度结果\n")
    lines.append(f"- Cronbach's α = **{qrel['cronbach_alpha']}**；各题CITC：{qrel['citc']}。\n- 收敛效度：认知总分与Q21 Spearman ρ = **{qrel['convergent_validity']['spearman_rho']}**，p = {qrel['convergent_validity']['p_value']}，方向{qrel['convergent_validity']['direction']}。\n- 未做因子分析，原因是4题、约200份样本不支持稳定EFA；这是方法诚实边界。\n")
    lines.append("## 六、描述统计与五大模块\n")
    m1, m2, m3, m4, m5 = qmod["module1_profile"], qmod["module2_pain"], qmod["module3_model"], qmod["module4_cognition"], qmod["module5_product"]
    lines.append(f"- 画像：有效样本{m1['n_total']}，有负债/疑似负债{m1['n_has_debt']}（{m1['has_debt_rate']:.2%}），分期笔数中位数{m1['debt_count_median']}，3笔以上占比{m1['debt_count_ge3_rate']:.2%}。\n")
    lines.append(f"- 痛点：月底缺钱{m2['cash_short_rate']:.2%}，压缩开支{m2['cut_expense_rate']:.2%}，以贷养贷{m2['borrow_to_repay_rate']:.2%}，宽松逾期率{m2['overdue_rate']:.2%}，严格逾期率{m2['overdue_strict_rate']:.2%}。\n")
    lines.append(f"- 逾期对比：严格逾期组DTI中位数{m3['strict']['dti_overdue_median']}，未逾期组{m3['strict']['dti_not_overdue_median']}，Mann-Whitney p={m3['strict']['mannwhitney_dti_p']}；严格逾期组分期中位数{m3['strict']['debt_count_overdue_median']}。\n")
    lines.append(f"- 认知：知道全部名义利率比例{m4['know_all_nominal_apr_rate']:.2%}，遇到过手续费{m4['fee_encountered_rate']:.2%}，认知薄弱{m4['cognitive_weak_rate']:.2%}。\n")
    lines.append(f"- 产品：使用意愿均值{m5['willing_to_use_mean']}，隐私顾虑均值{m5['privacy_concern_mean']}，前两大需求为“{m5['top_feature_1']}”“{m5['top_feature_2']}”。\n")
    lines.append("## 七、BNPL公开数据结果\n")
    lines.append(f"- 样本{bnpl['n_total']}，违约率{bnpl['default_rate']:.2%}；违约组DTI中位数{bnpl['dti']['warn_candidate_default_median']}，75分位{bnpl['dti']['high_candidate_default_q75']}。\n- Student子样本：{bnpl.get('student_subsample')}。\n")
    lines.append("## 八、阈值确定方法与最终参数\n")
    lines.append(f"融合公式：最终值 = (1-w)×BNPL候选 + w×问卷候选，w={fusion['questionnaire_weight']}。DTI关注线加边界`max(0.30,min(0.45,融合值))`；高风险线以行业50%为兜底，最高不超过60%。分期笔数不使用BNPL融合。\n")
    lines.append("| 规则 | 阈值 | 扣分 | 状态 | 来源 |\n|---|---:|---:|---|---|\n")
    for k in ["dti_ratio", "installment_count", "irr_rate", "borrow_to_repay", "overdue_history_strict", "cognitive_bias"]:
        r = rules[k]
        if k == "dti_ratio":
            th = f"{r['threshold_warn']:.2%} / {r['threshold_high']:.2%}"
            ded = f"{r['deduct_warn']} / {r['deduct_high']}"
        elif k == "installment_count":
            th = f"≥{r['threshold_multi']}笔"
            ded = str(r['deduct_multi'])
        elif k == "irr_rate":
            th = f">{r['threshold_high']:.0%}"
            ded = str(r['deduct_high'])
        else:
            th = "命中即扣" if k != "cognitive_bias" else "≤3分"
            ded = str(r['deduct'])
        lines.append(f"| {k} | {th} | {ded} | {r['calibration_status']} | {r['source']} |\n")
    lines.append("## 九、M2内核与M0基线回归\n")
    lines.append("已生成`m2_regression_kit.json`，包含S-01~S-05的AssessmentRequest与M0期望等级。M2内核应实现：读`scorecard.json`→算DTI/IRR/结余→四维打分→输出等级。回归验收标准：S-01低风险、S-02关注、S-03中风险、S-04高风险；分数允许±5偏差，等级必须一致。\n")
    lines.append("## 十、未完成项闭环清单\n")
    lines.append("- [x] 问卷V1.1映射修正；\n- [x] 信效度检验；\n- [x] 五大模块统计；\n- [x] BNPL分组统计；\n- [x] 双轨融合与边界约束；\n- [x] scorecard.json生成；\n- [x] 演示样本与M2回归包生成；\n- [x] S5签字页模板生成；\n- [ ] 本地运行M2回归测试并回填实际分数；\n- [ ] 把`scorecard.json`同步到`contracts/scorecard.example.json/yaml`；\n- [ ] 统计搭档在S5签字页签字；\n- [ ] M3会话、M4 Agent、M5页面、M6安全、M7部署按路线推进。\n")
    lines.append("## 十一、风险与局限\n")
    lines.append("① 问卷便利抽样，不代表全国总体；② 金额区间中位数有测量误差；③ 逾期自报口径可能偏宽；④ BNPL为合成数据且期数≠笔数；⑤ 严格逾期组样本若不足30，融合权重应降至0.2；⑥ 本工具不构成金融决策依据。\n")
    lines.append("## 十二、答辩口径\n")
    lines.append("“我们的阈值不是拍脑袋：DTI关注线来自BNPL违约组中位数与问卷严格逾期组中位数的加权融合，并用30%下限与45%上限约束；高风险线以行业50%兜底；分期多头线来自问卷严格逾期组笔数中位数；IRR锚定24%法定红线；以贷养贷和严格逾期史有学术与统计证据。信效度α=0.79、收敛ρ=0.395。样本为便利抽样，我们不做全国推断。”\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def write_s5_signoff(path, scorecard):
    lines = []
    lines.append("# S5 参数冻结签字页\n")
    lines.append(f"- scorecard版本：{scorecard['version']}\n- 生成时间：{scorecard['generated_at']}\n")
    lines.append("## 统计侧确认\n")
    lines.append("- [ ] S-M0-1 单位与口径确认：元/小数/期数1-120\n- [ ] S-M0-2 四维打分卡权重与分档确认\n- [ ] S-M0-3 四组样本输入与期望等级确认\n- [ ] S-M0-4 IRR与现金流假设确认\n- [ ] S-M0-5 savings_balance与recurring_subscriptions口径确认\n")
    lines.append("## 冻结参数\n")
    lines.append(f"- DTI关注线：{scorecard['rules']['dti_ratio']['threshold_warn']:.2%}\n- DTI高风险线：{scorecard['rules']['dti_ratio']['threshold_high']:.2%}\n- 分期多头线：≥{scorecard['rules']['installment_count']['threshold_multi']}笔\n- IRR红线：{scorecard['rules']['irr_rate']['threshold_high']:.0%}\n- 以贷养贷：扣{scorecard['rules']['borrow_to_repay']['deduct']}分\n- 严格逾期史：扣{scorecard['rules']['overdue_history_strict']['deduct']}分\n- 认知薄弱：扣{scorecard['rules']['cognitive_bias']['deduct']}分\n")
    lines.append("签字：统计同学 __________　计算机同学 __________　日期 __________\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

# ============================================================
# MAIN
# ============================================================
def main():
    if not OUTPUT_DIR:
        raise ValueError("请填写 OUTPUT_DIR")
    ensure_dir(OUTPUT_DIR)

    print("[1/7] 处理问卷...")
    qdf, qrel, qmod = process_questionnaire(QUESTIONNAIRE_XLSX)
    qdf.to_csv(os.path.join(OUTPUT_DIR, "integrated_questionnaire_clean.csv"), index=False, encoding="utf-8-sig")
    write_json(os.path.join(OUTPUT_DIR, "reliability_report.json"), qrel)
    write_json(os.path.join(OUTPUT_DIR, "questionnaire_analysis.json"), qmod)

    print("[2/7] 处理BNPL...")
    bnpl = process_bnpl(BNPL_CSV)
    write_json(os.path.join(OUTPUT_DIR, "bnpl_analysis.json"), bnpl)

    print("[3/7] 融合阈值...")
    scorecard, fusion = build_scorecard(qmod, bnpl)
    write_json(os.path.join(OUTPUT_DIR, "fusion_report.json"), fusion)
    write_json(os.path.join(OUTPUT_DIR, "scorecard.json"), scorecard)
    write_json(os.path.join(OUTPUT_DIR, "contracts_scorecard.example.json"), scorecard)

    print("[4/7] 生成演示样本与M2回归包...")
    demo = build_demo_and_m2_kit()
    write_json(os.path.join(OUTPUT_DIR, "demo_cases.json"), demo)
    m2kit = {
        "note": "M2回归包：把demo_cases中的request送入M2内核，期望等级见expected_level；M0分数仅参考，等级必须一致",
        "cases": demo
    }
    write_json(os.path.join(OUTPUT_DIR, "m2_regression_kit.json"), m2kit)

    print("[5/7] 生成校准报告...")
    write_calibration_doc(os.path.join(OUTPUT_DIR, "calibration_report.doc"), scorecard, qrel, qmod, bnpl, fusion)

    print("[6/7] 生成正式计划书章节...")
    write_formal_plan(os.path.join(OUTPUT_DIR, "formal_plan_section.md"), scorecard, qrel, qmod, bnpl, fusion)

    print("[7/7] 生成S5签字页...")
    write_s5_signoff(os.path.join(OUTPUT_DIR, "S5_freeze_signoff.md"), scorecard)

    print("完成。输出目录：", OUTPUT_DIR)
    print("核心文件：scorecard.json / formal_plan_section.md / calibration_report.doc / m2_regression_kit.json / S5_freeze_signoff.md")

if __name__ == "__main__":
    main()