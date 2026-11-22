"""Deterministic education-card retrieval and constrained answer generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from riskguard.agent.schemas import EducationAnswer, EducationCard, EducationSelection
from riskguard.models import FIXED_BOUNDARY_NOTICE

if TYPE_CHECKING:
    from riskguard.agent.deepseek import ChatModel


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

    def find_topics(self, message: str, *, limit: int = 3) -> list[EducationCard]:
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
        scored.sort(key=lambda item: item[0], reverse=True)
        return [card for _, card in scored[:limit]]

    def find_topic(self, message: str) -> EducationCard | None:
        topics = self.find_topics(message, limit=1)
        return topics[0] if topics else None

    def answer_topics(
        self,
        *,
        question: str,
        topic_ids: list[str],
    ) -> EducationAnswer:
        answers = [self.answer(question=question, topic_id=topic_id) for topic_id in topic_ids]
        excerpts: list[str] = []
        all_topics: list[str] = []
        for item in answers:
            for excerpt in item.source_excerpts:
                if excerpt not in excerpts:
                    excerpts.append(excerpt)
            for topic_id in item.topic_ids:
                if topic_id not in all_topics:
                    all_topics.append(topic_id)
        excerpts = excerpts[:8]
        answer = "；".join(excerpts)
        from riskguard.agent.safety import is_safe_text


        if not is_safe_text(answer):
            return self._fallback_answer(self.get_topic(topic_ids[0]))
        return EducationAnswer(
            answer=answer,
            source_excerpts=excerpts,
            topic_ids=all_topics,
            boundary_notice=FIXED_BOUNDARY_NOTICE,
            review_status=(
                "approved"
                if all(self.get_topic(topic_id).review_status == "approved" for topic_id in all_topics)
                else "pending"
            ),
        )

    def answer(self, *, question: str, topic_id: str) -> EducationAnswer:
        card = self.get_topic(topic_id)
        try:
            from riskguard.agent.prompts import build_education_messages

            response = self._llm_client.complete(
                messages=build_education_messages(question=question, card=card),
                response_format={"type": "json_object"},
            )
            selection = self._parse_selection(response)
            if selection.topic_id != card.topic_id:
                raise ValueError("education answer references the wrong topic")
            return self._compose_answer(card, selection)
        except Exception:
            pass
        return self._fallback_answer(card)

    @staticmethod
    def _parse_selection(response: object) -> EducationSelection:
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
        return EducationSelection.model_validate_json(cleaned)

    @staticmethod
    def _select_items(indices: list[int], source: list[str]) -> list[str]:
        selected: list[str] = []
        for index in indices:
            if index < 1 or index > len(source):
                raise ValueError("education source index is out of range")
            item = source[index - 1]
            if item not in selected:
                selected.append(item)
        return selected

    @classmethod
    def _compose_answer(
        cls,
        card: EducationCard,
        selection: EducationSelection,
    ) -> EducationAnswer:
        excerpts = cls._select_items(
            selection.key_point_indices,
            card.key_points,
        )
        excerpts.extend(
            cls._select_items(
                selection.action_indices,
                card.allowed_actions,
            )
        )
        answer = "；".join(excerpts)
        if len(answer) > 1200:
            raise ValueError("composed education answer is too long")
        from riskguard.agent.safety import is_safe_text

        if not is_safe_text(answer):
            raise ValueError("composed education answer failed safety validation")
        return EducationAnswer(
            answer=answer,
            source_excerpts=excerpts,
            topic_ids=[card.topic_id],
            boundary_notice=FIXED_BOUNDARY_NOTICE,
            review_status=card.review_status,
        )

    @classmethod
    def _fallback_answer(cls, card: EducationCard) -> EducationAnswer:
        excerpts = list(card.key_points[:3])
        if card.allowed_actions:
            excerpts.append(card.allowed_actions[0])
        answer = "；".join(excerpts)
        from riskguard.agent.safety import is_safe_text

        if not is_safe_text(answer):
            excerpts = ["当前内容需要进一步审核，请先核对分期成本和现金流。"]
        return EducationAnswer(
            answer="；".join(excerpts),
            source_excerpts=excerpts,
            topic_ids=[card.topic_id],
            boundary_notice=FIXED_BOUNDARY_NOTICE,
            review_status=card.review_status,
        )
