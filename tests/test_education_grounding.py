from __future__ import annotations

import json
from typing import Any

from riskguard.services.education_service import EducationService


class FakeEducationModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(self.payload, ensure_ascii=False)
                    }
                }
            ]
        }


def test_education_answer_is_composed_only_from_selected_card_items() -> None:
    model = FakeEducationModel(
        {
            "topic_id": "irr_real_cost",
            "key_point_indices": [1],
            "action_indices": [2],
        }
    )
    service = EducationService(llm_client=model)
    card = service.get_topic("irr_real_cost")

    answer = service.answer(question="什么是IRR？", topic_id=card.topic_id)

    assert answer.source_excerpts == [card.key_points[0], card.allowed_actions[1]]
    assert answer.answer == "；".join(answer.source_excerpts)
    assert answer.review_status == "pending"


def test_education_model_cannot_add_freeform_content() -> None:
    model = FakeEducationModel(
        {
            "topic_id": "irr_real_cost",
            "key_point_indices": [1],
            "action_indices": [],
            "answer": "IRR代表未来收益。",
        }
    )
    service = EducationService(llm_client=model)
    card = service.get_topic("irr_real_cost")

    answer = service.answer(question="什么是IRR？", topic_id=card.topic_id)

    assert "未来收益" not in answer.answer
    assert all(
        item in card.key_points or item in card.allowed_actions
        for item in answer.source_excerpts
    )


def test_all_education_cards_remain_pending_until_signoff() -> None:
    service = EducationService(llm_client=FakeEducationModel({}))

    assert len(service.list_topics()) == 10
    assert all(card.review_status == "pending" for card in service.list_topics())
