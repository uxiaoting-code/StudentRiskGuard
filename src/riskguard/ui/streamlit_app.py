"""StudentRiskGuard M5 Streamlit application."""

from __future__ import annotations

from uuid import uuid4

import streamlit as st

from riskguard import __version__
from riskguard.models import FIXED_BOUNDARY_NOTICE
from riskguard.ui.api_client import ApiClient, ApiClientError
from riskguard.ui.components import (
    render_agent_response,
    render_assessment,
    render_boundary_notice,
    render_chat_response,
    render_explanation,
    render_intake_preview,
    render_tool_activity,
)
from riskguard.ui.samples import load_demo_cases
from riskguard.ui.state import (
    apply_request_to_form,
    clear_transient_results,
    ensure_dynamic_keys,
    init_state,
)


def _new_session_id() -> str:
    return f"anon_{uuid4().hex[:12]}"


def _render_header() -> None:
    st.title("StudentRiskGuard")
    st.caption("大学生负债压力自检与理性消费科普 Agent")
    st.write(
        "本工具仅用于金融教育与个人负债压力自查，不采集征信数据，"
        "不评估贷款资格，不推荐借贷产品，不提供授信或放款功能。"
    )
    st.caption(
        "自然语言输入仅用于当前会话的语义解析和金融教育回答；"
        "不用于征信、授信、审批或借贷决策。报告只使用结构化计算结果，"
        "原始文本不持久化保存。"
    )
    st.warning(FIXED_BOUNDARY_NOTICE)


def _clear_ui_state(client: ApiClient) -> None:
    conversation_id = st.session_state.get("conversation_id")
    if conversation_id:
        try:
            client.delete_conversation(conversation_id)
        except ApiClientError:
            pass
    session_id = st.session_state.get("session_id")
    if session_id:
        try:
            client.delete_session(session_id)
        except ApiClientError:
            pass
    if st.session_state.get("auth_token"):
        try:
            client.logout()
        except ApiClientError:
            pass
    for key in (
        "session_id",
        "conversation_id",
        "selected_sample_id",
        "last_chat_response",
        "last_agent_response",
        "last_intake_response",
        "last_user_message",
        "last_error",
        "auth_token",
        "auth_user",
    ):
        st.session_state[key] = None
    st.rerun()


def _set_authenticated_user(client: ApiClient, response: dict) -> None:
    st.session_state.auth_token = response.get("token")
    st.session_state.auth_user = {
        "user_id": response.get("user_id"),
        "username": response.get("username"),
    }
    client.set_access_token(st.session_state.auth_token)
    st.session_state.last_error = None
    st.rerun()


def _render_auth_sidebar(client: ApiClient) -> None:
    st.sidebar.header("账号")
    user = st.session_state.get("auth_user")
    if user:
        st.sidebar.success(f"已登录：{user.get('username', '')}")
        if st.sidebar.button("退出登录", key="auth_logout"):
            try:
                client.logout()
            except ApiClientError as exc:
                st.sidebar.warning(exc.message)
            st.session_state.auth_token = None
            st.session_state.auth_user = None
            client.set_access_token(None)
            st.rerun()
        return

    st.sidebar.caption("无需登录也可以直接使用访客模式。")
    with st.sidebar.expander("登录 / 注册", expanded=False):
        mode = st.radio(
            "账号操作",
            ["登录", "注册"],
            key="auth_mode",
            horizontal=True,
        )
        with st.form("auth_form", clear_on_submit=False):
            username = st.text_input("用户名", key="auth_username")
            password = st.text_input(
                "密码",
                type="password",
                key="auth_password",
            )
            confirm = ""
            if mode == "注册":
                confirm = st.text_input(
                    "确认密码",
                    type="password",
                    key="auth_confirm_password",
                )
            submitted = st.form_submit_button(mode)
            if submitted:
                username = username.strip()
                if not username or not password:
                    st.error("请输入用户名和密码。")
                elif mode == "注册" and password != confirm:
                    st.error("两次输入的密码不一致。")
                else:
                    try:
                        if mode == "登录":
                            response = client.login(username, password)
                        else:
                            response = client.register(username, password)
                        _set_authenticated_user(client, response)
                    except ApiClientError as exc:
                        st.error(exc.message)


def _render_sidebar(client: ApiClient) -> None:
    st.sidebar.header("当前状态")
    st.sidebar.caption(f"API：`{client.base_url}`")
    if st.sidebar.button("检查后端连接", key="health_check"):
        try:
            health = client.health()
            st.sidebar.success(
                f"连接正常：{health.get('service', 'studentriskguard-api')}"
            )
        except ApiClientError as exc:
            st.sidebar.error(exc.message)

    st.sidebar.caption(f"版本：{__version__}")
    if st.session_state.get("conversation_id"):
        st.sidebar.code(st.session_state.conversation_id)
    if st.sidebar.button("清空当前界面状态", key="clear_ui"):
        _clear_ui_state(client)

    st.sidebar.divider()
    st.sidebar.caption(
        "所有数值由确定性 Python 工具计算；LLM 不参与风险评分、DTI、IRR 或现金流计算。"
    )


def _render_sample_buttons() -> None:
    st.subheader("合成演示样本")
    st.caption("以下样本均为合成脱敏数据，可直接载入结构化表单。")
    try:
        cases = load_demo_cases()
    except (OSError, ValueError) as exc:
        st.error("演示样本暂时不可用，请检查 contracts/demo_cases.json。")
        return

    columns = st.columns(min(len(cases), 5))
    for index, case in enumerate(cases):
        with columns[index % len(columns)]:
            if st.button(
                f"{case.get('sample_id', '')} · {case.get('label', '样本')}",
                key=f"sample_{case.get('sample_id', index)}",
            ):
                apply_request_to_form(case.get("request", {}))
                st.session_state.selected_sample_id = case.get("sample_id")
                clear_transient_results()
                st.rerun()
            st.caption(case.get("description", ""))
            st.caption(f"期望等级：{case.get('expected_level', '—')}")


def _build_form_request() -> dict:
    debt_count = int(st.session_state.get("debt_count", 0))
    debts: list[dict] = []
    for index in range(debt_count):
        debt = {
            "id": f"debt_{index + 1}",
            "label": str(st.session_state.get(f"debt_{index}_label", "")).strip()
            or f"分期{index + 1}",
            "remaining_principal": float(
                st.session_state.get(f"debt_{index}_principal", 0)
            ),
            "monthly_payment": float(
                st.session_state.get(f"debt_{index}_payment", 0)
            ),
            "remaining_periods": int(
                st.session_state.get(f"debt_{index}_periods", 1)
            ),
        }
        if not st.session_state.get(f"debt_{index}_apr_unknown", False):
            debt["nominal_apr"] = float(
                st.session_state.get(f"debt_{index}_apr", 0)
            )
        debts.append(debt)

    subscription_count = int(st.session_state.get("subscription_count", 0))
    subscriptions: list[dict] = []
    for index in range(subscription_count):
        subscriptions.append(
            {
                "label": str(st.session_state.get(f"sub_{index}_label", "")).strip()
                or f"订阅{index + 1}",
                "monthly_cost": float(st.session_state.get(f"sub_{index}_cost", 0)),
            }
        )

    return {
        "session_id": _new_session_id(),
        "income": {
            "monthly_disposable_allowance": float(
                st.session_state.get("income_disposable", 0)
            ),
            "monthly_part_time_income": float(
                st.session_state.get("income_part_time", 0)
            ),
        },
        "debts": debts,
        "savings_balance": float(st.session_state.get("savings_balance", 0)),
        "recurring_subscriptions": subscriptions,
        "behavior": {
            "borrow_to_repay": bool(st.session_state.get("borrow_to_repay", False)),
            "strict_overdue_count": int(
                st.session_state.get("strict_overdue_count", 0)
            ),
            "insufficient_months_last_3": int(
                st.session_state.get("insufficient_months_last_3", 0)
            ),
            "income_drop_30_cannot_cover": bool(
                st.session_state.get("income_drop_30_cannot_cover", False)
            ),
            "financial_cognition_score": float(
                st.session_state.get("financial_cognition_score", 4)
            ),
        },
        "forecast_months": int(st.session_state.get("forecast_months", 12)),
    }


def _run_form_assessment(client: ApiClient) -> None:
    try:
        request = _build_form_request()
        if (
            request["income"]["monthly_disposable_allowance"]
            + request["income"]["monthly_part_time_income"]
            <= 0
        ):
            st.error("生活费和兼职收入合计必须大于零。")
            return
        client.create_session(request)
        response = client.agent_assess(request["session_id"])
        st.session_state.session_id = request["session_id"]
        st.session_state.last_agent_response = response
        st.session_state.agent_response_source = "form"
        st.session_state.last_chat_response = None
        st.session_state.last_error = None
        st.rerun()
    except ApiClientError as exc:
        st.session_state.last_error = exc.message
        st.error(exc.message)
    except (TypeError, ValueError) as exc:
        st.error(f"表单字段不合法：{exc}")


def _render_structured_tab(client: ApiClient) -> None:
    st.header("结构化表单自检")
    st.caption("适合已知每笔分期字段的用户；所有金额单位为人民币元。")
    _render_sample_buttons()

    with st.form("structured_assessment_form"):
        col1, col2 = st.columns(2)
        with col1:
            st.number_input(
                "每月稳定可支配生活费",
                min_value=0.0,
                step=100.0,
                key="income_disposable",
            )
        with col2:
            st.number_input(
                "每月兼职收入",
                min_value=0.0,
                step=100.0,
                key="income_part_time",
            )

        debt_count = int(
            st.number_input(
                "分期笔数",
                min_value=0,
                max_value=20,
                step=1,
                key="debt_count",
            )
        )
        ensure_dynamic_keys()

        for index in range(debt_count):
            with st.expander(f"分期 {index + 1}", expanded=index == 0):
                st.text_input("分期名称", key=f"debt_{index}_label")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.number_input(
                        "剩余本金",
                        min_value=0.0,
                        step=100.0,
                        key=f"debt_{index}_principal",
                    )
                    st.number_input(
                        "剩余期数",
                        min_value=1,
                        max_value=120,
                        step=1,
                        key=f"debt_{index}_periods",
                    )
                with col_b:
                    st.number_input(
                        "每月还款",
                        min_value=0.0,
                        step=50.0,
                        key=f"debt_{index}_payment",
                    )
                    apr_unknown = st.checkbox(
                        "名义利率未知",
                        key=f"debt_{index}_apr_unknown",
                    )
                    st.number_input(
                        "名义年利率",
                        min_value=0.0,
                        max_value=1.0,
                        step=0.01,
                        format="%.2f",
                        key=f"debt_{index}_apr",
                        disabled=apr_unknown,
                        help="未知利率不会被当作 0%；勾选后不提交该字段。",
                    )

        with st.expander("存款与订阅", expanded=False):
            st.number_input(
                "当前存款余额",
                min_value=0.0,
                step=100.0,
                key="savings_balance",
            )
            subscription_count = int(
                st.number_input(
                    "订阅数量",
                    min_value=0,
                    max_value=20,
                    step=1,
                    key="subscription_count",
                )
            )
            ensure_dynamic_keys()
            for index in range(subscription_count):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.text_input("订阅名称", key=f"sub_{index}_label")
                with col_b:
                    st.number_input(
                        "每月扣费",
                        min_value=0.0,
                        step=10.0,
                        key=f"sub_{index}_cost",
                    )

        with st.expander("行为与韧性自查", expanded=False):
            st.checkbox("是否曾用新借款偿还旧分期", key="borrow_to_repay")
            st.number_input(
                "过去 12 个月严格逾期次数",
                min_value=0,
                max_value=100,
                step=1,
                key="strict_overdue_count",
            )
            st.number_input(
                "过去 3 个月资金不足月份数",
                min_value=0,
                max_value=3,
                step=1,
                key="insufficient_months_last_3",
            )
            st.checkbox(
                "收入下降 30% 时无法覆盖支出与当前还款",
                key="income_drop_30_cannot_cover",
            )
            st.number_input(
                "金融认知自评（1-5 分）",
                min_value=1.0,
                max_value=5.0,
                step=0.5,
                key="financial_cognition_score",
            )

        st.number_input(
            "预测月份",
            min_value=1,
            max_value=36,
            step=1,
            key="forecast_months",
        )

        submitted = st.form_submit_button("开始风险自检")
        if submitted:
            _run_form_assessment(client)

    if (
        st.session_state.get("last_agent_response")
        and st.session_state.get("agent_response_source") == "form"
    ):
        render_agent_response(st.session_state.last_agent_response)


def _handle_chat_submit(client: ApiClient, message: str) -> None:
    if st.session_state.get("confirming"):
        st.warning("正在生成评估报告，请稍候，不要重复提交。")
        return
    st.session_state.last_user_message = message
    st.session_state.last_agent_response = None
    st.session_state.agent_response_source = None
    st.session_state.assessment_ready = False
    try:
        response = client.chat(
            message,
            conversation_id=st.session_state.get("conversation_id"),
        )
        st.session_state.conversation_id = response.get("conversation_id")
        st.session_state.last_chat_response = response
        st.session_state.last_error = None
        st.rerun()
    except ApiClientError as exc:
        st.session_state.last_error = exc.message
        st.error(exc.message)


def _confirm_chat_intake(client: ApiClient) -> None:
    conversation_id = st.session_state.get("conversation_id")
    if not conversation_id:
        st.error("当前没有可确认的对话草稿。")
        return
    if st.session_state.get("assessment_ready") and st.session_state.get("last_agent_response"):
        return
    if st.session_state.get("confirming"):
        return
    st.session_state.confirming = True
    try:
        response = client.confirm_intake(conversation_id)
        if response.get("session_id"):
            st.session_state.session_id = response["session_id"]
        st.session_state.last_agent_response = response
        st.session_state.agent_response_source = "chat"
        st.session_state.assessment_ready = bool(response.get("assessment"))
        st.session_state.last_chat_response = None
        st.session_state.last_error = None
        st.session_state.confirming = False
        st.rerun()
    except ApiClientError as exc:
        st.session_state.confirming = False
        st.session_state.last_error = exc.message
        if exc.status_code in (404, 409):
            st.warning(
                "本次草稿可能已经确认或已经过期。请查看已有报告；如果没有报告，请点击重新开始。"
            )
        else:
            st.error(exc.message)


def _render_chat_tab(client: ApiClient) -> None:
    st.header("智能对话自检")
    st.caption(
        "建议直接描述你的收入、分期和订阅情况；系统会一次追问一个问题。"
        "完成报告后，也可以继续询问原因、金融概念或模拟新增分期。"
    )

    if st.session_state.get("conversation_id"):
        st.caption(f"当前匿名对话：`{st.session_state.conversation_id}`")
    else:
        st.caption("当前还没有匿名对话；直接输入第一段描述即可。")

    message = st.chat_input(
        "回答当前问题，或直接描述：生活费、兼职收入、分期和订阅情况。"
    )
    if message:
        _handle_chat_submit(client, message)

    if st.session_state.get("last_user_message"):
        with st.chat_message("user"):
            st.write(st.session_state.last_user_message)

    response = st.session_state.get("last_chat_response")
    if response:
        with st.chat_message("assistant"):
            render_chat_response(response)

        if response.get("status") == "ready_for_confirmation":
            st.caption("请先核对以上信息。确认后才会创建正式匿名评估会话。")
            if st.button(
                "确认并生成评估报告",
                key="confirm_chat",
                disabled=bool(st.session_state.get("confirming")),
            ):
                _confirm_chat_intake(client)
        elif response.get("status") == "clarification_limit":
            st.caption("可切换到上方“结构化表单自检”标签页继续，或重新开始对话。")
            if st.button("重新开始对话", key="restart_after_limit"):
                _clear_ui_state(client)

    if (
        st.session_state.get("last_agent_response")
        and st.session_state.get("agent_response_source") == "chat"
    ):
        render_agent_response(st.session_state.last_agent_response)
        if st.button("重新开始新的自检", key="restart_chat_flow"):
            _clear_ui_state(client)


def main() -> None:
    st.set_page_config(
        page_title="StudentRiskGuard",
        page_icon="🛡️",
        layout="wide",
    )
    init_state()
    client = ApiClient()
    client.set_access_token(st.session_state.get("auth_token"))
    _render_header()
    _render_auth_sidebar(client)
    _render_sidebar(client)

    chat_tab, form_tab = st.tabs(["智能对话自检", "结构化表单自检"])
    with chat_tab:
        _render_chat_tab(client)
    with form_tab:
        _render_structured_tab(client)


if __name__ == "__main__":
    main()
