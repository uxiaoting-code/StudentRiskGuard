from __future__ import annotations

import pytest

from riskguard.core.irr import compute_debt_irr
from riskguard.models import Debt


def test_docs_irr_example_is_reproduced() -> None:
    debt = Debt(
        id="d1",
        label="购物分期",
        remaining_principal=4800,
        monthly_payment=520,
        remaining_periods=10,
        nominal_apr=0.12,
    )

    result = compute_debt_irr(debt)

    assert result.status == "ok"
    assert result.monthly_irr == pytest.approx(0.01482441, abs=1e-8)
    assert result.annualized_irr == pytest.approx(0.19313849, abs=1e-8)


def test_zero_cost_debt_returns_zero_irr() -> None:
    debt = Debt(
        id="zero",
        label="零成本分期",
        remaining_principal=1200,
        monthly_payment=200,
        remaining_periods=6,
        nominal_apr=0,
    )

    result = compute_debt_irr(debt)

    assert result.status == "ok"
    assert result.monthly_irr == pytest.approx(0)
    assert result.annualized_irr == pytest.approx(0)


def test_irr_uses_effective_annualization() -> None:
    debt = Debt(
        id="d2",
        label="数码分期",
        remaining_principal=2600,
        monthly_payment=380,
        remaining_periods=8,
        nominal_apr=0.18,
    )

    result = compute_debt_irr(debt)

    assert result.status == "ok"
    assert result.monthly_irr == pytest.approx(0.0361141, abs=1e-8)
    assert result.annualized_irr == pytest.approx(
        (1 + result.monthly_irr) ** 12 - 1
    )
