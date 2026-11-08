"""Streamlit-only UI state helpers.

State is kept in Streamlit's process/session memory only. It is not written to
localStorage, a database, CSV, or the backend stores.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

DEFAULTS: dict[str, Any] = {
    "conversation_id": None,
    "session_id": None,
    "selected_sample_id": None,
    "last_chat_response": None,
    "last_agent_response": None,
    "agent_response_source": None,
    "last_intake_response": None,
    "last_user_message": None,
    "last_error": None,
    "auth_token": None,
    "auth_user": None,
    "form_initialized": False,
    "debt_count": 1,
    "subscription_count": 0,
}


def init_state() -> None:
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not st.session_state.form_initialized:
        initialize_form_defaults()
        st.session_state.form_initialized = True


def initialize_form_defaults() -> None:
    st.session_state["income_disposable"] = 2000.0
    st.session_state["income_part_time"] = 0.0
    st.session_state["savings_balance"] = 0.0
    st.session_state["forecast_months"] = 12
    st.session_state["borrow_to_repay"] = False
    st.session_state["strict_overdue_count"] = 0
    st.session_state["insufficient_months_last_3"] = 0
    st.session_state["income_drop_30_cannot_cover"] = False
    st.session_state["financial_cognition_score"] = 4.0
    _ensure_debt_keys(1)
    _ensure_subscription_keys(0)


def _ensure_debt_keys(count: int) -> None:
    defaults = {
        "label": "购物分期",
        "principal": 3000.0,
        "payment": 300.0,
        "periods": 10,
        "apr": 0.12,
    }
    for index in range(count):
        for field, value in defaults.items():
            st.session_state.setdefault(f"debt_{index}_{field}", value)


def _ensure_subscription_keys(count: int) -> None:
    for index in range(count):
        st.session_state.setdefault(f"sub_{index}_label", "会员")
        st.session_state.setdefault(f"sub_{index}_cost", 20.0)


def ensure_dynamic_keys() -> None:
    _ensure_debt_keys(int(st.session_state.get("debt_count", 0)))
    _ensure_subscription_keys(int(st.session_state.get("subscription_count", 0)))


def apply_request_to_form(request: dict[str, Any]) -> None:
    income = request.get("income", {})
    st.session_state["income_disposable"] = float(
        income.get("monthly_disposable_allowance", 0)
    )
    st.session_state["income_part_time"] = float(
        income.get("monthly_part_time_income", 0)
    )
    st.session_state["savings_balance"] = float(request.get("savings_balance", 0))
    st.session_state["forecast_months"] = int(request.get("forecast_months", 12))

    debts = request.get("debts", []) or []
    st.session_state["debt_count"] = len(debts)
    _ensure_debt_keys(len(debts))
    for index, debt in enumerate(debts):
        st.session_state[f"debt_{index}_label"] = debt.get("label", f"分期{index + 1}")
        st.session_state[f"debt_{index}_principal"] = float(
            debt.get("remaining_principal", 0)
        )
        st.session_state[f"debt_{index}_payment"] = float(
            debt.get("monthly_payment", 0)
        )
        st.session_state[f"debt_{index}_periods"] = int(
            debt.get("remaining_periods", 1)
        )
        st.session_state[f"debt_{index}_apr"] = float(debt.get("nominal_apr", 0))

    subscriptions = request.get("recurring_subscriptions", []) or []
    st.session_state["subscription_count"] = len(subscriptions)
    _ensure_subscription_keys(len(subscriptions))
    for index, item in enumerate(subscriptions):
        st.session_state[f"sub_{index}_label"] = item.get("label", f"订阅{index + 1}")
        st.session_state[f"sub_{index}_cost"] = float(item.get("monthly_cost", 0))

    behavior = request.get("behavior", {}) or {}
    st.session_state["borrow_to_repay"] = bool(behavior.get("borrow_to_repay", False))
    st.session_state["strict_overdue_count"] = int(
        behavior.get("strict_overdue_count", 0)
    )
    st.session_state["insufficient_months_last_3"] = int(
        behavior.get("insufficient_months_last_3", 0)
    )
    st.session_state["income_drop_30_cannot_cover"] = bool(
        behavior.get("income_drop_30_cannot_cover", False)
    )
    st.session_state["financial_cognition_score"] = float(
        behavior.get("financial_cognition_score") or 4.0
    )


def clear_transient_results() -> None:
    for key in (
        "last_chat_response",
        "last_agent_response",
        "agent_response_source",
        "last_intake_response",
        "last_user_message",
        "last_error",
    ):
        st.session_state[key] = None
