"""
Entrypoint: dataset/ -> output.csv.

Stage 2 (evidence extraction) is not wired in yet -- this is the
deterministic core only (goal graph Node 1). Run with:
    python3 code/main.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingest
import streams as streams_mod
import planner
import format as fmt
import evidence

OUTPUT_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
    "spending_changes_needed", "decision_explanation",
]


def process_all(requests_path_name="requests.csv", use_evidence=True):
    rates = ingest.load_exchange_rates()
    profiles = ingest.load_profiles()
    events_by_user = ingest.load_events(rates, profiles)
    requests = ingest.load_requests(requests_path_name)
    options_by_request = ingest.load_payment_options()

    images_by_user = {}
    messages_by_user = {}
    if use_evidence:
        for img in ingest.load_images().values():
            images_by_user.setdefault(img["user_id"], []).append(img)
        for msg in ingest.load_messages():
            messages_by_user.setdefault(msg["user_id"], []).append(msg)

    rows = []
    for req in requests:
        profile = profiles[req["user_id"]]
        events = list(events_by_user.get(req["user_id"], []))  # copy: evidence mutates
        import datetime
        request_date = datetime.date.fromisoformat(req["request_date"])

        if use_evidence:
            uid = req["user_id"]
            evidence.fill_blank_amounts(events, images_by_user.get(uid, []), rates, profile["home_currency"])
            evidence.apply_income_amendments(events, uid, messages_by_user.get(uid, []), req["request_date"],
                                              rates, profile["home_currency"])

        st = streams_mod.build_streams(events, request_date)

        req = dict(req)
        req["_options"] = options_by_request.get(req["request_id"], [])

        result = planner.decide(st, profile, req)
        explanation = fmt.explain(result, req, profile)

        rows.append({
            "request_id": req["request_id"],
            "amount_safe_to_pay": result["amount_safe_to_pay"],
            "affordability_status": result["affordability_status"],
            "recommended_payment_method": result["recommended_payment_method"],
            "payment_plan": result["payment_plan"],
            "earliest_date_for_full_payment": result["earliest_date_for_full_payment"],
            "spending_changes_needed": result["spending_changes_needed"],
            "decision_explanation": explanation,
        })
    return rows


def write_output(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    rows = process_all("requests.csv")
    write_output(rows, repo_root / "output.csv")
    print(f"Wrote {len(rows)} rows to {repo_root / 'output.csv'}")
