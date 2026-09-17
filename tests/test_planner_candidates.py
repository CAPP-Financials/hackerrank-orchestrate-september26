import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import planner

STREAMS = {}  # no recurring streams -- isolates this test to the candidate-gate logic

PROFILE = {
    "current_available_balance": 10000.0,
    "minimum_balance_to_keep": 1000.0,
    "payment_methods_user_will_consider": {"full_payment"},
    "max_installment_months": None,
    "expense_categories_user_is_willing_to_reduce": set(),
    "expense_categories_user_is_willing_to_stop": set(),
    "expense_categories_to_protect": set(),
}

REQUEST = {
    "request_date": "2026-01-01",
    "desired_completion_date": "2026-01-01",
    "requested_amount": 5000.0,
    "allows_partial_payment": False,
    "_options": [],
}


def test_generate_candidates_returns_full_payment_when_safe():
    request_date = datetime.date(2026, 1, 1)
    candidates = planner.generate_candidates(
        STREAMS, PROFILE, REQUEST, safe_amt=5000.0, earliest=request_date
    )
    assert len(candidates) == 1
    assert candidates[0]["method"] == "full_payment"
    assert candidates[0]["changes"] == []
    assert candidates[0]["total_paid"] == 5000.0


def test_generate_candidates_excludes_ineligible_methods():
    profile = dict(PROFILE, payment_methods_user_will_consider={"installments"})
    request_date = datetime.date(2026, 1, 1)
    candidates = planner.generate_candidates(
        STREAMS, profile, REQUEST, safe_amt=5000.0, earliest=request_date
    )
    # no installment options supplied in REQUEST["_options"], full_payment not
    # in accepted methods -> no candidates at all
    assert candidates == []


def test_decide_unchanged_after_extraction():
    request_date = datetime.date(2026, 1, 1)
    result = planner.decide(STREAMS, PROFILE, dict(REQUEST))
    assert result["affordability_status"] == "affordable_now"
    assert result["recommended_payment_method"] == "full_payment"
    assert result["amount_safe_to_pay"] == "5000"
    assert "_all_candidates" in result
    assert len(result["_all_candidates"]) == 1
