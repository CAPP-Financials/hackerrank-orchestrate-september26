"""
Stage 9 (text half): decision_explanation templates -- deterministic string
assembly, not generation. Six confirmed shapes from the 25 samples (SS F.3
of the architecture doc), plus a partial_payment template extrapolated from
the same family (no sample precedent existed for it before the plan's
change-scope-expansion decision; composed from confirmed fragments per that
decision, not invented from scratch). Official success criteria only asks
for "usefulness and consistency," not exact-string match -- this aims for
that, not byte-identical oracle text.
"""
import datetime


def _money(amount, currency):
    """<CUR> <value>, comma thousands separators, 2dp only when fractional."""
    if amount == int(amount):
        return f"{currency} {int(amount):,}"
    return f"{currency} {amount:,.2f}"


def _prose_date(d):
    """'8 August 2025' -- no leading zero, never ISO."""
    return f"{d.day} {d.strftime('%B')} {d.year}"


def explain(result, request, profile, streams_by_desc=None):
    cur = profile["home_currency"]
    minb = profile["minimum_balance_to_keep"]
    req_amt = request["requested_amount"]
    final = result["_final"]
    status = result["affordability_status"]
    method = result["recommended_payment_method"]

    if status == "not_affordable":
        accepted = profile["payment_methods_user_will_consider"]
        if accepted == {"partial_payment"} and request["allows_partial_payment"]:
            return (f"Do not proceed with the {_money(req_amt, cur)} request. "
                    f"Although {_money(result['_safe_amt'], cur)} is available today, "
                    f"the full amount cannot be completed safely within 90 days.")
        dcd = datetime.date.fromisoformat(request["desired_completion_date"])
        return (f"Do not make this payment by {_prose_date(dcd)}. "
                f"None of the available options keeps the {_money(minb, cur)} minimum protected.")

    change_clause = _change_clause(final["changes"], cur)

    if status == "affordable_now":
        return (f"Pay {_money(req_amt, cur)} today. "
                f"This leaves at least {_money(minb, cur)} available over the next 90 days.")

    if status == "affordable_later":
        d = final["plan"][0][0]
        return (f"Pay {_money(req_amt, cur)} in full on {_prose_date(d)}. "
                f"Paying earlier would take the balance below the {_money(minb, cur)} minimum.")

    # affordable_with_plan
    if method == "installments":
        n = final["n_payments"]
        amt = final["plan"][0][1]
        start = final["plan"][0][0]
        return (f"Use {n} installments of {_money(amt, cur)}, starting {_prose_date(start)}. "
                f"This leaves at least {_money(minb, cur)} available.")
    if method == "partial_payment":
        d1, a1 = final["plan"][0]
        d2, a2 = final["plan"][1]
        return (f"Pay {_money(a1, cur)} today and {_money(a2, cur)} on {_prose_date(d2)}. "
                f"This leaves at least {_money(minb, cur)} available.")
    if method == "full_payment":
        prefix = f"{change_clause}, then " if change_clause else ""
        return (f"{prefix}pay {_money(req_amt, cur)} today. "
                f"This leaves at least {_money(minb, cur)} available.")
    return "Recommendation computed from the 90-day forecast."


def _change_clause(changes, cur):
    if not changes:
        return ""
    parts = []
    for c in changes:
        desc = c.get("_sub_stream", {}).get("desc", c["stream_key"]).lower()
        if c["verb"] == "stop":
            parts.append(f"Stop the {desc}")
        else:
            parts.append(f"Reduce the {desc} to {_money(c['new_amount'], cur)}")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"
