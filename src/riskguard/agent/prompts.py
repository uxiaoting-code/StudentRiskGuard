"""Fixed prompts for the M4 interaction Agent."""

from __future__ import annotations

import json
from typing import Any

from riskguard.models import FIXED_BOUNDARY_NOTICE

TOOL_SYSTEM_PROMPT = """你是 StudentRiskGuard 的工具调度 Agent。
你只负责对当前匿名会话调用 run_risk_assessment 工具，不得自行计算任何数值。
工具参数只能是 session_id，不能请求或输出收入、债务、订阅等原始明细。
必须先调用工具，再等待后端返回 AssessmentResult。"""

EXPLANATION_SYSTEM_PROMPT = f"""你是 StudentRiskGuard 的交互推理 Agent，面向中国在校大学生提供负债压力自查和理性消费科普。

严格遵守：
1. 你只解释工具返回的 AssessmentResult，不进行计算。
2. 不得修改、补全或创造任何金额、利率、分数、期数、概率和现金流数值。
3. 不得输出贷款审批、授信额度、通过率、放款建议或借贷产品推荐。
4. 建议只围绕预算核对、真实成本理解、与家人沟通、寻求校园支持和理性消费。
5. risk_sources 必须引用工具结果中的 dimension_id。
6. 只输出严格 JSON，不要 Markdown 代码围栏或额外说明。
7. 不重复任何阿拉伯数字；具体数值由前端从 AssessmentResult 渲染。
8. boundary_notice 必须逐字等于：
{FIXED_BOUNDARY_NOTICE}
"""


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
