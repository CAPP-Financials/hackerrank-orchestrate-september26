"""
Stage 4: 90-day forecast curve.

Projects every stream forward from request_date to request_date+90d,
computes the balance curve and its trough, and supports re-forecasting
with a spending-change set applied -- the corrected G10/G14 mechanism
(a change permanently reduces every future occurrence of a stream within
the horizon; whether it "closes the gap" is answered by re-running the
whole forecast, never by comparing a static per-occurrence saving to a
static gap number, which was shown to be wrong on user_11: a chosen
change's single-occurrence saving was LESS than the stated gap, yet it
worked because the stream recurred multiple times before the old
earliest-safe date).
"""
import datetime
import statistics

HORIZON_DAYS = 90


def add_months(d, dom):
    y, m = d.year, d.month + 1
    if m > 12:
        m = 1
        y += 1
    try:
        return datetime.date(y, m, dom)
    except ValueError:
        nm = m + 1 if m < 12 else 1
        ny = y if m < 12 else y + 1
        return datetime.date(ny, nm, 1) - datetime.timedelta(days=1)


def project_flows(streams, request_date, horizon, overrides=None):
    """Returns a flat list of (date, signed_amount, stream_key) flows.

    overrides: optional dict stream_key -> {'stopped_entirely': bool} or
    {'new_amount': float}, for the change-assisted re-forecast path
    (planner.py builds these, splitting any affected pooled stream first
    so a change's amount override always applies to a real, undiluted
    stream -- see planner._apply_changes_to_streams)."""
    overrides = overrides or {}
    flows = []
    for k, s in streams.items():
        override = overrides.get(k, {})
        if override.get("stopped_entirely"):
            continue  # no flows at all for a fully-stopped stream

        live = s["live"]
        hist = [x for x in live if x[0] <= request_date]
        fut = [x for x in live if x[0] > request_date]
        sign = 1 if s["direction"] == "credit" else -1

        # explicit forward-dated rows always apply first (already respects
        # the cash-state classifier -- these are pre-filtered in streams.py)
        explicit_dates = []
        for d, ev in fut:
            if d > horizon:
                continue
            amt = ev["amount"]
            if amt is None:
                continue  # missing evidence: exclude, never default to zero
            flows.append((d, sign * amt, k))
            explicit_dates.append(d)

        proj_amt = override.get("new_amount")
        if proj_amt is None:
            last = live[-1][1]["amount"]
            proj_amt = last if last is not None else 0.0

        income_ends_by = s.get("income_ends_by")

        if s["is_monthly"] and live:
            last_date = live[-1][0]
            dom = s["dom"]
            cur = last_date
            while True:
                cur = add_months(cur, dom)
                if cur > horizon:
                    break
                if income_ends_by and cur > income_ends_by:
                    break  # job/stream has ended -- see streams.apply_income_termination
                if cur > request_date and not any(abs((cur - ed).days) <= 10 for ed in explicit_dates):
                    flows.append((cur, sign * proj_amt, k))

        elif not s["is_monthly"] and len(hist) >= 2:
            gaps = [(hist[i][0] - hist[i - 1][0]).days for i in range(1, len(hist))]
            med_gap = statistics.median(gaps) if gaps else None
            if s.get("is_pooled") and med_gap and override.get("new_amount") is None:
                span_days = (hist[-1][0] - hist[0][0]).days
                daily_rate = (sum(x[1]["amount"] or 0 for x in hist) / span_days
                              if span_days > 0 else 0)
                proj_amt = daily_rate * med_gap
            if med_gap and 3 <= med_gap <= 35:
                cur = hist[-1][0]
                while True:
                    cur = cur + datetime.timedelta(days=med_gap)
                    if cur > horizon:
                        break
                    if cur > request_date and not any(abs((cur - ed).days) <= max(2, med_gap // 3) for ed in explicit_dates):
                        flows.append((cur, sign * proj_amt, k))
    return flows


def trough(balance, flows):
    """Returns (trough_value, trough_date). trough_date defaults to the
    request date if the balance never dips below its starting value."""
    seq = sorted(flows, key=lambda x: x[0])
    run = balance
    lo = balance
    lo_date = None
    for d, amt, k in seq:
        run += amt
        if run < lo:
            lo = run
            lo_date = d
    return lo, lo_date


def forecast_curve(streams, balance, request_date, overrides=None):
    horizon = request_date + datetime.timedelta(days=HORIZON_DAYS)
    flows = project_flows(streams, request_date, horizon, overrides)
    lo, lo_date = trough(balance, flows)
    return {"flows": flows, "trough": lo, "trough_date": lo_date, "horizon": horizon}


def amount_safe_to_pay(streams, balance, min_balance, request_date, requested_amount):
    """G1: clamp(trough - min_balance, 0, requested_amount) on the
    UNMODIFIED forecast, before any spending change."""
    curve = forecast_curve(streams, balance, request_date)
    safe = curve["trough"] - min_balance
    return max(0.0, min(requested_amount, safe))


def earliest_date_for_full_payment(streams, balance, min_balance, request_date, requested_amount):
    """G6/G19: the first date a single full payment of requested_amount,
    made on that date, keeps the balance >= min_balance for the WHOLE
    90-day horizon (not just from that date onward -- a payment on day 20
    can still fail if the balance already dipped below min_balance on day
    5, before the payment even happens). Computed on the unmodified
    forecast, independent of payment-method preference. Returns None if
    never safe within the forecast."""
    horizon = request_date + datetime.timedelta(days=HORIZON_DAYS)
    flows = project_flows(streams, request_date, horizon)
    seq = sorted(flows, key=lambda x: x[0])

    # BUGFIX: checking only flow dates missed the true safe date when it
    # falls the day AFTER a flow (same-day income+expense interaction) --
    # found on request_07, off by exactly one day. Checking every calendar
    # day in the 90-day horizon is cheap (90 iterations) and removes this
    # whole class of off-by-one candidate-selection error.
    candidates = [request_date + datetime.timedelta(days=i) for i in range(HORIZON_DAYS + 1)]
    for cand in candidates:
        full_seq = sorted(seq + [(cand, -requested_amount, "__payment__")], key=lambda x: x[0])
        run = balance
        lowest = balance
        for d, amt, k in full_seq:
            run += amt
            if run < lowest:
                lowest = run
        if lowest >= min_balance:
            return cand
    return None


# Change application lives in planner.py (_apply_changes_to_streams) -- it
# needs to split a pooled stream into "pool minus target" + "target alone",
# which requires streams.py's `_source_streams` data, not available here.
