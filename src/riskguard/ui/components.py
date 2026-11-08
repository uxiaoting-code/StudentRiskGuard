"""Reusable Streamlit components for the M5 page."""

from __future__ import annotations

from typing import Any

import streamlit as st

from riskguard.ui.formatting import (
    format_currency,
    format_rate,
    format_review_status,
    format_risk_level,
    format_tool_status,
)
from riskguard.models import FIXED_BOUNDARY_NOTICE

RISK_COLORS = {
    "低风险": "green",
    "关注": "orange",
    "中风险": "orange",
    "高风险": "red",
}


def render_boundary_notice() -> None:
    st.warning(FIXED_BOUNDARY_NOTICE)


def render_tool_activity(activities: list[dict[str, Any]] | None) -> None:
    st.subheader("Agent 工具轨迹")
    if not activities:
        st.caption("本次没有可展示的工具调用记录。")
        return
    for item in activities:
        st.write(
            f"`{item.get('tool', 'unknown')}` · "
            f"{format_tool_status(item.get('status'))} · "
            f"{item.get('latency_ms', '—')} ms"
        )


def render_explanation(explanation: dict[str, Any] | None) -> None:
    if not explanation:
        st.info("本次没有可用的智能解释，仅展示确定性计算结果。")
        return

    st.subheader("智能解读")
    st.write(explanation.get("summary", "—"))

    sources = explanation.get("risk_sources", [])
    if sources:
        st.markdown("**风险来源**")
        for item in sources:
            st.write(
                f"- **{item.get('title', '')}**：{item.get('detail', '')}"
            )

    actions = explanation.get("actions", [])
    if actions:
        st.markdown("**建议行动**")
        for action in actions:
            st.write(f"- {action}")

    education = explanation.get("education", [])
    if education:
        st.markdown("**科普提示**")
        for item in education:
            st.info(item)

    questions = explanation.get("questions_to_consider", [])
    if questions:
        st.markdown("**可以继续思考**")
        for question in questions:
            st.write(f"- {question}")

    st.caption(explanation.get("boundary_notice", FIXED_BOUNDARY_NOTICE))


def render_assessment(result: dict[str, Any], *, title: str = "风险报告") -> None:
    st.subheader(title)
    risk = result.get("risk", {})
    metrics = result.get("metrics", {})

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("风险分数", risk.get("score", "—"))
    col2.metric("风险等级", format_risk_level(risk.get("level")))
    col3.metric("月供收入比", format_rate(metrics.get("debt_to_income_ratio")))
    col4.metric("月结余", format_currency(metrics.get("monthly_surplus")))

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("月供合计", format_currency(metrics.get("monthly_payment_total")))
    col6.metric("剩余负债", format_currency(metrics.get("remaining_debt_total")))
    col7.metric("分期笔数", metrics.get("debt_count", "—"))
    col8.metric("收入合计", format_currency(metrics.get("income_total")))

    st.markdown("**四维风险贡献**")
    dimensions = risk.get("dimensions", [])
    if dimensions:
        st.table(
            [
                {
                    "维度": item.get("id", ""),
                    "原始值": item.get("raw_value", "—"),
                    "得分": item.get("score", "—"),
                    "最大分": item.get("max_score", "—"),
                    "贡献": item.get("contribution", "—"),
                }
                for item in dimensions
            ]
        )
    else:
        st.caption("没有风险维度数据。")

    st.markdown("**逐笔 IRR**")
    irr_results = result.get("irr_results", [])
    if irr_results:
        st.table(
            [
                {
                    "债务 ID": item.get("debt_id", ""),
                    "状态": item.get("status", ""),
                    "月 IRR": (
                        format_rate(item.get("monthly_irr"))
                        if item.get("monthly_irr") is not None
                        else "—"
                    ),
                    "真实年化": (
                        format_rate(item.get("annualized_irr"))
                        if item.get("annualized_irr") is not None
                        else "—"
                    ),
                }
                for item in irr_results
            ]
        )
    else:
        st.caption("没有 IRR 数据。")

    cashflow = result.get("cashflow_series", [])
    if cashflow:
        st.markdown("**未来现金流**")
        st.line_chart(
            {
                "月度结余": [point.get("surplus", 0) for point in cashflow],
                "累计结余": [point.get("cumulative_surplus", 0) for point in cashflow],
            }
        )
        st.caption(
            "横轴为预测月份，纵轴为人民币元；"
            "月供到期后停止扣减，收入按固定收入假设。"
        )
    else:
        st.caption("没有现金流数据。")

    assumptions = result.get("assumptions", {})
    if assumptions:
        st.caption(
            f"预测期：{assumptions.get('forecast_months', '—')} 个月；"
            f"币种：{assumptions.get('currency', 'CNY')}；"
            "仅作教育性静态现金流推演。"
        )

    warnings = result.get("warnings", [])
    if warnings:
        with st.expander("计算提示"):
            for warning in warnings:
                st.write(f"- {warning}")


def render_agent_response(response: dict[str, Any]) -> None:
    status = response.get("status")
    if response.get("degraded"):
        st.warning("智能解读已降级；确定性计算结果仍然可用。")

    if status == "error":
        error = response.get("error") or {}
        st.error(error.get("message", "本次评估暂时不可用。"))
        render_tool_activity(response.get("tool_activity"))
        return

    if response.get("assessment"):
        render_assessment(response["assessment"])
    if response.get("explanation"):
        render_explanation(response["explanation"])
    render_tool_activity(response.get("tool_activity"))
    render_boundary_notice()


def render_intake_preview(preview: dict[str, Any] | None) -> None:
    st.subheader("请确认整理后的信息")
    if not preview:
        st.info("当前没有可确认的信息。")
        return

    income = preview.get("income") or {}
    st.markdown("**收入**")
    st.write(
        f"- 每月生活费：{format_currency(income.get('monthly_disposable_allowance'))}"
    )
    st.write(
        f"- 每月兼职收入：{format_currency(income.get('monthly_part_time_income'))}"
    )

    debts = preview.get("debts") or []
    st.markdown("**分期账单**")
    if not debts:
        st.write("- 当前没有正在还款的分期。")
    for index, debt in enumerate(debts, 1):
        label = debt.get("label") or f"分期 {index}"
        if debt.get("settled") is True or debt.get("remaining_periods") == 0:
            st.write(f"- {label}：已结清，不参与本次负债压力计算。")
        else:
            st.write(
                f"- {label}：还欠 {format_currency(debt.get('remaining_principal'))}，"
                f"每月约还 {format_currency(debt.get('monthly_payment'))}，"
                f"还要还 {debt.get('remaining_periods', '—')} 个月。"
            )

    subscriptions = preview.get("recurring_subscriptions") or []
    if subscriptions:
        st.markdown("**固定订阅支出**")
        for item in subscriptions:
            st.write(
                f"- {item.get('label') or '会员订阅'}："
                f"每月 {format_currency(item.get('monthly_cost'))}"
            )

    st.caption("确认后才会创建匿名会话并调用确定性评估工具。")


def render_education_answer(response: dict[str, Any]) -> None:
    education = response.get("education") or {}
    st.subheader("金融教育回答")
    st.write(education.get("answer") or response.get("reply", "—"))
    topic_ids = education.get("topic_ids", [])
    if topic_ids:
        st.caption("主题：" + "、".join(str(item) for item in topic_ids))
    st.caption(
        "内容审核状态："
        + format_review_status(
            response.get("review_status", education.get("review_status"))
        )
    )
    st.caption(education.get("boundary_notice", FIXED_BOUNDARY_NOTICE))


def render_scenario(result: dict[str, Any]) -> None:
    st.subheader("新增分期情景模拟")
    st.warning("这是基于当前输入和 M2 工具的数学情景模拟，不代表真实借款建议。")

    col1, col2, col3 = st.columns(3)
    col1.metric("月供变化", format_currency(result.get("monthly_payment_delta")))
    col2.metric("月结余变化", format_currency(result.get("monthly_surplus_delta")))
    col3.metric("风险分变化", result.get("risk_score_delta", "—"))

    st.table(
        [
            {
                "项目": "风险等级",
                "模拟前": format_risk_level(result.get("risk_level_before")),
                "模拟后": format_risk_level(result.get("risk_level_after")),
            },
            {
                "项目": "月供合计",
                "模拟前": format_currency(
                    result.get("base_assessment", {}).get("metrics", {}).get(
                        "monthly_payment_total"
                    )
                ),
                "模拟后": format_currency(
                    result.get("scenario_assessment", {}).get("metrics", {}).get(
                        "monthly_payment_total"
                    )
                ),
            },
            {
                "项目": "月结余",
                "模拟前": format_currency(
                    result.get("base_assessment", {}).get("metrics", {}).get(
                        "monthly_surplus"
                    )
                ),
                "模拟后": format_currency(
                    result.get("scenario_assessment", {}).get("metrics", {}).get(
                        "monthly_surplus"
                    )
                ),
            },
        ]
    )


def render_chat_response(response: dict[str, Any]) -> None:
    status = response.get("status")
    if status == "needs_more_info":
        st.warning(response.get("reply", "还需要补充一点信息。"))
        return

    if status == "ready_for_confirmation":
        st.success(response.get("reply", "信息已整理完成。"))
        render_intake_preview(response.get("preview"))
        return

    if status == "education_answer":
        render_education_answer(response)
        render_tool_activity(response.get("tool_activity"))
        return

    if status == "out_of_scope":
        st.info(response.get("reply", "这个请求超出了当前金融教育工具的范围。"))
        return

    if status == "error":
        error = response.get("error") or {}
        st.error(error.get("message", response.get("reply", "请求失败。")))
        return

    if status == "completed":
        if response.get("scenario"):
            render_scenario(response["scenario"])
        if response.get("assessment"):
            render_assessment(response["assessment"])
        if response.get("explanation"):
            render_explanation(response["explanation"])
        render_tool_activity(response.get("tool_activity"))
        render_boundary_notice()
        return

    st.info(response.get("reply", "当前没有可展示的结果。"))
