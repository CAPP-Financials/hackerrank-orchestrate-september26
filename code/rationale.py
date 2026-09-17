"""
Single source of truth for every output column and decision_explanation.

Wraps planner.decide()'s existing decision logic and format.render_explanation()'s
existing text generation, then asserts the output contract's invariants at
CONSTRUCTION time -- a contradiction raises InvariantError instead of
reaching output.csv, where validate.py's post-hoc sweep (code/validate.py)
would otherwise be the only thing that could catch it, and only after the
full run finished. This mirrors the winning HackerRank Orchestrate
submission's reconcile.py: one rationale object feeds every output field,
see docs/CONTRACT.md.
"""
from dataclasses import dataclass

import format
import planner


class InvariantError(Exception):
    """A computed decision violates one of docs/CONTRACT.md's invariants.
    Always a bug in the decision logic upstream -- never a value to
    silently coerce or round away."""


@dataclass(frozen=True)
class Rationale:
    request_id: str
    amount_safe_to_pay: str
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str
    final_candidate: dict | None
    all_candidates: tuple
    safe_amount_raw: float
    earliest_date_raw: object  # datetime.date | None

    def as_row(self):
        """The 8 required CSV columns, in the required order."""
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": self.amount_safe_to_pay,
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": self.earliest_date_for_full_payment,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


_VALID_STATUS_METHOD_PAIRS = {
    ("affordable_now", "full_payment"),
    ("affordable_later", "wait"),
    ("not_affordable", "not_recommended"),
    ("affordable_with_plan", "installments"),
    ("affordable_with_plan", "full_payment"),
    ("affordable_with_plan", "partial_payment"),
}


def _check_invariants(result, request):
    status = result["affordability_status"]
    method = result["recommended_payment_method"]
    plan_str = result["payment_plan"]
    earliest_str = result["earliest_date_for_full_payment"]
    safe_amt = result["_safe_amt"]
    requested_amount = request["requested_amount"]

    # I-1 (docs/CONTRACT.md): 0 <= amount_safe_to_pay <= requested_amount
    if not (0 <= safe_amt <= requested_amount):
        raise InvariantError(f"I-1 violated: amount_safe_to_pay {safe_amt} outside [0, {requested_amount}]")

    # plan_none / not_affordable / not_recommended must be a 3-way equivalence
    three = {plan_str == "none", status == "not_affordable", method == "not_recommended"}
    if len(three) != 1:
        raise InvariantError(
            f"plan_none/not_affordable/not_recommended disagree: "
            f"plan_none={plan_str == 'none'} status={status} method={method}")

    # status/method must be a recognized pairing
    if (status, method) not in _VALID_STATUS_METHOD_PAIRS:
        raise InvariantError(f"invalid (status, method) pair: ({status}, {method})")

    # affordable_now must have earliest == request_date
    if status == "affordable_now" and earliest_str != request["request_date"]:
        raise InvariantError(
            f"affordable_now but earliest ({earliest_str}) != request_date ({request['request_date']})")


def build_rationale(request, profile, streams):
    """Runs the full decision pipeline for one request and returns the
    single Rationale object that is the sole source of every output
    column. Raises InvariantError instead of returning a contradictory
    row -- callers (main.py) should let this propagate; a caught
    InvariantError here means the decision logic has a bug, not that the
    request is unusual."""
    result = planner.decide(streams, profile, request)
    _check_invariants(result, request)
    explanation = format.render_explanation(result, request, profile)

    return Rationale(
        request_id=request["request_id"],
        amount_safe_to_pay=result["amount_safe_to_pay"],
        affordability_status=result["affordability_status"],
        recommended_payment_method=result["recommended_payment_method"],
        payment_plan=result["payment_plan"],
        earliest_date_for_full_payment=result["earliest_date_for_full_payment"],
        spending_changes_needed=result["spending_changes_needed"],
        decision_explanation=explanation,
        final_candidate=result["_final"],
        all_candidates=tuple(result["_all_candidates"]),
        safe_amount_raw=result["_safe_amt"],
        earliest_date_raw=result["_earliest"],
    )
