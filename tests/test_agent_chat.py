from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from riskguard.api.main import create_app
from riskguard.models import AssessmentRequest, FIXED_BOUNDARY_NOTICE, ScenarioDraft
from riskguard.services import ConversationStore, ScenarioNotFound, SessionStore

ROOT = Path(__file__).resolve().parents[1]


class FakeChatModel:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected model call")
        item = self.responses.pop(0)
        return item(kwargs) if callable(item) else item


def demo_request(session_id: str = "chat-demo") -> AssessmentRequest:
    cases = json.loads((ROOT / "contracts" / "demo_cases.json").read_text(encoding="utf-8"))
    raw = next(case["request"] for case in cases if case["sample_id"] == "S-03")
    raw = dict(raw)
    raw["session_id"] = session_id
    return AssessmentRequest.model_validate(raw)


def tool_call_response(kwargs: dict[str, Any]) -> dict[str, Any]:
    user_message = json.loads(kwargs["messages"][1]["content"])
    session_id = user_message["session_id"]
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_chat_1",
                            "type": "function",
                            "function": {
                                "name": "run_risk_assessment",
                                "arguments": json.dumps({"session_id": session_id}),
                            },
                        }
                    ],
                }
            }
        ]
    }


def explanation_response() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "summary": "当前固定支出对现金流形成明显压力。",
                            "risk_sources": [
                                {
                                    "dimension_id": "debt_to_income",
                                    "title": "月供压力",
                                    "detail": "固定支出在可支配资金中占比较高。",
                                }
                            ],
                            "actions": [
                                "核对每笔分期的月供和剩余期数。",
                                "检查未来数月的基本生活支出。",
                            ],
                            "education": [
                                "低月供不等于低总成本，应关注期限和真实成本。"
                            ],
                            "questions_to_consider": [
                                "收入下降时是否仍能覆盖固定支出？"
                            ],
                            "boundary_notice": FIXED_BOUNDARY_NOTICE,
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def education_response() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "topic_id": "irr_real_cost",
                            "key_point_indices": [1],
                            "action_indices": [1],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def scenario_response() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": "complete",
                            "scenario": {
                                "label": "新手机分期",
                                "remaining_principal": 2400,
                                "monthly_payment": 300,
                                "remaining_periods": 8,
                                "nominal_apr": 0.12,
                            },
                            "missing_fields": [],
                            "warnings": [],
                            "question": None,
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def partial_scenario_response() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": "needs_more_info",
                            "scenario": {
                                "label": "新手机",
                                "remaining_principal": 2400,
                            },
                            "missing_fields": [
                                "monthly_payment",
                                "remaining_periods",
                            ],
                            "warnings": [],
                            "question": "每月还多少，还要还几个月？",
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def api_with_session(
    model: FakeChatModel,
    *,
    include_conversation: bool = True,
) -> tuple[TestClient, SessionStore, ConversationStore]:
    sessions = SessionStore()
    request = demo_request()
    sessions.create(request)
    conversations = ConversationStore()
    if include_conversation:
        conversations.create(
            conversation_id="conv-chat",
            session_id=request.session_id,
            current_intent="risk_explanation",
        )
    return (
        TestClient(
            create_app(
                session_store=sessions,
                conversation_store=conversations,
                llm_client=model,
            )
        ),
        sessions,
        conversations,
    )


def test_chat_education_answers_from_retrieved_card() -> None:
    model = FakeChatModel([education_response()])
    api = TestClient(create_app(llm_client=model))

    response = api.post(
        "/api/v1/agent/chat",
        json={"message": "什么是IRR？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "education_answer"
    assert body["review_status"] == "pending"
    assert body["education"]["topic_ids"] == ["irr_real_cost"]
    assert body["education"]["source_excerpts"]
    assert body["tool_activity"][0]["tool"] == "retrieve_education_topic"
    assert "IRR" in body["reply"]
    assert all(item in body["reply"] for item in body["education"]["source_excerpts"])
    assert len(model.calls) == 1


def test_chat_risk_explanation_reuses_assessment_result() -> None:
    model = FakeChatModel([tool_call_response, explanation_response()])
    api, _, _ = api_with_session(model)

    response = api.post(
        "/api/v1/agent/chat",
        json={"conversation_id": "conv-chat", "message": "为什么我是中风险？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["assessment"]["risk"]["level"] == "中风险"
    assert body["explanation"]["boundary_notice"] == FIXED_BOUNDARY_NOTICE
    assert body["tool_activity"][0]["tool"] == "run_risk_assessment"


def test_chat_scenario_uses_tool_and_does_not_mutate_session() -> None:
    model = FakeChatModel([scenario_response()])
    api, sessions, _ = api_with_session(model)
    original_count = len(sessions.get("chat-demo").request.debts)

    response = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "如果我新增一笔分期，本金2400，每月300，8期，利率12%，会怎样？",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["scenario"]["monthly_payment_delta"] == 300
    assert body["tool_activity"][0]["tool"] == "simulate_new_installment"
    assert len(sessions.get("chat-demo").request.debts) == original_count
    assert len(model.calls) == 1


def test_chat_scenario_keeps_partial_draft_across_turns() -> None:
    model = FakeChatModel([partial_scenario_response(), scenario_response()])
    api, _, conversations = api_with_session(model)

    first = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "如果我新增一笔手机分期，本金2400，会怎样？",
        },
    ).json()
    second = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "每月还300，还要还8期，利率不知道。",
        },
    ).json()

    assert first["status"] == "needs_more_info"
    assert first["preview"]["remaining_principal"] == 2400
    assert second["status"] == "completed"
    assert second["scenario"]["monthly_payment_delta"] == 300
    state = conversations.get("conv-chat")
    assert state.active_task is None
    assert state.active_scenario_id is None
    second_prompt = json.loads(model.calls[1]["messages"][1]["content"])
    assert second_prompt["previous_question"] == "每月还多少，还要还几个月？"
    assert second_prompt["existing_scenario"]["remaining_principal"] == 2400


def test_chat_maps_scenario_store_errors_to_structured_response() -> None:
    model = FakeChatModel([scenario_response()])
    api, _, _ = api_with_session(model)
    original_execute = api.app.state.tool_executor.execute

    def execute(tool_name, arguments):
        if tool_name == "simulate_new_installment":
            raise ScenarioNotFound("missing")
        return original_execute(tool_name, arguments)

    api.app.state.tool_executor.execute = execute
    response = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "如果我新增一笔分期，本金2400，每月300，8期，利率12%，会怎样？",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["error"]["code"] == "SCENARIO_NOT_FOUND"


def test_scenario_clarification_limit_stops_before_model(monkeypatch) -> None:
    monkeypatch.setenv("MAX_CLARIFICATION_TURNS", "1")
    model = FakeChatModel([partial_scenario_response(), partial_scenario_response()])
    api, _, conversations = api_with_session(model)

    first = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "如果我新增一笔手机分期，本金2400，会怎样？",
        },
    ).json()
    second = api.post(
        "/api/v1/agent/chat",
        json={"conversation_id": "conv-chat", "message": "每月还300。"},
    ).json()
    third = api.post(
        "/api/v1/agent/chat",
        json={"conversation_id": "conv-chat", "message": "还要还8期。"},
    ).json()

    assert first["clarification_turns"] == 0
    assert second["status"] == "needs_more_info"
    assert second["clarification_turns"] == 1
    assert third["status"] == "clarification_limit"
    assert third["clarification_turns"] == 1
    assert len(model.calls) == 2
    state = conversations.get("conv-chat")
    assert state.active_task == "scenario"
    assert state.active_scenario_id is not None


def test_explicit_out_of_scope_stays_blocked_during_scenario_clarification() -> None:
    model = FakeChatModel([partial_scenario_response()])
    api, _, conversations = api_with_session(model)
    api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "如果我新增一笔手机分期，本金2400，会怎样？",
        },
    )

    response = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "推荐一个借款平台，哪家通过率高？",
        },
    ).json()

    assert response["status"] == "out_of_scope"
    assert len(model.calls) == 1
    assert conversations.get("conv-chat").active_task == "scenario"


def test_chat_out_of_scope_never_recommends_a_lender() -> None:
    model = FakeChatModel([])
    api = TestClient(create_app(llm_client=model))

    response = api.post(
        "/api/v1/agent/chat",
        json={"message": "推荐一个借款平台，哪个贷款通过率高？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "out_of_scope"
    assert "不能推荐" in body["reply"]
    assert len(model.calls) == 0


def test_chat_multi_turn_routes_risk_then_scenario() -> None:
    model = FakeChatModel([tool_call_response, explanation_response(), scenario_response()])
    api, _, _ = api_with_session(model)

    first = api.post(
        "/api/v1/agent/chat",
        json={"conversation_id": "conv-chat", "message": "为什么我是中风险？"},
    )
    second = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": "conv-chat",
            "message": "如果我新增一笔分期，本金2400，每月300，8期，利率12%，会怎样？",
        },
    )

    assert first.json()["status"] == "completed"
    assert second.json()["status"] == "completed"
    assert second.json()["scenario"]["risk_score_delta"] >= 0
    assert len(model.calls) == 3


def intake_response() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": "complete",
                            "draft": {
                                "income": {
                                    "monthly_disposable_allowance": 2200,
                                    "monthly_part_time_income": 800,
                                },
                                "debts": [
                                    {
                                        "label": "购物分期",
                                        "remaining_principal": 4800,
                                        "monthly_payment": 520,
                                        "remaining_periods": 10,
                                        "nominal_apr": 0.12,
                                    }
                                ],
                                "no_debts": False,
                            },
                            "missing_fields": [],
                            "warnings": [],
                            "question": None,
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def test_intake_confirm_creates_context_for_follow_up() -> None:
    model = FakeChatModel(
        [
            intake_response(),
            tool_call_response,
            explanation_response(),
            tool_call_response,
            explanation_response(),
        ]
    )
    api = TestClient(create_app(llm_client=model))

    intake = api.post(
        "/api/v1/agent/intake",
        json={"message": "我每个月生活费2200，兼职800，购物分期货款520，还剩10期，利率12%。"},
    )
    conversation_id = intake.json()["conversation_id"]
    confirmed = api.post(f"/api/v1/agent/intake/{conversation_id}/confirm")
    follow_up = api.post(
        "/api/v1/agent/chat",
        json={"conversation_id": conversation_id, "message": "为什么我是中风险？"},
    )

    assert intake.json()["status"] == "ready_for_confirmation"
    assert confirmed.json()["status"] == "completed"
    assert follow_up.json()["status"] == "completed"
    assert follow_up.json()["tool_activity"][0]["tool"] == "run_risk_assessment"
    assert len(model.calls) == 5


def test_scenario_without_session_asks_for_assessment_first() -> None:
    model = FakeChatModel([])
    api = TestClient(create_app(llm_client=model))

    response = api.post(
        "/api/v1/agent/chat",
        json={"message": "如果我新增一笔分期会怎样？"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_more_info"
    assert "先提供" in response.json()["reply"]
    assert len(model.calls) == 0

def test_unsafe_education_answer_falls_back_to_card_content() -> None:
    unsafe = education_response()
    payload = json.loads(unsafe["choices"][0]["message"]["content"])
    payload["key_point_indices"] = [99]
    unsafe["choices"][0]["message"]["content"] = json.dumps(payload, ensure_ascii=False)
    model = FakeChatModel([unsafe])
    api = TestClient(create_app(llm_client=model))

    response = api.post("/api/v1/agent/chat", json={"message": "什么是IRR？"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "education_answer"
    assert body["reply"]
    assert body["review_status"] == "pending"
    assert body["education"]["source_excerpts"]
def test_chat_natural_language_description_routes_to_intake() -> None:
    model = FakeChatModel([intake_response()])
    api = TestClient(create_app(llm_client=model))

    response = api.post(
        "/api/v1/agent/chat",
        json={
            "message": (
                "我每个月生活费2200，兼职800，购物分期本金4800，"
                "每月520，还剩10期，名义利率12%。"
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready_for_confirmation"
    assert body["conversation_id"]
    assert body["missing_fields"] == []
    assert len(model.calls) == 1
def partial_intake_response() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": "needs_more_info",
                            "draft": {
                                "income": {
                                    "monthly_disposable_allowance": 2000,
                                    "monthly_part_time_income": 500,
                                },
                                "debts": [
                                    {
                                        "label": "花呗",
                                        "monthly_payment": 300,
                                    }
                                ],
                                "no_debts": False,
                            },
                            "missing_fields": [
                                "debts[0].remaining_principal",
                                "debts[0].remaining_periods",
                            ],
                            "warnings": [],
                            "question": "这笔花呗现在大概还欠多少钱？还要还几个月？",
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def test_chat_clarification_uses_only_pending_question_not_full_history(caplog) -> None:
    model = FakeChatModel([partial_intake_response(), partial_intake_response()])
    app = create_app(llm_client=model)
    api = TestClient(app)
    private_marker = "隐私标记-不要进入第二轮模型"

    with caplog.at_level("DEBUG"):
        first = api.post(
            "/api/v1/agent/chat",
            json={"message": f"我每个月生活费2000，兼职500，花呗月供300。{private_marker}"},
        )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["status"] == "needs_more_info"
    assert first_body["clarification_turns"] == 0
    assert first_body["remaining_clarification_turns"] == 8

    second = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": first_body["conversation_id"],
            "message": "那再补一个，这笔还欠1000，还要还5个月。",
        },
    )
    assert second.status_code == 200
    assert second.json()["status"] == "needs_more_info"

    second_prompt = json.loads(model.calls[1]["messages"][1]["content"])
    assert second_prompt["previous_question"] == first_body["reply"]
    assert second_prompt["user_message"].startswith("那再补一个")
    assert private_marker not in json.dumps(second_prompt, ensure_ascii=False)
    assert private_marker not in caplog.text

    memory = app.state.chat_memory_store.get_optional(first_body["conversation_id"])
    assert memory is not None
    assert len(memory.messages) <= 4


def test_delete_conversation_clears_chat_memory_and_structured_context() -> None:
    model = FakeChatModel([education_response()])
    app = create_app(llm_client=model)
    api = TestClient(app)

    response = api.post("/api/v1/agent/chat", json={"message": "什么是IRR？"})
    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]
    assert app.state.chat_memory_store.get_optional(conversation_id) is not None
    assert app.state.conversation_store.get_optional(conversation_id) is not None

    deleted = api.delete(f"/api/v1/agent/conversations/{conversation_id}")

    assert deleted.status_code == 204
    assert app.state.chat_memory_store.get_optional(conversation_id) is None
    assert app.state.conversation_store.get_optional(conversation_id) is None


def test_delete_conversation_cascades_to_session_and_scenarios() -> None:
    model = FakeChatModel([])
    api, sessions, conversations = api_with_session(model)
    scenarios = api.app.state.scenario_store
    scenarios.create(
        "sc-conv-chat",
        ScenarioDraft(label="新手机", remaining_principal=2400),
        conversation_id="conv-chat",
        session_id="chat-demo",
        missing_fields=["monthly_payment", "remaining_periods"],
    )

    deleted = api.delete("/api/v1/agent/conversations/conv-chat")

    assert deleted.status_code == 204
    assert conversations.get_optional("conv-chat") is None
    assert len(sessions) == 0
    assert len(scenarios) == 0
def test_chat_clarification_limit_returns_friendly_exit_without_model_call(monkeypatch) -> None:
    monkeypatch.setenv("MAX_CLARIFICATION_TURNS", "1")
    model = FakeChatModel([partial_intake_response(), partial_intake_response()])
    api = TestClient(create_app(llm_client=model))

    first = api.post(
        "/api/v1/agent/chat",
        json={"message": "我每个月生活费2000，兼职500，花呗月供300。"},
    ).json()
    second = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": first["conversation_id"],
            "message": "那再补一个，月供是三百。",
        },
    ).json()
    third = api.post(
        "/api/v1/agent/chat",
        json={
            "conversation_id": first["conversation_id"],
            "message": "继续补充。",
        },
    ).json()

    assert first["clarification_turns"] == 0
    assert second["status"] == "needs_more_info"
    assert second["clarification_turns"] == 1
    assert third["status"] == "clarification_limit"
    assert third["clarification_turns"] == 1
    assert third["remaining_clarification_turns"] == 0
    assert "结构化表单" in third["reply"]
    assert "重新开始" in third["reply"]
    assert third["tool_activity"] == []
    assert len(model.calls) == 2
