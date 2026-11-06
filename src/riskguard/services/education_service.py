"""Deterministic education-card retrieval and constrained answer generation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from riskguard.agent.deepseek import ChatModel
from riskguard.agent.prompts import build_education_messages
from riskguard.agent.schemas import EducationAnswer, EducationCard
from riskguard.models import FIXED_BOUNDARY_NOTICE


class EducationTopicNotFound(Exception):
    pass


class EducationService:
    """Load reviewed-card content and answer only from that content."""

    def __init__(
        self,
        *,
        llm_client: ChatModel,
        cards_path: Path | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._cards_path = cards_path or (
            Path(__file__).resolve().parents[1] / "data" / "education_cards.json"
        )
        self._cards = self._load_cards()

    def _load_cards(self) -> dict[str, EducationCard]:
        raw = json.loads(self._cards_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("education_cards.json must contain a list")
        cards = [EducationCard.model_validate(item) for item in raw]
        return {card.topic_id: card for card in cards}

    def list_topics(self) -> list[EducationCard]:
        return list(self._cards.values())

    def get_topic(self, topic_id: str) -> EducationCard:
        card = self._cards.get(topic_id)
        if card is None:
            raise EducationTopicNotFound(topic_id)
        return card

    def find_topic(self, message: str) -> EducationCard | None:
        normalized = message.lower()
        scored: list[tuple[int, EducationCard]] = []
        for card in self._cards.values():
            score = 0
            if card.title.lower() in normalized:
                score += 20
            for keyword in card.keywords:
                if keyword.lower() in normalized:
                    score += 5
            if score:
                scored.append((score, card))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def answer(self, *, question: str, topic_id: str) -> EducationAnswer:
        card = self.get_topic(topic_id)
        try:
            response = self._llm_client.complete(
                messages=build_education_messages(question=question, card=card),
                response_format={"type": "json_object"},
            )
            answer = self._parse_answer(response, card)
            if answer.topic_ids != [card.topic_id]:
                raise ValueError("education answer references the wrong topic")
            if self._is_safe(answer):
                return answer.model_copy(update={"review_status": card.review_status})
        except Exception:
            pass
        return self._fallback_answer(card)

    @staticmethod
    def _parse_answer(response: object, card: EducationCard) -> EducationAnswer:
        if not isinstance(response, dict):
            raise ValueError("education response is not an object")
        choices = response.get("choices")
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("education response has no choices")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("education response is empty")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]
        return EducationAnswer.model_validate_json(cleaned)

    @staticmethod
    def _is_safe(answer: EducationAnswer) -> bool:
        forbidden_terms = (
            "借款平台",
            "贷款平台",
            "推荐平台",
            "保证收益",
            "承诺收益",
            "保证解决",
            "审批通过",
            "授信额度",
            "放款",
            "以贷养贷",
        )
        if any(term in answer.answer for term in forbidden_terms):
            return False
        if re.search(r"\d", answer.answer):
            return False
        return True

    @staticmethod
    def _fallback_answer(card: EducationCard) -> EducationAnswer:
        return EducationAnswer(
            answer="；".join(card.key_points),
            topic_ids=[card.topic_id],
            boundary_notice=FIXED_BOUNDARY_NOTICE,
            review_status=card.review_status,
        )
