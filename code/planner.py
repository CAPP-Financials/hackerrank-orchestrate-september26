"""
Stage 5-8: candidate plans, safety validation, eligibility filter, ranking.

Generates every eligible payment method (full / partial / each installment
option / wait), change-free first and then change-assisted for EVERY
method (not just full_payment -- decided explicitly during the grilling
session: restricting to full_payment only was pattern-matching the 25
samples' thin evidence, not a rule the data states), tests each against a
full re-forecast, and ranks by the spec's stated order.
"""
import datetime
import itertools
import math

import forecast

MAX_CHANGES = 3


def _payment_safe(streams, balance, min_balance, request_date, payments, overrides=None):
    """payments: list of (date, amount) debits. Re-forecasts with these
    payments injected as extra flows, returns (is_safe, trough)."""
    horizon = request_date + datetime.timedelta(days=forecast.HORIZON_DAYS)
    flows = forecast.project_flows(streams, request_date, horizon, overrides)
    flows = flows + [(d, -amt, "__payment__") for d, amt in payments]
    lo, _ = forecast.trough(balance, flows)
    return lo >= min_balance, lo


def _apply_changes_to_streams(base_streams, chosen_changes):
    """Build a modified streams dict + overrides for a chosen change set.

    For a pooled target, a diluted "daily rate share" approximation was
    tried first and verified WRONG (request_11: the oracle's single change
    closes the whole gap; stacking all 6 pooled sub-streams' diluted
    deltas together still didn't). The correct fix: split the pool at
    forecast time. Remove the target sub-stream's own occurrences from the
    pool (so the pool's rate reflects only the OTHER descriptions), then
    project the target sub-stream on its OWN cadence at the new amount --
    giving the change its true, undiluted effect, exactly as if it had
    never been pooled. `streams.py` already keeps each pooled stream's
    original un-pooled sub-streams (`_source_streams`) for exactly this."""
    streams = dict(base_streams)
    overrides = {}
    for c in chosen_changes:
        target = c["pooled_parent"]
        if target is None:
            key = c["stream_key"]
            if c["verb"] == "stop":
                overrides[key] = {"stopped_entirely": True}
            else:
                overrides[key] = {"new_amount": c["new_amount"]}
            continue

        sub = c["_sub_stream"]
        pool = streams[target]
        sub_event_ids = {ev["event_id"] for _, ev in sub["live"]}
        pool = dict(pool)
        pool["live"] = [x for x in pool["live"] if x[1]["event_id"] not in sub_event_ids]
        streams[target] = pool

        if c["verb"] == "stop":
            continue  # fully removed, no replacement series
        sub_key = c["stream_key"]
        if sub_key not in streams:  # avoid clobbering if referenced twice
            streams[sub_key] = sub
        overrides[sub_key] = {"new_amount": c["new_amount"]}
    return streams, overrides


def search_change_set(streams, balance, min_balance, request_date, payments, change_candidates):
    """Search subsets of size 1..MAX_CHANGES for one that makes `payments`
    safe under re-forecast (the corrected G10/G14 mechanism -- never a
    static per-occurrence-saving-vs-gap comparison). Prefers fewest
    changes, then lowest approximate ongoing cost, as the tie-break
    (G14's exact rule is still open per the plan; this is the documented
    default)."""
    if not change_candidates:
        return None
    for size in range(1, min(MAX_CHANGES, len(change_candidates)) + 1):
        found = []
        for combo in itertools.combinations(change_candidates, size):
            # G13 mutual exclusion: stop and reduce must target different events
            event_ids = [c["event_id"] for c in combo]
            if len(set(event_ids)) != len(event_ids):
                continue
            mod_streams, overrides = _apply_changes_to_streams(streams, combo)
            safe, lo = _payment_safe(mod_streams, balance, min_balance, request_date, payments, overrides)
            if safe:
                found.append((combo, lo))
        if found:
            # tie-break: lowest total "cost" proxy = highest resulting trough
            # is not it; prefer the combo needing the LEAST aggressive cut,
            # i.e. the one whose trough is closest to (but above) min_balance
            found.sort(key=lambda x: x[1])
            return list(found[0][0])
    return None


def _resolve_sub_stream(streams, candidate):
    """Attach the real sub-stream dict to a change candidate (needed for
    the pooled daily-rate-delta approximation)."""
    if candidate["pooled_parent"] is None:
        candidate["_sub_stream"] = streams[candidate["stream_key"]]
    else:
        parent = streams[candidate["pooled_parent"]]
        candidate["_sub_stream"] = parent["_source_streams"][candidate["stream_key"]]
    return candidate


def generate_full_payment(streams, balance, min_balance, request_date, requested_amount, change_candidates):
    payments = [(request_date, requested_amount)]
    safe, _ = _payment_safe(streams, balance, min_balance, request_date, payments)
    if safe:
        return {"method": "full_payment", "plan": payments, "changes": [],
                "total_paid": requested_amount, "start": request_date,
                "n_payments": 1, "completes_by_deadline": True, "option_id": None}
    chosen = search_change_set(streams, balance, min_balance, request_date, payments, change_candidates)
    if chosen:
        return {"method": "full_payment", "plan": payments, "changes": chosen,
                "total_paid": requested_amount, "start": request_date,
                "n_payments": 1, "completes_by_deadline": True, "option_id": None}
    return None


def generate_partial(streams, balance, min_balance, request_date, requested_amount,
                      earliest, desired_completion_date, allows_partial, change_candidates):
    if not allows_partial or earliest is None:
        return None
    safe_amt = forecast.amount_safe_to_pay(streams, balance, min_balance, request_date, requested_amount)
    if not (0 < safe_amt < requested_amount):
        return None
    if earliest > desired_completion_date:
        return None
    remainder = requested_amount - safe_amt
    payments = [(request_date, safe_amt), (earliest, remainder)]
    safe, _ = _payment_safe(streams, balance, min_balance, request_date, payments)
    if not safe:
        chosen = search_change_set(streams, balance, min_balance, request_date, payments, change_candidates)
        if not chosen:
            return None
        changes = chosen
    else:
        changes = []
    return {"method": "partial_payment", "plan": payments, "changes": changes,
            "total_paid": requested_amount, "start": request_date,
            "n_payments": 2, "completes_by_deadline": earliest <= desired_completion_date,
            "option_id": None}


def generate_installments(streams, balance, min_balance, request_date, requested_amount,
                           options, desired_completion_date, max_installment_months, change_candidates):
    out = []
    if max_installment_months is None:
        return out  # blank cap = installments refused entirely (verified 119/119)
    for opt in options:
        duration_months = math.ceil(opt["number_of_payments"] * opt["payment_frequency_days"] / 30)
        if duration_months > max_installment_months:
            continue
        first = datetime.date.fromisoformat(opt["first_payment_date"])
        plan = [(first + datetime.timedelta(days=opt["payment_frequency_days"] * k), opt["payment_amount"])
                for k in range(opt["number_of_payments"])]
        last_date = plan[-1][0]
        safe, _ = _payment_safe(streams, balance, min_balance, request_date, plan)
        changes = []
        if not safe:
            chosen = search_change_set(streams, balance, min_balance, request_date, plan, change_candidates)
            if not chosen:
                continue
            changes = chosen
        out.append({"method": "installments", "plan": plan, "changes": changes,
                     "total_paid": opt["total_payable_amount"], "start": first,
                     "n_payments": opt["number_of_payments"],
                     "completes_by_deadline": last_date <= desired_completion_date,
                     "option_id": opt["payment_option_id"]})
    return out


def generate_wait(request_date, requested_amount, earliest, desired_completion_date):
    if earliest is None or earliest == request_date:
        return None
    return {"method": "wait", "plan": [(earliest, requested_amount)], "changes": [],
            "total_paid": requested_amount, "start": earliest, "n_payments": 1,
            "completes_by_deadline": earliest <= desired_completion_date, "option_id": None}


def _option_id_sort_key(option_id):
    if option_id is None:
        return (1, "")
    # payment_option_NN -> sortable by the numeric suffix
    try:
        return (0, int(option_id.rsplit("_", 1)[-1]))
    except ValueError:
        return (0, option_id)


def rank(candidates):
    """Rank rule order (spec, verbatim): completes by deadline -> no
    spending changes -> lowest total paid -> earlier start -> fewer
    payments -> lowest payment_option_id."""
    def key(c):
        return (
            0 if c["completes_by_deadline"] else 1,
            0 if not c["changes"] else 1,
            c["total_paid"],
            c["start"],
            c["n_payments"],
            _option_id_sort_key(c["option_id"]),
        )
    return sorted(candidates, key=key)


def generate_candidates(streams, profile, request, safe_amt, earliest):
    """Builds every eligible candidate plan (full / partial / each
    installment option / wait) for one request. Pure function relative to
    its caller: mutates `streams` only via `_resolve_sub_stream` attaching
    `_sub_stream` onto change-candidate dicts (unchanged behavior from the
    original `decide()`), never the streams' cash-flow data itself. Returns
    the UNRANKED candidate list -- `rank()` orders it."""
    balance = profile["current_available_balance"]
    min_balance = profile["minimum_balance_to_keep"]
    request_date = datetime.date.fromisoformat(request["request_date"])
    desired_completion = datetime.date.fromisoformat(request["desired_completion_date"])
    requested_amount = request["requested_amount"]
    accepted_methods = profile["payment_methods_user_will_consider"]

    import streams as streams_mod
    change_candidates = streams_mod.resolve_change_candidates(streams, profile)
    for c in change_candidates:
        _resolve_sub_stream(streams, c)

    candidates = []
    if "full_payment" in accepted_methods:
        fp = generate_full_payment(streams, balance, min_balance, request_date, requested_amount, change_candidates)
        if fp:
            candidates.append(fp)
    if "partial_payment" in accepted_methods and request["allows_partial_payment"]:
        pp = generate_partial(streams, balance, min_balance, request_date, requested_amount,
                               earliest, desired_completion, True, change_candidates)
        if pp:
            candidates.append(pp)
    if "installments" in accepted_methods:
        options = request.get("_options", [])
        candidates.extend(generate_installments(
            streams, balance, min_balance, request_date, requested_amount,
            options, desired_completion, profile["max_installment_months"], change_candidates))
    if "full_payment" in accepted_methods:
        wt = generate_wait(request_date, requested_amount, earliest, desired_completion)
        if wt:
            candidates.append(wt)
    return candidates


def decide(streams, profile, request):
    """Full decision pipeline for one request. Returns the 8-field output
    dict (request_id excluded -- caller adds it) plus `_all_candidates`,
    the full ranked list, for callers (rationale.py) that need to reason
    about which candidates were considered, not just the winner."""
    balance = profile["current_available_balance"]
    min_balance = profile["minimum_balance_to_keep"]
    request_date = datetime.date.fromisoformat(request["request_date"])
    requested_amount = request["requested_amount"]

    safe_amt = forecast.amount_safe_to_pay(streams, balance, min_balance, request_date, requested_amount)
    earliest = forecast.earliest_date_for_full_payment(streams, balance, min_balance, request_date, requested_amount)

    candidates = generate_candidates(streams, profile, request, safe_amt, earliest)
    ranked = rank(candidates)
    final = ranked[0] if ranked else None

    if final is None:
        status = "not_affordable"
        method = "not_recommended"
        plan_str = "none"
        earliest_str = ""
        changes_str = "none"
    else:
        if final["method"] == "full_payment" and not final["changes"] and final["start"] == request_date:
            status = "affordable_now"
        elif final["method"] == "wait":
            status = "affordable_later"
        else:
            status = "affordable_with_plan"
        method = final["method"]
        plan_str = "|".join(f"{d.isoformat()}:{_fmt(a)}" for d, a in final["plan"])
        earliest_str = earliest.isoformat() if earliest else ""
        changes_str = _format_changes(final["changes"])

    return {
        "amount_safe_to_pay": _fmt(safe_amt),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": plan_str,
        "earliest_date_for_full_payment": earliest_str,
        "spending_changes_needed": changes_str,
        "_final": final,
        "_all_candidates": ranked,
        "_safe_amt": safe_amt,
        "_earliest": earliest,
    }


def _fmt(amount):
    """G20: pad to 2dp when fractional, bare when integral."""
    if amount == int(amount):
        return str(int(amount))
    return f"{amount:.2f}"


def _format_changes(changes):
    if not changes:
        return "none"
    parts = []
    for c in changes[:MAX_CHANGES]:
        if c["verb"] == "stop":
            parts.append(f"stop:{c['event_id']}")
        else:
            parts.append(f"reduce_to:{c['event_id']}:{_fmt(c['new_amount'])}")
    return "|".join(parts)
