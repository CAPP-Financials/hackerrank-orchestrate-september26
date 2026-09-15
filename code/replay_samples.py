"""
Test harness: runs the full pipeline against dataset/sample_requests.csv as
if its 8 output columns were blank, diffs against the real columns, prints
per-sample pass/fail. Run after every change to streams.py/forecast.py/
planner.py -- the fast feedback loop the roadmap's time budget depends on.

Evidence-free samples (no linked message/image) are the ones Node 1 can be
graded on before Stage 2 exists: 01,02,05,07,09,12,13,14,21,24,25.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence
evidence.DEV_CACHE_ENABLED = True  # dev-only iteration speed; the real run disables this
import main as main_mod

EVIDENCE_FREE = {"request_01", "request_02", "request_05", "request_07", "request_09",
                  "request_12", "request_13", "request_14", "request_21", "request_24", "request_25"}

FIELDS = ["amount_safe_to_pay", "affordability_status", "recommended_payment_method",
          "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]


def load_oracle():
    path = Path(__file__).resolve().parent.parent / "dataset" / "sample_requests.csv"
    with open(path, encoding="utf-8-sig") as f:
        return {r["request_id"]: r for r in csv.DictReader(f)}


def main():
    oracle = load_oracle()
    rows = main_mod.process_all("sample_requests.csv")
    by_id = {r["request_id"]: r for r in rows}

    n_pass = 0
    n_total = 0
    evidence_free_pass = 0
    for rid, want in oracle.items():
        got = by_id.get(rid)
        if not got:
            print(f"{rid}: MISSING")
            continue
        n_total += 1
        mismatches = []
        for f in FIELDS:
            if f == "amount_safe_to_pay":
                w = float(want[f]); g = float(got[f])
                rel = abs(w - g) / w * 100 if w else (0 if g == 0 else 999)
                if rel > 1.0:
                    mismatches.append(f"{f}: want={w} got={g} ({rel:.1f}% off)")
            else:
                if want[f] != got[f]:
                    mismatches.append(f"{f}: want={want[f]!r} got={got[f]!r}")
        tag = "EVIDENCE-FREE" if rid in EVIDENCE_FREE else "evidence-touched"
        if not mismatches:
            n_pass += 1
            if rid in EVIDENCE_FREE:
                evidence_free_pass += 1
            print(f"{rid} [{tag}]: PASS")
        else:
            print(f"{rid} [{tag}]: FAIL")
            for m in mismatches:
                print(f"    {m}")

    print()
    print(f"Overall: {n_pass}/{n_total} exact-match (categorical fields + 1% amount tolerance)")
    print(f"Evidence-free floor: {evidence_free_pass}/{len(EVIDENCE_FREE)} "
          f"(Node 1 target: >=10/11)")


if __name__ == "__main__":
    main()
