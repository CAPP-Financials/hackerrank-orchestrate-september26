"""
Stage 3: canonical state -- CashflowStream construction.

Collapses raw per-row events into per-(user, description) streams, detects
cadence (monthly / interval / one_off), applies the two calibrated fixes
from the design session (income-identity merge across description drift,
and category pooling for the expense-side over-summation bug), and exposes
a clean list of streams ready for 90-day projection (forecast.py) and
spending-change candidate search (planner.py).

Every design choice here traces to a specific, verified finding -- see the
inline comments and the architecture doc
(C:\\Users\\193pu\\.claude\\plans\\currently-only-discussion-and-tingly-diffie.md).
"""
import datetime
import statistics
from collections import defaultdict, Counter

D = lambda s: datetime.date.fromisoformat(s) if s else None


# ---------------------------------------------------------------------------
# Cash-state classifier (architecture doc SS B.4) + linked_event_id handling
# ---------------------------------------------------------------------------

def is_duplicate_charge(event, events_by_id):
    """The 6 verified 'Original card charge' -> 'Possible duplicate card
    charge' pairs (linked_event_id, 11 days apart, exact amount match).
    Detected structurally (link + matching amount + pending-vs-settled),
    not by hardcoding the description string, so it generalises to the
    eval set even if a duplicate uses different wording there."""
    if event["status"] != "pending" or event["direction"] != "debit":
        return False
    if not event["linked_event_id"]:
        return False
    parent = events_by_id.get(event["linked_event_id"])
    if not parent:
        return False
    return (parent["status"] == "settled"
            and parent["direction"] == "debit"
            and parent["amount_raw"] == event["amount_raw"])


def is_future_flow(event, request_date):
    """SS B.4 cash-state table, collapsed to one predicate: does this event
    count as a projected future flow (as opposed to already-reflected-in-
    balance history, or excluded entirely)?"""
    if event["direction"] == "non_cash":
        return False
    if event["status"] in ("cancelled", "failed"):
        return False
    if event["status"] == "pending" and event["direction"] == "credit":
        return False
    if event["status"] not in ("settled", "scheduled", "pending"):
        return False
    cd = event["cash_date"]
    if not cd:
        return False
    return D(cd) > request_date


def is_history(event, request_date):
    """Settled, non-excluded, at-or-before request_date -- used for cadence
    and amount-model detection, never re-applied as a flow (already inside
    current_available_balance)."""
    if event["direction"] == "non_cash":
        return False
    if event["status"] in ("cancelled", "failed"):
        return False
    cd = event["cash_date"]
    if not cd:
        return False
    return D(cd) <= request_date


# ---------------------------------------------------------------------------
# Stream construction
# ---------------------------------------------------------------------------

def build_base_streams(events, request_date):
    """Group by (description) -- filtering out excluded/duplicate rows first
    -- and classify cadence. One entry per description; monthly-vs-interval
    -vs-one_off exactly as validated against the 25 samples."""
    events_by_id = {e["event_id"]: e for e in events}
    by_desc = defaultdict(list)
    for e in events:
        if is_duplicate_charge(e, events_by_id):
            continue
        cd = e["cash_date"]
        if not cd:
            continue
        d = D(cd)
        if is_history(e, request_date) or is_future_flow(e, request_date):
            by_desc[e["description"]].append((d, e))

    streams = {}
    for desc, items in by_desc.items():
        items.sort(key=lambda x: x[0])
        hist = [x for x in items if x[0] <= request_date]
        fut = [x for x in items if x[0] > request_date]
        if not items:
            continue
        direction = items[-1][1]["direction"]
        category = items[-1][1]["category"]
        flexibility = items[-1][1]["flexibility"]
        # floor_amount is a per-(user,category) constant when present
        floor_amounts = [x[1]["minimum_allowed_amount"] for x in items
                          if x[1]["minimum_allowed_amount"] is not None]
        floor_amount = floor_amounts[-1] if floor_amounts else None

        doms = [x[0].day for x in hist] if hist else [x[0].day for x in items]
        dom_spread = max(doms) - min(doms) if len(doms) > 1 else 0
        modal_dom = Counter(doms).most_common(1)[0][0] if doms else None
        # BUGFIX (found on request_15): a stream with exactly 2 historical
        # occurrences, same day-of-month, ~30 days apart is genuinely
        # monthly -- but the old `len(hist) >= 3` threshold pushed it into
        # the interval branch, which projects via raw day-count arithmetic
        # (`+30 days`) instead of day-of-month anchoring. Raw 30-day
        # arithmetic drifts off the true day whenever an intervening month
        # isn't exactly 30 days (Dec 15 + 30 days = Jan 14, not Jan 15) --
        # a full calendar day of drift that mattered on a razor-thin-margin
        # user. Promote a 2-occurrence stream to monthly when its single
        # gap is itself in the monthly range (27-31 days), not just 3+.
        hist_gap_looks_monthly = False
        if len(hist) == 2:
            g = (hist[1][0] - hist[0][0]).days
            hist_gap_looks_monthly = 27 <= g <= 31
        is_monthly = dom_spread <= 2 and (len(hist) >= 3 or (len(hist) == 2 and hist_gap_looks_monthly))

        streams[desc] = {
            "key": desc, "desc": desc, "direction": direction, "category": category,
            "flexibility": flexibility, "floor_amount": floor_amount,
            "is_monthly": is_monthly, "dom": modal_dom,
            "hist": hist, "fut": fut, "live": items,
            "is_pooled": False, "source_descs": [desc],
        }
    return streams


def apply_income_identity_merge(streams):
    """Merge income (credit) streams whose description drifted (a raise, a
    relabelled payroll row, "Next confirmed salary") into one continuing
    stream, matched by (shared day-of-month, non-overlapping date range) --
    NOT requiring either side to already have 3+ occurrences (that missed
    the target case: a single pre-raise row + a single scheduled row).

    Circuit breaker (verified necessary): disabled entirely for any user
    with more than 3 distinct income descriptions. Checked against 60 users
    with genuinely concurrent multi-source income (gig workers, dual
    earners) -- a blanket merge would wrongly blend unrelated income; this
    threshold cleanly separates the raise/relabel cases (<=2 descriptions)
    from the multi-source cases (4-8 descriptions) without losing the fix
    where it matters."""
    streams = dict(streams)
    income_keys = [k for k, s in streams.items() if s["direction"] == "credit"]
    if len(income_keys) > 3:
        return streams

    def date_range(s):
        ds = [x[0] for x in s["live"]]
        return min(ds), max(ds)

    def overlaps(a, b):
        (a0, a1), (b0, b1) = date_range(a), date_range(b)
        return not (a1 < b0 or b1 < a0)

    merged_away = set()
    for k in list(income_keys):
        if k in merged_away:
            continue
        s = streams[k]
        if s["is_monthly"]:
            continue
        thin_dom = s["live"][-1][0].day
        match = None
        for k2 in income_keys:
            if k2 == k or k2 in merged_away:
                continue
            s2 = streams[k2]
            if s2["dom"] is None or s2["dom"] != thin_dom:
                continue
            if overlaps(s, s2):
                continue
            match = k2
            break
        if match:
            merged_away.add(k)
            merged_live = sorted(streams[match]["live"] + s["live"], key=lambda x: x[0])
            rep = dict(streams[match])
            rep["live"] = merged_live
            rep["is_monthly"] = True
            rep["source_descs"] = streams[match]["source_descs"] + s["source_descs"]
            streams[match] = rep
            del streams[k]
    return streams


def apply_category_pool(streams):
    """Pool multiple non-monthly DEBIT descriptions within one category into
    one combined stream so interval-cadence detection computes ONE rate for
    the category instead of summing N independent per-description
    projections (verified over-summation bug: 7-8 descriptions per category,
    each firing independently across a 90-day horizon, compounds far past
    real spend). Amount is anchored to the true historical daily rate for
    the category, not one representative transaction (a plainer "last
    value" approach was checked and shown to over-correct on request_06).

    Known open limitation (named in the plan, not hidden): this still
    regresses request_06 specifically -- no threshold found this session
    discriminates it from the cases pooling correctly fixes, since it has
    identical (8/8/8) description multiplicity. Ship with this named.

    Critically preserves `source_descs` (the real per-description keys that
    were pooled) on the representative stream, so planner.py can resolve a
    spending-change event_id from the ORIGINAL data, never a synthetic key
    -- this is the exact seam the devil's-advocate pass flagged as untested.
    """
    streams = dict(streams)
    by_cat = defaultdict(list)
    for k, s in streams.items():
        if s["direction"] == "debit" and not s["is_monthly"]:
            by_cat[s["category"]].append(k)
    for cat, keys in by_cat.items():
        if len(keys) < 2:
            continue
        pooled_live = sorted(sum((streams[k]["live"] for k in keys), []), key=lambda x: x[0])
        rep = dict(streams[keys[0]])
        rep["live"] = pooled_live
        rep["key"] = f"__pooled_{cat}__"
        rep["is_pooled"] = True
        rep["source_descs"] = sum((streams[k]["source_descs"] for k in keys), [])
        rep["_source_streams"] = {k: streams[k] for k in keys}  # for change-candidate resolution
        for k in keys:
            del streams[k]
        streams[f"__pooled_{cat}__"] = rep
    return streams


TERMINATION_SIGNALS = ("final", "last salary", "severance")


def apply_income_termination(streams):
    """A thin income row can mean "this stream continues" (a raise, a
    relabelled payroll row -- handled by apply_income_identity_merge) or
    "this stream just ended" (a job termination, e.g. "Final employer
    payroll") -- these are structurally identical (one thin row, same
    day-of-month, non-overlapping with the prior stream) and differ ONLY
    in what the description says. Found on user_05: the merge logic was
    wrongly treating a termination as a continuation and projecting three
    more months of salary that will never arrive (2001% overestimate).

    This dataset uses a small, closed vocabulary for these labels (verified
    across the full 25,342-row file), so a description-text check here is
    a genuine structural signal, not fragile NLP. Any credit stream whose
    latest row's description signals termination becomes a hard income
    cutoff for the user: no OTHER income stream may project past that
    date, regardless of its own cadence."""
    streams = dict(streams)
    cutoffs = []
    for k, s in streams.items():
        if s["direction"] != "credit":
            continue
        last_desc = s["live"][-1][1]["description"].lower()
        if any(sig in last_desc for sig in TERMINATION_SIGNALS):
            cutoffs.append(s["live"][-1][0])
    if not cutoffs:
        return streams
    cutoff = min(cutoffs)
    for k, s in streams.items():
        if s["direction"] == "credit":
            rep = dict(s)
            rep["income_ends_by"] = cutoff
            streams[k] = rep
    return streams


def build_streams(events, request_date):
    """Full pipeline: base construction -> income-identity merge ->
    income-termination cutoff -> category pooling. This is the single
    entry point forecast.py and planner.py should use."""
    streams = build_base_streams(events, request_date)
    streams = apply_income_identity_merge(streams)
    streams = apply_income_termination(streams)
    streams = apply_category_pool(streams)
    return streams


def resolve_change_candidates(streams, profile):
    """Build the list of legal spending-change candidates (G11-G13): one per
    flexible stream whose category the user permits reducing/stopping.

    For a POOLED stream, resolves against the underlying per-description
    source streams (never the synthetic pooled key) so the emitted
    `event_id` is always a real, citable event -- the fix for the untested
    pooling/change-mechanism seam flagged in the devil's-advocate review.
    Targets the LATEST historical occurrence of the stream (G12)."""
    reduce_cats = profile["expense_categories_user_is_willing_to_reduce"]
    stop_cats = profile["expense_categories_user_is_willing_to_stop"]
    protect_cats = profile["expense_categories_to_protect"]

    candidates = []
    for key, s in streams.items():
        # expand pooled streams into their real underlying per-description streams
        sub_streams = list(s.get("_source_streams", {}).values()) if s["is_pooled"] else [s]
        for sub in sub_streams:
            if sub["direction"] != "debit":
                continue
            cat = sub["category"]
            if cat in protect_cats:
                continue
            flex = sub["flexibility"]
            can_reduce = flex in ("reducible", "reducible_or_stoppable") and cat in reduce_cats
            can_stop = flex in ("stoppable", "reducible_or_stoppable") and cat in stop_cats
            if not (can_reduce or can_stop):
                continue
            # latest historical occurrence of THIS specific stream (G12)
            hist = [x for x in sub["live"] if x[1]["event_id"]]
            if not hist:
                continue
            latest_event = hist[-1][1]
            verb = "reduce_to" if can_reduce else "stop"  # reduce preferred (G13)
            new_amount = sub["floor_amount"] if verb == "reduce_to" else 0.0
            if verb == "reduce_to" and sub["floor_amount"] is None:
                continue  # can't reduce without a known floor
            candidates.append({
                "event_id": latest_event["event_id"],
                "verb": verb,
                "new_amount": new_amount,
                "category": cat,
                "stream_key": sub["key"],
                "pooled_parent": key if s["is_pooled"] else None,
            })
    return candidates
