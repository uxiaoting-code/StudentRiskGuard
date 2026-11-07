"""Minimal Streamlit shell for M1.

The real input, result and scenario pages are implemented in M5.
"""

from __future__ import annotations

import streamlit as st

from riskguard import __version__


def main() -> None:
    st.set_page_config(
        page_title="StudentRiskGuard",
        page_icon="🛡️",
        layout="wide",
    )

    st.title("StudentRiskGuard")
    st.caption("大学生负债压力自检与理性消费科普 Agent")
    st.info("M4 Agent 后端已接入自然语言录入、科普问答和情景模拟；M5 页面闭环尚未实现。")

    left, right = st.columns(2)
    left.metric("当前版本", __version__)
    right.metric("当前阶段", "M1")

    st.subheader("产品边界")
    st.write(
        "本工具仅用于金融教育与个人负债压力自查，不采集征信数据，"
        "不评估贷款资格，不推荐借贷产品，不提供授信或放款功能。"
    )
    st.caption(
        "自然语言输入仅用于当前会话的语义解析和金融教育回答；"
        "不用于征信、授信、审批或借贷决策。报告只使用结构化计算结果，原始文本不持久化保存。"
    )

    st.subheader("下一阶段")
    st.write("M2 将实现指标、IRR、打分卡和现金流计算；M3 将封装会话与工具接口。")


if __name__ == "__main__":
    main()
