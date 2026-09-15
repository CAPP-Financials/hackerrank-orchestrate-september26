"""
Post-hoc fragility pass (goal graph Node 4): flags predictions whose
UNCLAMPED capacity (trough - min_balance) sits close to a decision
boundary (0, or requested_amount) -- these are exactly where a small
forecast-accuracy error can flip affordability_status/recommended_method,
per the request_06-style regime-flip risk named in the devil's-advocate
review. There is no ground truth on the 250 eval rows to catch this
directly, so this substitutes a structural signal: how much margin does
the unclamped number have, not just where the clamped output landed.
"""
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Deliberately does NOT call evidence.py -- this is a cheap structural
# margin check (no new API cost), not a precision check. Fragility is
# about how close the UNCLAMPED number sits to a boundary, which evidence
# amendments shift by a few percent at most; the flagged set is a
# reasonable proxy either way.
import ingest
import streams as streams_mod
import forecast

MARGIN_PCT = 0.03  # within 3% of a boundary counts as fragile


def main():
    rates = ingest.load_exchange_rates()
    profiles = ingest.load_profiles()
    events_by_user = ingest.load_events(rates, profiles)
    requests = ingest.load_requests("requests.csv")

    flagged = []
    for req in requests:
        profile = profiles[req["user_id"]]
        events = events_by_user.get(req["user_id"], [])
        rd = datetime.date.fromisoformat(req["request_date"])
        st = streams_mod.build_streams(events, rd)
        balance = profile["current_available_balance"]
        minb = profile["minimum_balance_to_keep"]
        req_amt = req["requested_amount"]

        curve = forecast.forecast_curve(st, balance, rd)
        unclamped = curve["trough"] - minb  # BEFORE clamping to [0, req_amt]

        near_zero = abs(unclamped) <= max(minb, 1) * MARGIN_PCT
        near_req = req_amt > 0 and abs(unclamped - req_amt) <= req_amt * MARGIN_PCT
        if near_zero or near_req:
            reason = "near-zero-boundary" if near_zero else "near-requested-amount-boundary"
            flagged.append((req["request_id"], reason, round(unclamped, 2), req_amt))

    print(f"Fragility-flagged (genuine near-boundary margin, unclamped): {len(flagged)}/{len(requests)}")
    for rid, reason, unclamped, req_amt in flagged:
        print(f"  {rid}: {reason}  unclamped_capacity={unclamped}  requested_amount={req_amt}")


if __name__ == "__main__":
    main()
