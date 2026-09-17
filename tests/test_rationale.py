import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import rationale

STREAMS = {}

PROFILE = {
    "current_available_balance": 10000.0,
    "minimum_balance_to_keep": 1000.0,
    "payment_methods_user_will_consider": {"full_payment"},
    "max_installment_months": None,
    "home_currency": "USD",
    "expense_categories_user_is_willing_to_reduce": set(),
    "expense_categories_user_is_willing_to_stop": set(),
    "expense_categories_to_protect": set(),
}

REQUEST = {
    "request_id": "request_test_1",
    "request_date": "2026-01-01",
    "desired_completion_date": "2026-01-01",
    "requested_amount": 5000.0,
    "allows_partial_payment": False,
    "_options": [],
}


def test_build_rationale_happy_path():
    rat = rationale.build_rationale(dict(REQUEST), PROFILE, STREAMS)
    assert rat.request_id == "request_test_1"
    assert rat.affordability_status == "affordable_now"
    assert rat.recommended_payment_method == "full_payment"
    assert rat.earliest_date_for_full_payment == "2026-01-01"
    assert rat.decision_explanation  # non-empty
    assert len(rat.all_candidates) == 1

    row = rat.as_row()
    assert list(row.keys()) == [
        "request_id", "amount_safe_to_pay", "affordability_status",
        "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
        "spending_changes_needed", "decision_explanation",
    ]


def test_build_rationale_raises_on_bad_status_method_pair(monkeypatch):
    import planner

    def broken_decide(streams, profile, request):
        return {
            "amount_safe_to_pay": "5000", "affordability_status": "affordable_now",
            "recommended_payment_method": "wait",  # invalid pairing on purpose
            "payment_plan": "2026-01-01:5000", "earliest_date_for_full_payment": "2026-01-01",
            "spending_changes_needed": "none", "_final": None, "_all_candidates": [],
            "_safe_amt": 5000.0, "_earliest": datetime.date(2026, 1, 1),
        }

    monkeypatch.setattr(planner, "decide", broken_decide)
    try:
        rationale.build_rationale(dict(REQUEST), PROFILE, STREAMS)
        assert False, "expected InvariantError"
    except rationale.InvariantError as e:
        assert "affordable_now" in str(e) and "wait" in str(e)


def test_build_rationale_raises_on_out_of_bounds_safe_amount(monkeypatch):
    import planner

    def broken_decide(streams, profile, request):
        return {
            "amount_safe_to_pay": "9999999", "affordability_status": "affordable_now",
            "recommended_payment_method": "full_payment",
            "payment_plan": "2026-01-01:5000", "earliest_date_for_full_payment": "2026-01-01",
            "spending_changes_needed": "none", "_final": {"method": "full_payment", "changes": []},
            "_all_candidates": [], "_safe_amt": 9999999.0, "_earliest": datetime.date(2026, 1, 1),
        }

    monkeypatch.setattr(planner, "decide", broken_decide)
    try:
        rationale.build_rationale(dict(REQUEST), PROFILE, STREAMS)
        assert False, "expected InvariantError"
    except rationale.InvariantError as e:
        assert "I-1" in str(e)
