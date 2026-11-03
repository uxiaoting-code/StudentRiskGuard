"""Build the M2 research-object and model-calibration report.

Raw questionnaire and BNPL files are intentionally not copied into the
repository. Pass their local paths when running the script.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from scipy.stats import mannwhitneyu


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from riskguard.core import load_scorecard, run_assessment  # noqa: E402
from riskguard.data import load_demo_cases  # noqa: E402
from riskguard.models import AssessmentRequest  # noqa: E402


BODY_FONT = "宋体"
HEADING_FONT = "微软雅黑"
NAVY = "#1F4E79"
TEAL = "#2A9D8F"
ORANGE = "#E76F51"
GOLD = "#E9C46A"
GRAY = "#6C757D"
LIGHT_GRAY = "#D9D9D9"
TABLE_BORDER = "D5DCE3"
PALE_BLUE = "EAF2F8"
BLACK = RGBColor(0, 0, 0)
WHITE = RGBColor(255, 255, 255)
MUTED = RGBColor(89, 89, 89)
CONTENT_WIDTH_CM = 16.6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questionnaire", required=True)
    parser.add_argument("--bnpl", required=True)
    parser.add_argument(
        "--docx",
        default=str(ROOT / "docs" / "23_M2研究对象与模型校准报告.docx"),
    )
    parser.add_argument(
        "--assets",
        default=str(ROOT / "docs" / "assets" / "m2"),
    )
    parser.add_argument(
        "--summary",
        default=str(ROOT / "docs" / "23_M2研究对象分析摘要.json"),
    )
    return parser.parse_args()


def pct(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) * 100 if denominator else np.nan


def format_p(value: float) -> str:
    return "p<0.001" if value < 0.001 else f"p={value:.3f}"


def cronbach_alpha(items: pd.DataFrame) -> float:
    complete = items.dropna()
    item_count = complete.shape[1]
    if item_count < 2 or complete.empty:
        return np.nan
    total_variance = complete.sum(axis=1).var(ddof=1)
    if total_variance == 0:
        return np.nan
    alpha = item_count / (item_count - 1) * (
        1 - complete.var(axis=0, ddof=1).sum() / total_variance
    )
    return float(alpha)


def analyze_questionnaire(path: Path) -> dict:
    raw = pd.read_excel(path, engine="openpyxl")
    valid = raw[raw.iloc[:, 22].eq(4)].copy()
    n = len(valid)

    q1 = valid.iloc[:, 8]
    q2 = valid.iloc[:, 9]
    q3 = valid.iloc[:, 10:16]
    q4 = valid.iloc[:, 16]
    q5 = valid.iloc[:, 17]
    q6 = valid.iloc[:, 18]
    q7 = valid.iloc[:, 19]
    q8 = valid.iloc[:, 20]
    q9 = valid.iloc[:, 21]
    q11, q12, q13, q14 = [valid.iloc[:, index] for index in (23, 24, 25, 26)]
    q15, q16, q17, q18, q19 = [
        valid.iloc[:, index] for index in (27, 28, 29, 30, 31)
    ]
    q20, q21, q22 = [valid.iloc[:, index] for index in (32, 33, 34)]
    q23 = valid.iloc[:, 35:41]
    q25, q26, q27, q28 = [valid.iloc[:, index] for index in (42, 43, 44, 45)]

    eligible = q1.isin([1, 3])
    valid_debt_count = q2.isin([1, 2, 3])
    monthly_payment = q4.map(
        {1: 150, 2: 450, 3: 800, 4: 1250, 5: 1750, 6: 2000}
    )
    stable_funds = q27.map({1: 500, 2: 1500, 3: 2500, 4: 3500, 5: 4000})
    part_time = q28.map({1: 0, 2: 500, 3: 1500, 4: 2000})
    dti = monthly_payment / (stable_funds + part_time).replace(0, np.nan)

    strict_overdue = q9.isin([3, 4])
    never_overdue = q9.eq(1)
    strict_dti = dti[eligible & strict_overdue].dropna()
    never_dti = dti[eligible & never_overdue].dropna()
    overdue_valid = q9.isin([1, 2, 3, 4])
    cognitive = pd.DataFrame(
        {"q15": q15, "q16": q16, "q17_rev": 6 - q17, "q18": q18}
    ).astype(float)
    cognitive_score = cognitive.mean(axis=1)

    explicit_three_plus = q2.isin([2, 3])
    high_concentration = q2.isin([3, 4])
    valid_dti = dti.dropna()

    return {
        "raw_rows": int(len(raw)),
        "invalid_rows": int(len(raw) - n),
        "valid_rows": int(n),
        "valid_rate": pct(n, len(raw)),
        "eligible_rows": int(eligible.sum()),
        "eligible_percent": pct(int(eligible.sum()), n),
        "declared_debt_rows": int(q1.eq(1).sum()),
        "uncertain_debt_rows": int(q1.eq(3).sum()),
        "education": {
            "labels": [
                "本科一年级",
                "本科二年级",
                "本科三年级",
                "本科四年级",
                "本科五年级及以上",
                "硕士研究生",
            ],
            "count": [int(q26.eq(i).sum()) for i in range(1, 7)],
            "percent": [pct(int(q26.eq(i).sum()), n) for i in range(1, 7)],
        },
        "debt_count": {
            "labels": ["1-2笔", "3-4笔", "5笔及以上", "不愿说明"],
            "count": [int(q2.eq(i).sum()) for i in range(1, 5)],
            "percent": [pct(int(q2.eq(i).sum()), n) for i in range(1, 5)],
            "explicit_three_plus_count": int(explicit_three_plus.sum()),
            "explicit_three_plus_percent": pct(
                int(explicit_three_plus.sum()), int(valid_debt_count.sum())
            ),
            "high_concentration_count": int(high_concentration.sum()),
            "high_concentration_percent": pct(
                int(high_concentration.sum()), int(eligible.sum())
            ),
        },
        "debt_types": {
            "labels": [
                "电商购物分期",
                "数码产品分期",
                "教育培训分期",
                "会员/订阅/年付折算月付",
                "先买后付",
                "其他",
            ],
            "percent": [
                pct(q3.iloc[:, index].eq(1).sum(), eligible.sum())
                for index in range(6)
            ],
        },
        "monthly_payment": {
            "labels": [
                "300元以下",
                "300-599元",
                "600-999元",
                "1000-1499元",
                "1500-1999元",
                "2000元及以上",
                "不愿说明",
            ],
            "count": [int(q4.eq(i).sum()) for i in range(1, 8)],
            "percent": [pct(int(q4.eq(i).sum()), eligible.sum()) for i in range(1, 8)],
        },
        "principal": {
            "labels": [
                "3000元以下",
                "3000-9999元",
                "10000-19999元",
                "20000元及以上",
                "不清楚",
                "不愿说明",
            ],
            "count": [int(q5.eq(i).sum()) for i in range(1, 7)],
        },
        "duration": {
            "labels": [
                "6个月及以内",
                "7-12个月",
                "13-24个月",
                "25个月及以上",
                "不清楚",
            ],
            "count": [int(q6.eq(i).sum()) for i in range(1, 6)],
        },
        "self_reported_dti": {
            "labels": [
                "10%以下",
                "10%-19%",
                "20%-29%",
                "30%-39%",
                "40%-49%",
                "50%及以上",
                "无法估计",
            ],
            "count": [int(q7.eq(i).sum()) for i in range(1, 8)],
        },
        "pressure": [
            {
                "label": "过去3个月月底资金不足",
                "count": int(q11.isin([2, 3, 4]).sum()),
                "percent": pct(int(q11.isin([2, 3, 4]).sum()), n),
            },
            {
                "label": "因还款压缩必要支出",
                "count": int(q12.isin([3, 4, 5]).sum()),
                "percent": pct(int(q12.isin([3, 4, 5]).sum()), n),
            },
            {
                "label": "明确担心未来还款压力",
                "count": int(q13.isin([4, 5]).sum()),
                "percent": pct(int(q13.isin([4, 5]).sum()), n),
            },
            {
                "label": "收入下降30%时无法覆盖",
                "count": int(q14.isin([4, 5]).sum()),
                "percent": pct(int(q14.isin([4, 5]).sum()), n),
            },
        ],
        "behavior": {
            "borrow_to_repay_count": int(q8.eq(1).sum()),
            "borrow_to_repay_valid_percent": pct(
                int(q8.eq(1).sum()), int(q8.isin([1, 2]).sum())
            ),
            "loose_overdue_count": int(q9.isin([2, 3, 4]).sum()),
            "loose_overdue_percent": pct(
                int(q9.isin([2, 3, 4]).sum()), int(overdue_valid.sum())
            ),
            "strict_overdue_count": int(strict_overdue.sum()),
            "strict_overdue_percent": pct(
                int(strict_overdue.sum()), int(overdue_valid.sum())
            ),
        },
        "cognition": {
            "score_mean": float(cognitive_score.mean()),
            "cronbach_alpha": cronbach_alpha(cognitive),
            "weak_count": int(cognitive_score.le(3).sum()),
            "weak_percent": pct(int(cognitive_score.le(3).sum()), n),
            "fee_count": int(q20.eq(1).sum()),
            "fee_percent": pct(int(q20.eq(1).sum()), n),
            "knows_all_apr_count": int(q21.eq(1).sum()),
            "knows_all_apr_percent": pct(int(q21.eq(1).sum()), n),
            "q19_mean": float(q19.mean()),
            "willing_to_use_mean": float(q22.mean()),
            "privacy_concern_mean": float(valid.iloc[:, 41].mean()),
        },
        "product_demand": {
            "labels": [
                "汇总多笔分期的月供压力",
                "计算逐笔真实年化成本",
                "预测未来12个月现金流",
                "模拟新增一笔分期",
                "提供理性消费和金融科普",
                "生成可保存的简易报告",
            ],
            "percent": [pct(q23.iloc[:, index].eq(1).sum(), n) for index in range(6)],
        },
        "preferred_format": {
            "labels": [
                "100字以内短文本",
                "图表和数字卡片",
                "音频讲解",
                "1-3分钟短视频",
                "可交互情景模拟",
            ],
            "count": [int(q25.eq(i).sum()) for i in range(1, 6)],
        },
        "dti_comparison": {
            "strict_n": int(len(strict_dti)),
            "never_n": int(len(never_dti)),
            "strict_median": float(strict_dti.median()),
            "never_median": float(never_dti.median()),
            "strict_q25": float(strict_dti.quantile(0.25)),
            "strict_q75": float(strict_dti.quantile(0.75)),
            "never_q25": float(never_dti.quantile(0.25)),
            "never_q75": float(never_dti.quantile(0.75)),
            "p_two_sided": float(
                mannwhitneyu(strict_dti, never_dti, alternative="two-sided").pvalue
            ),
            "dti_valid_n": int(len(valid_dti)),
            "dti_ge_warn_count": int(valid_dti.ge(0.3).sum()),
            "dti_ge_warn_percent": pct(int(valid_dti.ge(0.3).sum()), len(valid_dti)),
            "dti_ge_high_count": int(valid_dti.ge(0.5).sum()),
            "dti_ge_high_percent": pct(int(valid_dti.ge(0.5).sum()), len(valid_dti)),
        },
    }


def analyze_bnpl(path: Path) -> dict:
    df = pd.read_csv(path)
    default = df[df.default_flag.eq(1)]
    non_default = df[df.default_flag.eq(0)]
    students = df[df.employment_type.eq("Student")]
    student_default = students[students.default_flag.eq(1)]
    student_non_default = students[students.default_flag.eq(0)]
    employment_order = ["Student", "Salaried", "Self-Employed", "Unemployed"]
    return {
        "rows": int(len(df)),
        "default_count": int(len(default)),
        "default_rate": pct(len(default), len(df)),
        "employment_labels": employment_order,
        "employment_counts": [
            int(df.employment_type.eq(value).sum()) for value in employment_order
        ],
        "employment_default_rates": [
            pct(
                int(df[df.employment_type.eq(value)].default_flag.sum()),
                int(df.employment_type.eq(value).sum()),
            )
            for value in employment_order
        ],
        "overall_dti": {
            "default_median": float(default.debt_to_income_ratio.median()),
            "default_q75": float(default.debt_to_income_ratio.quantile(0.75)),
            "non_default_median": float(non_default.debt_to_income_ratio.median()),
            "non_default_q75": float(non_default.debt_to_income_ratio.quantile(0.75)),
            "p_value": float(
                mannwhitneyu(
                    default.debt_to_income_ratio,
                    non_default.debt_to_income_ratio,
                    alternative="two-sided",
                ).pvalue
            ),
        },
        "overall_installments": {
            "default_median": float(default.bnpl_installments.median()),
            "non_default_median": float(non_default.bnpl_installments.median()),
            "p_value": float(
                mannwhitneyu(
                    default.bnpl_installments,
                    non_default.bnpl_installments,
                    alternative="two-sided",
                ).pvalue
            ),
        },
        "student_rows": int(len(students)),
        "student_default_rate": pct(len(student_default), len(students)),
        "student_dti": {
            "default_median": float(student_default.debt_to_income_ratio.median()),
            "non_default_median": float(
                student_non_default.debt_to_income_ratio.median()
            ),
            "p_value": float(
                mannwhitneyu(
                    student_default.debt_to_income_ratio,
                    student_non_default.debt_to_income_ratio,
                    alternative="two-sided",
                ).pvalue
            ),
        },
    }


def analyze_demos() -> list[dict]:
    scorecard = load_scorecard()
    labels = {item["id"]: item["label"] for item in scorecard["dimensions"]}
    rows = []
    for case in load_demo_cases():
        request = AssessmentRequest.model_validate(case["request"])
        result = run_assessment(request)
        rows.append(
            {
                "sample_id": case["sample_id"],
                "expected_level": case["expected_level"],
                "dti": result.metrics.debt_to_income_ratio,
                "score": result.risk.score,
                "level": result.risk.level,
                "dimensions": [
                    {
                        "id": dimension.id,
                        "label": labels[dimension.id],
                        "score": dimension.score,
                    }
                    for dimension in result.risk.dimensions
                ],
            }
        )
    return rows


def save_chart(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def make_charts(
    questionnaire: dict,
    bnpl: dict,
    demos: list[dict],
    assets: Path,
) -> dict[str, Path]:
    assets.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "Microsoft YaHei",
            "font.size": 10,
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "axes.edgecolor": "#B7B7B7",
            "axes.linewidth": 0.8,
            "xtick.color": "#333333",
            "ytick.color": "#333333",
            "text.color": "#222222",
        }
    )
    paths: dict[str, Path] = {}

    labels = ["学生", "受雇", "自雇", "失业"]
    values = bnpl["employment_default_rates"]
    fig, ax = plt.subplots(figsize=(7.8, 4.3))
    bars = ax.bar(labels, values, color=[ORANGE, NAVY, TEAL, GOLD], width=0.62)
    ax.set_ylabel("违约率（%）")
    ax.set_title("BNPL数据中各就业状态的违约率")
    ax.set_ylim(0, max(values) + 10)
    ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.2,
            f"{value:.1f}%",
            ha="center",
        )
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    paths["bnpl_employment"] = assets / "fig1_bnpl_employment.png"
    save_chart(fig, paths["bnpl_employment"])

    groups = ["总体违约", "总体未违约", "学生违约", "学生未违约"]
    medians = [
        bnpl["overall_dti"]["default_median"] * 100,
        bnpl["overall_dti"]["non_default_median"] * 100,
        bnpl["student_dti"]["default_median"] * 100,
        bnpl["student_dti"]["non_default_median"] * 100,
    ]
    fig, ax = plt.subplots(figsize=(7.8, 4.5))
    bars = ax.bar(groups, medians, color=[ORANGE, TEAL, GOLD, NAVY], width=0.62)
    ax.set_ylabel("购买金额 / 月收入（%）")
    ax.set_title("BNPL违约组与未违约组的购买收入比")
    ax.set_ylim(0, max(medians) + 10)
    ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, medians):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.8,
            f"{value:.1f}%",
            ha="center",
        )
    ax.text(
        0.99,
        0.96,
        f"总体 {format_p(bnpl['overall_dti']['p_value'])}；"
        f"学生 {format_p(bnpl['student_dti']['p_value'])}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color=GRAY,
    )
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    paths["bnpl_dti"] = assets / "fig2_bnpl_dti.png"
    save_chart(fig, paths["bnpl_dti"])

    education = questionnaire["education"]
    fig, ax = plt.subplots(figsize=(7.8, 4.3))
    y = np.arange(len(education["labels"]))
    ax.barh(y, education["percent"], color=NAVY)
    ax.set_yticks(y, education["labels"])
    ax.invert_yaxis()
    ax.set_xlabel("占有效样本比例（%）")
    ax.set_title("问卷有效样本的教育阶段构成")
    ax.set_xlim(0, max(education["percent"]) + 8)
    ax.grid(axis="x", color=LIGHT_GRAY, linewidth=0.7)
    ax.set_axisbelow(True)
    for index, value in enumerate(education["percent"]):
        ax.text(value + 0.8, index, f"{value:.1f}%", va="center")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    paths["education"] = assets / "fig3_education.png"
    save_chart(fig, paths["education"])

    debt = questionnaire["debt_count"]
    fig, ax = plt.subplots(figsize=(7.8, 4.2))
    bars = ax.bar(
        debt["labels"],
        debt["percent"],
        color=[TEAL, NAVY, ORANGE, GRAY],
        width=0.62,
    )
    ax.set_ylabel("占有效样本比例（%）")
    ax.set_title("问卷中的分期笔数分布")
    ax.set_ylim(0, max(debt["percent"]) + 12)
    ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, debt["percent"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.2,
            f"{value:.1f}%",
            ha="center",
        )
    ax.text(
        0.99,
        0.96,
        f"直接口径≥3笔：{debt['explicit_three_plus_percent']:.1f}%",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color=GRAY,
    )
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    paths["debt_count"] = assets / "fig4_debt_count.png"
    save_chart(fig, paths["debt_count"])

    pressure = questionnaire["pressure"]
    pressure_labels = [item["label"] for item in pressure]
    pressure_values = [item["percent"] for item in pressure]
    fig, ax = plt.subplots(figsize=(8.2, 4.5))
    y = np.arange(len(pressure_labels))
    ax.barh(y, pressure_values, color=[ORANGE, GOLD, TEAL, NAVY])
    ax.set_yticks(y, pressure_labels)
    ax.invert_yaxis()
    ax.set_xlabel("占有效样本比例（%）")
    ax.set_title("问卷样本的现金流压力与风险感知")
    ax.set_xlim(0, max(pressure_values) + 12)
    ax.grid(axis="x", color=LIGHT_GRAY, linewidth=0.7)
    ax.set_axisbelow(True)
    for index, value in enumerate(pressure_values):
        ax.text(value + 1.1, index, f"{value:.1f}%", va="center")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    paths["pressure"] = assets / "fig5_questionnaire_pressure.png"
    save_chart(fig, paths["pressure"])

    dimension_order = [
        ("debt_to_income", "月供收入比 35", NAVY),
        ("debt_stack", "多头分期 15", TEAL),
        ("real_cost", "IRR成本 20", ORANGE),
        ("behavior_resilience", "行为韧性 30", GOLD),
    ]
    fig, ax = plt.subplots(figsize=(8.2, 4.7))
    bottom = np.zeros(len(demos))
    for dimension_id, label, color in dimension_order:
        values = np.array(
            [
                next(
                    item["score"]
                    for item in demo["dimensions"]
                    if item["id"] == dimension_id
                )
                for demo in demos
            ]
        )
        ax.bar(
            [demo["sample_id"] for demo in demos],
            values,
            bottom=bottom,
            label=label,
            color=color,
            width=0.62,
        )
        bottom += values
    ax.set_ylabel("风险贡献分")
    ax.set_title("五套演示样本的四维风险贡献")
    ax.set_ylim(0, 105)
    ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(ncol=4, frameon=False, fontsize=8.3, loc="upper center")
    for index, demo in enumerate(demos):
        ax.text(index, demo["score"] + 2, str(demo["score"]), ha="center", fontsize=9)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    paths["demo_risk"] = assets / "fig6_demo_risk.png"
    save_chart(fig, paths["demo_risk"])
    return paths


def set_run_font(run, name=BODY_FONT, size=10.5, bold=None, color=BLACK):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run.font.size = Pt(size)
    run.font.color.rgb = color
    if bold is not None:
        run.bold = bold


def set_style_font(style, name, size, bold=False, color=BLACK):
    style.font.name = name
    rpr = style.element.get_or_add_rPr()
    rpr.rFonts.set(qn("w:eastAsia"), name)
    rpr.rFonts.set(qn("w:ascii"), name)
    rpr.rFonts.set(qn("w:hAnsi"), name)
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = color


def remove_paragraph_borders(paragraph):
    p_pr = paragraph._p.get_or_add_pPr()
    for border in p_pr.findall(qn("w:pBdr")):
        p_pr.remove(border)


def shade_cell(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.first_child_found_in("w:shd")
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_width(cell, width):
    cell.width = width
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.first_child_found_in("w:tcW")
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(int(width.twips)))
    tc_w.set(qn("w:type"), "dxa")


def set_cell_margins(cell, top=70, start=80, bottom=70, end=80):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (
        ("top", top),
        ("start", start),
        ("bottom", bottom),
        ("end", end),
    ):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color=TABLE_BORDER, size="4"):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)


def set_cell_text(
    cell,
    text,
    *,
    size=8.8,
    bold=False,
    color=BLACK,
    align=WD_ALIGN_PARAGRAPH.LEFT,
):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.12
    run = paragraph.add_run(str(text))
    set_run_font(run, size=size, bold=bold, color=color)


def repeat_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:tblHeader")) is None:
        tr_pr.append(OxmlElement("w:tblHeader"))


def prevent_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def add_para(
    doc,
    text,
    *,
    size=10.5,
    bold=False,
    align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    after=5,
    before=0,
    indent=Cm(0.74),
    line=1.45,
    color=BLACK,
    keep=False,
):
    paragraph = doc.add_paragraph()
    paragraph.alignment = align
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.first_line_indent = indent
    paragraph.paragraph_format.line_spacing = line
    paragraph.paragraph_format.keep_with_next = keep
    paragraph.paragraph_format.keep_together = True
    paragraph.paragraph_format.widow_control = True
    run = paragraph.add_run(text)
    set_run_font(run, size=size, bold=bold, color=color)
    return paragraph


def add_heading(doc, text, level=1, *, page_break=False):
    paragraph = doc.add_paragraph(style=f"Heading {level}")
    remove_paragraph_borders(paragraph)
    paragraph.paragraph_format.page_break_before = page_break
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    paragraph.paragraph_format.space_after = Pt(6 if level == 1 else 4)
    run = paragraph.add_run(text)
    set_run_font(
        run,
        name=HEADING_FONT,
        size=16 if level == 1 else 11.5,
        bold=True,
    )
    return paragraph


def add_table(
    doc,
    headers,
    rows,
    widths,
    *,
    caption=None,
    font_size=8.5,
    alignments=None,
):
    if caption:
        cap = add_para(
            doc,
            caption,
            size=8.8,
            color=MUTED,
            align=WD_ALIGN_PARAGRAPH.LEFT,
            after=4,
            indent=None,
            line=1.1,
            keep=True,
        )
        remove_paragraph_borders(cap)
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)
    header = table.rows[0]
    prevent_split(header)
    repeat_header(header)
    for index, (cell, value) in enumerate(zip(header.cells, headers)):
        set_cell_width(cell, Cm(widths[index]))
        shade_cell(cell, "1F4E79")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_margins(cell, top=80, bottom=80)
        set_cell_text(
            cell,
            value,
            size=font_size,
            bold=True,
            color=WHITE,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
    for row_index, values in enumerate(rows):
        row = table.add_row()
        prevent_split(row)
        for col_index, (cell, value) in enumerate(zip(row.cells, values)):
            set_cell_width(cell, Cm(widths[col_index]))
            shade_cell(cell, PALE_BLUE if row_index % 2 == 0 else "FFFFFF")
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
            alignment = (
                alignments[col_index]
                if alignments and col_index < len(alignments)
                else WD_ALIGN_PARAGRAPH.LEFT
            )
            set_cell_text(cell, value, size=font_size, align=alignment)
    if len(rows) <= 6:
        for row in table.rows[:-1]:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_with_next = True
    add_para(doc, "", after=2, indent=None)
    return table


def add_picture(doc, path: Path, alt: str, width=15.2):
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run()
    shape = run.add_picture(str(path), width=Cm(width))
    shape._inline.docPr.set("descr", alt)
    shape._inline.docPr.set("title", alt)
    return paragraph


def add_caption(doc, text):
    add_para(
        doc,
        text,
        size=8.8,
        color=MUTED,
        align=WD_ALIGN_PARAGRAPH.LEFT,
        after=8,
        indent=None,
        line=1.1,
    )


def add_page_field(paragraph, field: str):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = f" {field} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instruction, separate, text, end])
    set_run_font(run, size=8.5, color=MUTED)


def configure_document(doc):
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.9)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    set_style_font(normal, BODY_FONT, 10.5)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.45
    for level, size in ((1, 16), (2, 11.5)):
        style = doc.styles[f"Heading {level}"]
        set_style_font(style, HEADING_FONT, size, bold=True)
        style.paragraph_format.keep_with_next = True
    title = doc.styles["Title"]
    set_style_font(title, HEADING_FONT, 24, bold=True)
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(8)
    for border in title.element.get_or_add_pPr().findall(qn("w:pBdr")):
        title.element.get_or_add_pPr().remove(border)

    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        update = OxmlElement("w:updateFields")
        update.set(qn("w:val"), "true")
        settings.append(update)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.paragraph_format.space_after = Pt(0)
    prefix = footer.add_run("StudentRiskGuard M2  |  第 ")
    set_run_font(prefix, size=8.5, color=MUTED)
    add_page_field(footer, "PAGE")
    middle = footer.add_run(" 页 / 共 ")
    set_run_font(middle, size=8.5, color=MUTED)
    add_page_field(footer, "NUMPAGES")
    suffix = footer.add_run(" 页")
    set_run_font(suffix, size=8.5, color=MUTED)


def build_document(
    questionnaire: dict,
    bnpl: dict,
    demos: list[dict],
    figures: dict[str, Path],
    output: Path,
):
    scorecard = load_scorecard()
    doc = Document()
    configure_document(doc)
    doc.core_properties.title = (
        "StudentRiskGuard 大学生负债压力自评模型研究对象与校准报告"
    )
    doc.core_properties.author = "StudentRiskGuard 项目组"
    doc.core_properties.subject = "大学生问卷、BNPL外部对照与专家规则评分卡校准"

    for _ in range(3):
        add_para(doc, "", after=0, indent=None)
    add_para(
        doc,
        "StudentRiskGuard 项目报告",
        size=11,
        bold=True,
        color=MUTED,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        after=18,
        indent=None,
    )
    title = doc.add_paragraph(style="Title")
    remove_paragraph_borders(title)
    run = title.add_run("大学生负债压力自评模型\n研究对象与校准报告")
    set_run_font(run, name=HEADING_FONT, size=24, bold=True)
    add_para(
        doc,
        "问卷画像、BNPL外部对照与四维专家规则评分卡",
        size=14,
        bold=True,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        after=22,
        indent=None,
    )
    add_table(
        doc,
        ["项目信息", "内容"],
        [
            ["报告版本", "M2-REPORT-1.0 定稿"],
            ["问卷样本", "214份原始答卷，213份有效样本"],
            ["BNPL样本", "10,345条外部风险记录"],
            ["模型版本", "calc-2026.11-m2"],
            ["参数版本", "scorecard-2026.11-m2"],
            ["报告日期", "2026年11月3日"],
        ],
        [4.0, 9.0],
        font_size=9,
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT],
    )
    for _ in range(5):
        add_para(doc, "", after=0, indent=None)
    add_para(
        doc,
        "StudentRiskGuard 项目组",
        size=11,
        bold=True,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        after=2,
        indent=None,
    )
    add_para(
        doc,
        "2026年11月",
        size=10,
        color=MUTED,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        indent=None,
    )
    doc.add_page_break()

    add_heading(doc, "执行摘要")
    add_para(
        doc,
        f"本报告将两套数据放在同一研究框架中：{questionnaire['valid_rows']}份有效匿名大学生问卷用于理解在校学生的负债结构、现金流压力与金融认知；{bnpl['rows']:,}条BNPL记录只用于观察外部风险方向。两套数据的人群、字段和业务含义不同，不合并为同一个训练样本。",
    )
    add_para(
        doc,
        f"问卷中，{questionnaire['declared_debt_rows']}人明确有分期、月付或先买后付，"
        f"{questionnaire['uncertain_debt_rows']}人表示不确定，合计{questionnaire['eligible_rows']}人，"
        f"占有效样本{questionnaire['eligible_percent']:.1f}%。按原始选项直接识别，"
        f"3笔及以上为{questionnaire['debt_count']['explicit_three_plus_count']}人，"
        f"占有笔数回答样本的{questionnaire['debt_count']['explicit_three_plus_percent']:.1f}%。"
        f"交接稿采用的22.9%高集中度保守口径由“5笔及以上”与“不愿说明”合并得到"
        f"（{questionnaire['debt_count']['high_concentration_count']}人），"
        "不能等同于精确的≥3笔人数。",
    )
    add_para(
        doc,
        f"现金流压力已经具有较高的可观察性：过去3个月至少1个月出现月底资金不足的比例为"
        f"{questionnaire['pressure'][0]['percent']:.1f}%，因还款压缩必要支出的比例为"
        f"{questionnaire['pressure'][1]['percent']:.1f}%，但明确担心未来还款压力的比例仅为"
        f"{questionnaire['pressure'][2]['percent']:.1f}%。行为已经显示压力时，主观焦虑并未同步出现，"
        "这支持以客观指标和自报行为共同构建自查工具。",
    )
    add_para(
        doc,
        f"BNPL总体违约率为{bnpl['default_rate']:.1f}%，学生子样本违约率为"
        f"{bnpl['student_default_rate']:.1f}%。总体数据中，违约组的购买金额/月收入中位数为"
        f"{bnpl['overall_dti']['default_median'] * 100:.1f}%，未违约组为"
        f"{bnpl['overall_dti']['non_default_median'] * 100:.1f}%，"
        f"{format_p(bnpl['overall_dti']['p_value'])}；学生子样本两组分别为"
        f"{bnpl['student_dti']['default_median'] * 100:.1f}%和"
        f"{bnpl['student_dti']['non_default_median'] * 100:.1f}%，"
        f"{format_p(bnpl['student_dti']['p_value'])}。因此BNPL数据只提供方向性参照，"
        "不直接生成学生阈值。",
    )
    add_para(
        doc,
        f"M2采用冻结的四维专家规则评分卡：月供负债收入比35分、多头分期笔数15分、"
        f"IRR真实年化成本20分、行为与韧性30分，总分为100分。"
        f"DTI≥30%的样本触发率为{questionnaire['dti_comparison']['dti_ge_warn_percent']:.1f}%，"
        "落在10%-40%的校内覆盖率校验区间内。五套Demo样本得分为"
        f"{'、'.join(str(demo['score']) for demo in demos)}，分别落入预期风险等级。",
    )

    add_heading(doc, "一、研究对象、数据与方法", page_break=True)
    add_heading(doc, "1.1 研究对象", level=2)
    add_para(
        doc,
        "问卷对象为当前在校大学生，采用微信社交圈和班级群等渠道便利抽样。有效样本以本科一至三年级为主，"
        "三者合计占77.9%；本科各年级合计占97.2%，硕士研究生占2.8%。"
        "这一定位适合理解本科阶段的日常月付和现金流压力，不代表全国大学生总体。",
    )
    add_para(
        doc,
        "BNPL数据包含学生、受雇、自雇和失业四类就业状态。学生子样本仅用于观察青年与学生的外部风险模式。"
        "该数据没有覆盖中国大学生活费、家庭支持和校园消费场景，因此不能替代本校问卷。",
    )
    add_table(
        doc,
        ["数据", "样本量", "研究用途", "关键限制"],
        [
            [
                "匿名问卷",
                f"{questionnaire['valid_rows']}份有效",
                "学生画像、行为规则、阈值覆盖校验",
                "便利抽样、区间金额、自报行为",
            ],
            [
                "BNPL公开数据",
                f"{bnpl['rows']:,}条",
                "总体违约模式的方向性对照",
                "购买收入比不是月供DTI；期数不是负债笔数",
            ],
        ],
        [2.8, 2.5, 5.2, 6.1],
        caption="表1  两套数据的用途与边界",
        alignments=[WD_ALIGN_PARAGRAPH.LEFT] * 4,
    )

    add_heading(doc, "1.2 数据处理与检验", level=2)
    add_para(
        doc,
        f"问卷原始{questionnaire['raw_rows']}份，注意力检查剔除{questionnaire['invalid_rows']}份，"
        f"保留{questionnaire['valid_rows']}份，有效率{questionnaire['valid_rate']:.1f}%。"
        "金额题使用可复现区间代表值；金融认知四题先对反向题进行6-x转换，再计算均分。"
        "Cronbach α采用四项量表的方差分解公式计算。",
    )
    add_para(
        doc,
        "BNPL数据按default_flag分组，比较购买金额/月收入与单笔分期期数的中位数，"
        "使用Mann-Whitney U检验判断组间差异并报告双边p值。"
        "全部解释采用描述性或组间比较口径，不把横截面相关写成因果结论。",
    )
    add_para(
        doc,
        "研究对象选择、变量变换和阈值分析只用于产品校准。风险计算由确定性公式和专家规则完成，"
        "大模型只在后续链路中解释已经生成的结果，不参与DTI、IRR或评分。",
    )

    add_heading(doc, "二、BNPL数据的外部风险模式", page_break=True)
    add_picture(
        doc,
        figures["bnpl_employment"],
        "BNPL各就业状态违约率条形图",
    )
    add_caption(doc, "图1  BNPL数据中各就业状态的违约率")
    add_para(
        doc,
        f"学生和失业群体的违约率分别为{bnpl['employment_default_rates'][0]:.1f}%和"
        f"{bnpl['employment_default_rates'][3]:.1f}%，高于受雇群体的"
        f"{bnpl['employment_default_rates'][1]:.1f}%和自雇群体的"
        f"{bnpl['employment_default_rates'][2]:.1f}%。这说明收入来源稳定性与风险承受能力"
        "在外部数据中具有明显关联，也支持在大学生场景中关注现金流韧性。",
    )
    add_picture(
        doc,
        figures["bnpl_dti"],
        "BNPL总体与学生子样本的购买收入比对照图",
    )
    add_caption(doc, "图2  BNPL违约组与未违约组的购买金额/月收入")
    add_para(
        doc,
        f"总体违约组的购买收入比中位数为{bnpl['overall_dti']['default_median'] * 100:.1f}%，"
        f"未违约组为{bnpl['overall_dti']['non_default_median'] * 100:.1f}%，"
        f"{format_p(bnpl['overall_dti']['p_value'])}。单笔分期期数的中位数分别为"
        f"{bnpl['overall_installments']['default_median']:.0f}和"
        f"{bnpl['overall_installments']['non_default_median']:.0f}，"
        f"但差异不显著（{format_p(bnpl['overall_installments']['p_value'])}）。",
    )
    add_para(
        doc,
        f"学生子样本的违约组与未违约组购买收入比中位数分别为"
        f"{bnpl['student_dti']['default_median'] * 100:.1f}%和"
        f"{bnpl['student_dti']['non_default_median'] * 100:.1f}%，"
        f"{format_p(bnpl['student_dti']['p_value'])}。因此，外部数据支持"
        "“总体债务负担与违约有关”的方向，但不能直接给出中国学生的DTI阈值，"
        "也不能把bnpl_installments当作多头负债笔数。",
    )

    add_heading(doc, "三、问卷样本的研究对象情况")
    add_picture(doc, figures["education"], "问卷样本教育阶段构成条形图")
    add_caption(doc, "图3  问卷有效样本的教育阶段构成")
    add_para(
        doc,
        "样本的教育结构决定了结论的适用范围。研究结果适合描述本科阶段的月付与现金流压力，"
        "对研究生、非在校青年和已就业群体只能提供有限参考。",
    )
    add_picture(doc, figures["debt_count"], "问卷样本分期笔数分布柱状图")
    add_caption(doc, "图4  问卷中的分期笔数分布")
    add_para(
        doc,
        f"有分期或不确定人群为{questionnaire['eligible_rows']}人。按原始选项直接识别，"
        f"3笔及以上共{questionnaire['debt_count']['explicit_three_plus_count']}人，"
        f"占有笔数回答样本的{questionnaire['debt_count']['explicit_three_plus_percent']:.1f}%。"
        f"交接稿所用22.9%是{questionnaire['debt_count']['high_concentration_count']}名"
        "选择5笔及以上或不愿说明者占该人群的比例，适合作为“高集中度或未知”的保守口径，"
        "但不应被解释为精确的≥3笔比例。月付义务具有分散和叠加特征，"
        "单笔金额不大并不等于总压力低。",
    )
    add_picture(doc, figures["pressure"], "问卷现金流压力与风险感知条形图")
    add_caption(doc, "图5  现金流压力与风险感知")
    add_table(
        doc,
        ["观察指标", "人数", "比例"],
        [
            [item["label"], item["count"], f"{item['percent']:.1f}%"]
            for item in questionnaire["pressure"]
        ]
        + [
            [
                "曾以贷养贷",
                questionnaire["behavior"]["borrow_to_repay_count"],
                f"{questionnaire['behavior']['borrow_to_repay_valid_percent']:.1f}%",
            ],
            [
                "严格逾期（2次及以上）",
                questionnaire["behavior"]["strict_overdue_count"],
                f"{questionnaire['behavior']['strict_overdue_percent']:.1f}%",
            ],
        ],
        [9.0, 2.5, 2.8],
        caption="表2  问卷中的现金流与借贷接续行为",
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
        ],
    )
    add_para(
        doc,
        f"月底资金不足占{questionnaire['pressure'][0]['percent']:.1f}%，"
        f"明显高于明确担心未来还款压力的{questionnaire['pressure'][2]['percent']:.1f}%。"
        "行为信号强于主观焦虑，说明风险可能已经发生，但用户没有形成同等强度的心理预警。",
    )

    add_heading(doc, "四、金融认知与产品需求")
    add_para(
        doc,
        f"金融认知量表Cronbach α为{questionnaire['cognition']['cronbach_alpha']:.4f}，"
        "高于0.7的常用信度参考线，适合进行群体层面的描述。"
        f"认知得分均值为{questionnaire['cognition']['score_mean']:.2f}，"
        f"≤3分的认知薄弱群体占{questionnaire['cognition']['weak_percent']:.1f}%。"
        f"{questionnaire['cognition']['fee_percent']:.1f}%的学生遇到服务费、手续费或前置费用，"
        f"只有{questionnaire['cognition']['knows_all_apr_percent']:.1f}%知道所有分期的名义年利率。",
    )
    add_table(
        doc,
        ["能力需求", "选择比例"],
        [
            [label, f"{value:.1f}%"]
            for label, value in zip(
                questionnaire["product_demand"]["labels"],
                questionnaire["product_demand"]["percent"],
            )
        ],
        [9.5, 3.0],
        caption="表3  学生最希望工具提供的能力",
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER],
    )
    add_para(
        doc,
        f"月供汇总和真实年化成本是需求最高的两项能力，与M2的DTI和IRR计算方向一致。"
        f"使用意愿均值为{questionnaire['cognition']['willing_to_use_mean']:.2f}，"
        f"隐私顾虑均值为{questionnaire['cognition']['privacy_concern_mean']:.2f}。"
        "产品应坚持不采集征信、不上传真实账单、不保存平台账号，并在页面上明确数据用途。",
    )

    add_heading(doc, "五、社会科学解释")
    add_heading(doc, "5.1 月付分散与支付痛感", level=2)
    add_para(
        doc,
        "平台把一次大额消费拆为多个小额月付，当下的支付痛感下降，未来现金流却被持续占用。"
        f"问卷中会员订阅和先买后付的覆盖率分别为"
        f"{questionnaire['debt_types']['percent'][3]:.1f}%和"
        f"{questionnaire['debt_types']['percent'][4]:.1f}%，"
        "说明风险入口不止电商分期，还包括自动续费和短期赊购。"
        "单笔月供较低并不等于总成本较低，期限、服务费和现金占用需要一起核算。",
    )
    add_heading(doc, "5.2 金融素养中的自评偏差", level=2)
    add_para(
        doc,
        "用户可能理解“日息”或“每期还款”的字面含义，却无法独立完成现金流折现。"
        f"仅{questionnaire['cognition']['knows_all_apr_percent']:.1f}%知道所有分期的名义年利率，"
        "而认知薄弱比例仍超过四分之一。产品应直接计算真实成本，"
        "让用户看到总还款、月度占用和IRR，而不是要求用户先成为金融专家。",
    )
    add_heading(doc, "5.3 行为信号与风险感知", level=2)
    add_para(
        doc,
        f"{questionnaire['behavior']['borrow_to_repay_valid_percent']:.1f}%的有效回答者曾以贷养贷，"
        f"{questionnaire['behavior']['strict_overdue_percent']:.1f}%出现2次及以上严格逾期。"
        f"行为已经显示压力时，主观担心比例仍只有{questionnaire['pressure'][2]['percent']:.1f}%。"
        "低月供锚定、心理账户和现时偏差可以解释这一差距，"
        "因此行为与韧性必须成为评分卡中的独立维度，而不能只用自评焦虑代替。",
    )
    add_heading(doc, "5.4 流动性约束与韧性", level=2)
    add_para(
        doc,
        f"收入下降30%时无法覆盖支出和当前还款的比例为"
        f"{questionnaire['pressure'][3]['percent']:.1f}%。"
        "大学生的收入来源常由生活费和不稳定兼职组成，固定月供会放大短期流动性约束。"
        "BNPL数据中学生和失业群体违约率高于受雇和自雇群体，"
        "与这一解释方向一致，但不同人群与字段口径仍限制了直接外推。",
    )
    add_heading(doc, "5.5 从风险标签到理性消费教育", level=2)
    add_para(
        doc,
        "负债压力并不等同于个人失败。将负债行为道德化会降低用户求助意愿，"
        "也容易掩盖产品设计、支付机制和信息不对称的影响。"
        "StudentRiskGuard的角色是提供可解释的资金流与成本反馈，帮助用户理解选择后果，"
        "而不是进行借贷审批、授信评分或对个人品格作判断。",
    )

    add_heading(doc, "六、M2模型与参数校准")
    add_heading(doc, "6.1 计算链路", level=2)
    add_para(
        doc,
        "M2由纯函数组成：输入AssessmentRequest后，依次计算收入与月度固定支出、逐笔IRR、"
        "四维评分和12个月现金流，最后生成AssessmentResult。所有字段经过Pydantic校验，"
        "原始明细不进入大模型。相同输入重复计算得到相同结果。",
    )
    add_para(
        doc,
        "DTI =（债务月供 + 持续订阅月费）÷（可支配资金 + 兼职收入）。"
        "IRR以剩余本金为第0期现金流入，用固定月供求解月度IRR，"
        "再转换为有效年化：(1 + monthly_irr)^12 - 1。",
        align=WD_ALIGN_PARAGRAPH.CENTER,
        indent=None,
    )
    add_heading(doc, "6.2 四维评分卡", level=2)
    add_table(
        doc,
        ["维度", "最大分", "冻结规则", "解释与依据"],
        [
            [
                "月供负债收入比",
                "35",
                "<30%得0；30%-39%得12；40%-49%得24；≥50%得35",
                "问卷严格逾期组DTI中位数31.5%；行业50%高风险锚点",
            ],
            [
                "多头分期笔数",
                "15",
                "≤2笔得0；3笔得6；4笔得10；≥5笔得15",
                "同时持有笔数反映额度分散与还款管理负荷",
            ],
            [
                "IRR真实年化成本",
                "20",
                "<10%得0；10%-23.9%得6；24%-35.9%得12；≥36%得20",
                "内部成本预警线，不宣称为法定红线",
            ],
            [
                "行为与韧性",
                "30",
                "以贷养贷10；严格逾期6；资金不足2/4/6；收入下降无法覆盖4；认知薄弱3",
                "按配置逐项累加并封顶30分",
            ],
        ],
        [3.0, 1.8, 6.5, 5.3],
        caption="表4  M2冻结版四维评分卡",
        alignments=[
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.LEFT,
        ],
        font_size=8.1,
    )
    add_para(
        doc,
        "总分按half-up取整：0-24低风险，25-49关注，50-74中风险，75-100高风险。"
        "四个维度权重分别为0.35、0.15、0.20和0.30，最大值合计100。"
        "全部阈值和分值存放在独立scorecard.json中，评分代码不硬编码业务阈值。",
    )

    add_heading(doc, "6.3 阈值校准与覆盖校验", level=2)
    add_para(
        doc,
        f"问卷中严格逾期组的DTI中位数为{questionnaire['dti_comparison']['strict_median'] * 100:.1f}%，"
        f"从未逾期组为{questionnaire['dti_comparison']['never_median'] * 100:.1f}%，"
        f"{format_p(questionnaire['dti_comparison']['p_two_sided'])}，"
        f"两组样本量分别为{questionnaire['dti_comparison']['strict_n']}和"
        f"{questionnaire['dti_comparison']['never_n']}。"
        "这支持将30%作为预警起点，但不能证明30%就是全国大学生的普遍临界值。",
    )
    add_para(
        doc,
        f"按可计算DTI的{questionnaire['dti_comparison']['dti_valid_n']}名样本校验，"
        f"DTI≥30%的人数为{questionnaire['dti_comparison']['dti_ge_warn_count']}，"
        f"占{questionnaire['dti_comparison']['dti_ge_warn_percent']:.1f}%；"
        f"DTI≥50%的人数为{questionnaire['dti_comparison']['dti_ge_high_count']}，"
        f"占{questionnaire['dti_comparison']['dti_ge_high_percent']:.1f}%。"
        "30%预警线落在10%-40%覆盖率目标内，50%高压力线作为更严格的第二层提示。",
    )
    add_para(
        doc,
        f"BNPL总体违约组购买收入比中位数为{bnpl['overall_dti']['default_median'] * 100:.1f}%，"
        f"未违约组为{bnpl['overall_dti']['non_default_median'] * 100:.1f}%；"
        "该差异只用于确认“债务负担越高、风险越高”的方向。"
        "由于该字段不是月供DTI、学生子样本差异不显著，且样本不是中国大学生，"
        "BNPL数据不直接参与学生阈值的数值拟合。",
    )

    add_heading(doc, "6.4 演示样本回归", level=2)
    add_picture(
        doc,
        figures["demo_risk"],
        "五套演示样本的四维风险贡献堆叠图",
        width=14.2,
    )
    add_caption(doc, "图6  五套演示样本的四维风险贡献")
    add_table(
        doc,
        ["样本", "DTI", "风险分", "等级", "主要覆盖场景"],
        [
            [
                "S-01",
                f"{demos[0]['dti'] * 100:.1f}%",
                demos[0]["score"],
                demos[0]["level"],
                "单笔小额分期、收入稳定",
            ],
            [
                "S-02",
                f"{demos[1]['dti'] * 100:.1f}%",
                demos[1]["score"],
                demos[1]["level"],
                "两笔分期、含短期资金不足",
            ],
            [
                "S-03",
                f"{demos[2]['dti'] * 100:.1f}%",
                demos[2]["score"],
                demos[2]["level"],
                "三笔叠加、DTI达到40%",
            ],
            [
                "S-04",
                f"{demos[3]['dti'] * 100:.1f}%",
                demos[3]["score"],
                demos[3]["level"],
                "五笔叠加、行为与韧性压力",
            ],
            [
                "S-05",
                f"{demos[4]['dti'] * 100:.1f}%",
                demos[4]["score"],
                demos[4]["level"],
                "存款缓冲与持续订阅",
            ],
        ],
        [1.7, 2.2, 2.2, 2.5, 8.0],
        caption="表5  M2演示样本回归结果",
        alignments=[
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
        ],
    )
    add_para(
        doc,
        "五套样本覆盖低风险、关注、中风险和高风险，并额外验证存款与订阅。"
        "全部样本通过冻结等级回归；同一输入重复20次结果一致。"
        "订阅进入DTI和现金流，但不进入债务笔数与IRR；存款只用于现金流缓冲推演。",
    )
    add_table(
        doc,
        ["验证项", "结果"],
        [
            ["核心自动化测试", "24项通过，无失败"],
            ["五套演示样本回归", "5/5等级符合冻结结果"],
            ["重复计算一致性", "同一输入20次结果完全一致"],
            ["IRR手算对照", "三笔债务与零成本债务通过"],
            ["评分卡一致性", "包内配置与契约配置一致"],
            ["订阅与存款边界", "订阅进入固定支出，存款缺口月份可识别"],
            ["行为评分边界", "逐项累加并在30分处封顶"],
        ],
        [7.0, 7.0],
        caption="表6  M2验证证据",
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT],
    )

    add_heading(doc, "七、研究局限性与结论建议")
    add_heading(doc, "7.1 研究局限", level=2)
    add_para(
        doc,
        "第一，问卷采用便利抽样，样本以本科一至三年级为主，不具备全国代表性。"
        "横截面数据只能说明变量关联，不能证明负债行为与压力之间的因果关系。",
    )
    add_para(
        doc,
        "第二，金额题使用区间，DTI分析采用区间代表值，可能带来测量误差；"
        "逾期、以贷养贷和现金流压力均为自报信息，可能受回忆偏差和社会赞许性影响。"
        "问卷Q2的“3-4笔”与“5笔及以上”不是精确计数，因此高集中度口径必须明确披露。",
    )
    add_para(
        doc,
        "第三，BNPL数据的人群、国家和字段定义均与国内大学生不同。"
        "其debt_to_income_ratio是购买金额/月收入，bnpl_installments是单笔期数，"
        "不能替代月供DTI和同时负债笔数。该数据的价值只在外部方向性参照。",
    )
    add_para(
        doc,
        "第四，IRR阈值和行为权重目前缺少学生真实账单与纵向违约结果，"
        "属于产品内控和金融教育参数，不是监管认定、授信规则或风险诊断。"
        "M7前仍需经济统计同学人工复核参数，并在获得合规数据后继续验证。",
    )

    add_heading(doc, "7.2 结论", level=2)
    add_para(
        doc,
        "M2已经形成可复现的确定性计算内核：DTI捕捉月度固定支出压力，"
        "IRR揭示真实资金成本，多头分期笔数刻画负债集中度，"
        "行为与韧性维度覆盖借贷接续、逾期、现金流脆弱性和金融认知。"
        "四维评分卡保持可解释性，并与问卷覆盖率、行业锚点和外部数据方向进行交叉校验。",
    )
    add_para(
        doc,
        "计算与解释严格分离。LLM不参与任何指标、现金流或评分计算；"
        "LLM调用失败时，系统仍能展示原始指标、风险分和固定模板提示。"
        "因此，M2满足进入M3 Agent链路的工程前提。"
        "本报告及其模型仅用于大学生金融教育与个人负债压力自查，"
        "不构成信贷审批、授信、放款、投资建议或对个人信用状况的正式评估。",
    )

    add_heading(doc, "7.3 后续建议", level=2)
    for text in [
        "在M3中只允许DeepSeek读取AssessmentResult并生成解释，提示词不得要求模型重算DTI、IRR或总分。",
        "在M4表单中允许用户修正区间代表值，优先采集金额、月供、期数和行为字段，不采集平台账号与真实账单。",
        "在结果页同时展示总分、四个维度贡献和“本结果不构成信贷审批或诊断”的边界声明。",
    ]:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.left_indent = Cm(0.75)
        paragraph.paragraph_format.first_line_indent = Cm(-0.55)
        paragraph.paragraph_format.space_after = Pt(4)
        paragraph.paragraph_format.line_spacing = 1.4
        run = paragraph.add_run("•  ")
        set_run_font(run, size=10.5, bold=True, color=BLACK)
        run = paragraph.add_run(text)
        set_run_font(run, size=10.5, color=BLACK)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def main():
    args = parse_args()
    questionnaire_path = Path(args.questionnaire)
    bnpl_path = Path(args.bnpl)
    assets = Path(args.assets)
    summary_path = Path(args.summary)
    output = Path(args.docx)

    questionnaire = analyze_questionnaire(questionnaire_path)
    bnpl = analyze_bnpl(bnpl_path)
    demos = analyze_demos()
    figures = make_charts(questionnaire, bnpl, demos, assets)
    scorecard = load_scorecard()
    summary = {
        "questionnaire": questionnaire,
        "bnpl": bnpl,
        "demo_cases": demos,
        "scorecard_version": scorecard["version"],
        "scorecard_max_scores": {
            item["id"]: item["max_score"] for item in scorecard["dimensions"]
        },
        "figures": {key: str(value) for key, value in figures.items()},
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    build_document(questionnaire, bnpl, demos, figures, output)
    print(output)
    print(summary_path)


if __name__ == "__main__":
    main()
