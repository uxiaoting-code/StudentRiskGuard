"""Fixed prompts for the M4 interaction Agent."""

from __future__ import annotations

import json
from typing import Any

from riskguard.agent.schemas import (
    AssessmentDraft,
    EducationCard,
    EducationSelection,
    ExtractionResult,
    ScenarioExtractionResult,
)
from riskguard.models import (
    FIXED_BOUNDARY_NOTICE,
    AssessmentRequest,
    Explanation,
)

TOOL_SYSTEM_PROMPT = """你是 StudentRiskGuard 的工具调度 Agent。
你只负责对当前匿名会话调用 run_risk_assessment 工具，不得自行计算任何数值。
工具参数只能是 session_id，不能请求或输出收入、债务、订阅等原始明细。
必须先调用工具，再等待后端返回 AssessmentResult。"""

EXTRACTION_SYSTEM_PROMPT = """你是 StudentRiskGuard 的自然语言信息抽取 Agent。
你的唯一任务是把大学生关于收入、分期、订阅和现金流的自然语言描述整理成结构化草稿。
你不进行任何金融计算，不判断风险等级，不提供借贷或投资建议。

严格遵守：
1. 只输出严格 JSON，不要 Markdown 代码围栏、前后说明或注释。
2. 只能使用提供的 ExtractionResult Schema 和 AssessmentRequest Schema 中的字段。
3. 禁止新增字段、拼写变体或隐藏字段。
4. 金额单位统一为人民币元。
5. 利率使用小数，例如 12% 写成 0.12，不能写成 12。
6. 月供不是本金；不能把同一数字同时猜成本金和月供。
7. 不得编造缺失的本金、月供、期数、利率、收入或订阅金额。
8. 用户明确说没有分期时，debts 为空数组且 no_debts=true。
9. 用户没有提到是否有分期的，debts 和 no_debts 保持 null，不能擅自假设没有负债。
10. 用户说“剩余期数为0”“已经还完”“已结清”时，将该笔债务标记为 settled=true，不要要求本金、月供、期数或利率，不要把它当作正在还款债务。
11. 会员、订阅、自动续费、连续包月、每月扣费、月费属于 recurring_subscriptions，不属于 debts；订阅只需要 label 和 monthly_cost。
12. 信息不足时 status=needs_more_info；只有存在正在还款中的分期且关键信息缺失时，才索要分期信息。
13. 数值非法时 status=invalid，在 warnings 中说明原因。
14. 只有所有必填字段完整且合法时，status 才能是 complete。
15. existing_draft 是已经确认或已经抽取的草稿；返回时必须保留其中非空字段，除非用户明确纠正。
16. 用户补充信息时，只更新用户新提到的字段，不要删除 existing_draft 中已有值。
17. question 必须使用普通大学生能理解的大白话，禁止写字段名、JSON key、数组下标，例如 debts[0].remaining_periods、nominal_apr、monthly_payment。
18. previous_question 是上一轮尚未回答的问题，只用于理解用户这次补充了什么，不要把它当作用户新提供的数据。
19. 可以使用当前轮消息、existing_draft 和 previous_question，但不要依赖完整聊天历史，也不要要求系统提供完整历史。
20. 用户纠正已有字段时以本轮明确表达为准；用户没有提到的已知字段必须保留。
21. 不要编造用户没有提供的金额、期数、利率或订阅费用；不要重复询问 existing_draft 中已经存在的字段。
22. 已结清负债和订阅规则不得回退：已结清记录不进入正式债务，订阅只进入 recurring_subscriptions。
23. 用户明确说利率“不知道、不清楚、没告诉我”时，nominal_apr 必须为 null，nominal_apr_status 必须为 unknown；不能写成 0，其他字段完整时仍可返回 complete。
24. 用户尚未提到利率时，nominal_apr_status 使用 not_mentioned；用户提供了具体利率时使用 provided。
25. 不要输出用户原文，不要复述整段自然语言。"""

EXPLANATION_SYSTEM_PROMPT = f"""你是 StudentRiskGuard 的交互推理 Agent，面向中国在校大学生提供负债压力自查和理性消费科普。
你只接收结构化 AssessmentResult，不接收原始聊天文本、完整聊天历史或完整财务档案。

严格遵守：
1. 你只解释工具返回的 AssessmentResult，不进行计算。
2. 不得修改、补全或创造任何金额、利率、分数、期数、概率和现金流数值。
3. 不得输出贷款审批、授信额度、通过率、放款建议或借贷产品推荐。
4. 不得推荐具体平台、品牌、分期产品或投资产品。
5. 不得提供“以贷养贷”方案，不得承诺收益或保证解决债务。
6. 建议只围绕预算核对、真实成本理解、与家人沟通、寻求校园支持和理性消费。
7. risk_sources 必须引用工具结果中的 dimension_id。
8. 只输出严格 JSON，不要 Markdown 代码围栏或额外说明。
9. 不重复任何阿拉伯数字；具体数值由前端从 AssessmentResult 渲染。
10. boundary_notice 必须逐字等于：
{FIXED_BOUNDARY_NOTICE}
11. 输出字段必须完整符合提供的 Explanation Schema。
12. risk_sources 只用于选择证据维度；后端会丢弃自由文本，并根据合法 dimension_id 重新组装最终解释。
13. 不要输出任何未经工具结果授权的金额、利率、期数、概率、审批、额度或放款事实。"""


def build_tool_messages(session_id: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": TOOL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "对当前匿名会话执行负债压力评估，必须先调用 run_risk_assessment。",
                    "session_id": session_id,
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_extraction_messages(
    *,
    user_message: str,
    existing_draft: AssessmentDraft | None = None,
    previous_question: str | None = None,
) -> list[dict[str, Any]]:
    """Build the one extraction request. Raw text goes only to this model call."""

    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "从本轮用户消息中抽取或补充评估草稿。",
                    "existing_draft": (
                        existing_draft.model_dump(mode="json", exclude_none=True)
                        if existing_draft is not None
                        else None
                    ),
                    "previous_question": previous_question,
                    "extraction_result_schema": ExtractionResult.model_json_schema(),
                    "assessment_request_schema": AssessmentRequest.model_json_schema(),
                    "user_message": user_message,
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_explanation_messages(
    *,
    session_id: str,
    assistant_message: dict[str, Any],
    tool_result: dict[str, Any],
) -> list[dict[str, Any]]:
    tool_call_id = assistant_message["tool_calls"][0]["id"]
    return [
        {"role": "system", "content": EXPLANATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "基于工具结果生成学生可理解的风险解释，不要重新计算。",
                    "session_id": session_id,
                    "explanation_schema": Explanation.model_json_schema(),
                },
                ensure_ascii=False,
            ),
        },
        assistant_message,
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(tool_result, ensure_ascii=False),
        },
    ]


EDUCATION_SYSTEM_PROMPT = f"""你是 StudentRiskGuard 的金融教育回答 Agent。
你不生成自由文本，只能从提供的 EducationCard 中选择来源片段编号。

严格遵守：
1. key_point_indices 使用从 1 开始的编号，只能选 key_points 中已有的项目。
2. action_indices 使用从 1 开始的编号，只能选 allowed_actions 中已有的项目；最多选一项，也可以不选。
3. 不得生成、改写或补全任何金融事实、建议或数字。
4. 不推荐具体平台、品牌、分期产品或投资产品。
5. 不承诺收益，不承诺解决债务，不提供以贷养贷方案。
6. 不判断贷款审批、授信额度、通过率或放款结果。
7. 只输出严格 JSON，不要 Markdown 代码围栏。
8. topic_id 必须等于当前卡片 topic_id。
9. 输出字段必须符合 EducationSelection Schema。
10. boundary_notice 由后端逐字添加，模型不得生成。"""


def build_education_messages(
    *,
    question: str,
    card: EducationCard,
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": EDUCATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "只基于这张教育卡片回答用户问题。",
                    "education_card": card.model_dump(mode="json"),
                    "selection_schema": EducationSelection.model_json_schema(),
                    "user_question": question,
                },
                ensure_ascii=False,
            ),
        },
    ]


SCENARIO_EXTRACTION_SYSTEM_PROMPT = """你是 StudentRiskGuard 的情景模拟信息抽取 Agent。
你的任务是从用户关于“如果新增一笔分期会怎样”的自然语言中提取新增分期字段。
你不进行任何风险计算，也不推荐借贷产品或平台。

严格遵守：
1. 只输出严格 JSON，不要 Markdown 代码围栏。
2. 只能输出 ScenarioExtractionResult Schema 中的字段。
3. 金额单位为人民币元，利率使用小数，例如 12% 写成 0.12。
4. 不得编造缺失的本金、月供、期数或利率。
5. 信息不足返回 needs_more_info，并在 missing_fields 和 question 中说明。
6. 数值非法返回 invalid。
7. 该类问题只用于数学情景模拟，不代表真实借款建议。
8. 只抽取用户明确描述的新增分期，不要修改已有会话数据。
9. 用户明确说利率“不知道、不清楚、没告诉我”时，nominal_apr 必须为 null，不能写成 0；只要本金、月供和期数完整，状态仍可为 complete。"""


def build_scenario_extraction_messages(
    *,
    user_message: str,
    existing_scenario: dict[str, Any] | None = None,
    previous_question: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SCENARIO_EXTRACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "提取新增分期情景字段。",
                    "scenario_result_schema": ScenarioExtractionResult.model_json_schema(),
                    "existing_scenario": existing_scenario,
                    "previous_question": previous_question,
                    "user_message": user_message,
                },
                ensure_ascii=False,
            ),
        },
    ]
