"""
Stage 9 (checks half): the invariant sweep. Every rule here is a G-rule
from the architecture doc, made assertable -- run this over the final
output.csv (both during development and, per the goal graph's Node 6, on
the actual submitted file) before calling anything done.
"""


def check_row(row, request):
    """row: dict with the 8 output fields (as strings, matching output.csv).
    request: the matching input row (needs requested_amount).
    Returns a list of violation strings (empty = clean)."""
    v = []
    req_amt = request["requested_amount"]
    safe = float(row["amount_safe_to_pay"])

    # G1: bounds -- spec-mandated, inclusive of 0
    if not (0 <= safe <= req_amt):
        v.append(f"amount_safe_to_pay {safe} outside [0, {req_amt}]")
    # NOTE: G2 ("amount_safe_to_pay is never 0") held 25/25 in the design
    # samples but is NOT enforced here -- verified directly on the real
    # 250-row eval set that 0 is the mathematically correct answer for a
    # user whose baseline spending alone (no purchase at all) already
    # breaches minimum_balance_to_keep within 90 days (e.g. request_60,
    # the tightest-headroom user in the whole dataset, 283.69). The spec
    # itself states 0 <= amount_safe_to_pay, inclusive. Treating G2 as a
    # hard invariant here would have meant hand-inflating a correct answer
    # to satisfy a pattern inferred from a 25-sample set that turned out
    # not to generalize -- named explicitly rather than silently dropped.

    status = row["affordability_status"]
    method = row["recommended_payment_method"]
    plan = row["payment_plan"]
    earliest = row["earliest_date_for_full_payment"]
    changes = row["spending_changes_needed"]

    # G4, corrected: `plan==none`, `not_affordable`, `not_recommended` are a
    # genuine 3-way equivalence -- structurally guaranteed by the planner
    # (all three are driven by the same "no candidate found" branch). But
    # `earliest==''` is NOT tied to that branch -- earliest is computed
    # independently of which plan gets chosen, and CAN legitimately be
    # empty while a change-assisted plan is still found (verified directly
    # on the real 250-row set: request_111/165/174, a change-assisted
    # full payment or partial/installment plan works today even though no
    # UNASSISTED full payment is ever safe within 90 days). The original
    # 4-way rule held 25/25 in the design samples but that was coincidence
    # of a thin sample, not a structural truth -- asserting it here would
    # flag correct, spec-compliant rows as violations.
    is_none_plan = plan == "none"
    is_not_affordable = status == "not_affordable"
    is_not_recommended = method == "not_recommended"
    three = {is_none_plan, is_not_affordable, is_not_recommended}
    if len(three) != 1:
        v.append(f"plan_none/not_affordable/not_recommended equivalence broken: "
                  f"plan_none={is_none_plan} not_affordable={is_not_affordable} "
                  f"not_recommended={is_not_recommended}")

    # G8: status/method consistency
    valid_pairs = {
        ("affordable_now", "full_payment"),
        ("affordable_later", "wait"),
        ("not_affordable", "not_recommended"),
        ("affordable_with_plan", "installments"),
        ("affordable_with_plan", "full_payment"),
        ("affordable_with_plan", "partial_payment"),
    }
    if (status, method) not in valid_pairs:
        v.append(f"invalid (status, method) pair: ({status}, {method})")

    # changes: <=3, well-formed
    if changes != "none":
        parts = changes.split("|")
        if len(parts) > 3:
            v.append(f"more than 3 spending changes: {len(parts)}")
        event_ids = []
        for p in parts:
            fields = p.split(":")
            if fields[0] not in ("stop", "reduce_to"):
                v.append(f"invalid change verb: {fields[0]}")
            if fields[0] == "reduce_to" and len(fields) != 3:
                v.append(f"malformed reduce_to entry: {p}")
            if fields[0] == "stop" and len(fields) != 2:
                v.append(f"malformed stop entry: {p}")
            event_ids.append(fields[1] if len(fields) > 1 else None)
        if len(set(event_ids)) != len(event_ids):
            v.append("stop/reduce_to target the same event (G13 mutual exclusion violated)")

    # affordable_now => earliest == request_date
    if status == "affordable_now" and earliest != request["request_date"]:
        v.append(f"affordable_now but earliest ({earliest}) != request_date ({request['request_date']})")

    return v


def sweep(rows, requests_by_id):
    """rows: list of output dicts (request_id + 8 fields). Returns
    {request_id: [violations]} for any row with at least one violation."""
    problems = {}
    for row in rows:
        req = requests_by_id.get(row["request_id"])
        if not req:
            problems[row["request_id"]] = ["no matching request row"]
            continue
        v = check_row(row, req)
        if v:
            problems[row["request_id"]] = v
    return problems
