import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import main

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_process_all_matches_pre_refactor_snapshot():
    rows = main.process_all("requests.csv", use_evidence=False)
    with open(FIXTURES_DIR / "pre_refactor_output_no_evidence.csv", encoding="utf-8") as f:
        expected_rows = list(csv.DictReader(f))

    assert len(rows) == len(expected_rows) == 250
    for got, expected in zip(rows, expected_rows):
        assert got == expected, f"mismatch on {got['request_id']}"


def test_process_all_rows_have_required_columns():
    rows = main.process_all("requests.csv", use_evidence=False)
    required = {
        "request_id", "amount_safe_to_pay", "affordability_status",
        "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
        "spending_changes_needed", "decision_explanation",
    }
    for row in rows:
        assert set(row.keys()) == required
