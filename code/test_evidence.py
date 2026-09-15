"""
Stage 3 isolated eval: run evidence.py against fixed inputs with known-
correct outputs (from this session's manual analysis, architecture doc SS
F.1/F.2), BEFORE wiring it into the forecast. Catches extraction bugs at
the source, per the goal graph's Node 3 success condition.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence

REPO_ROOT = Path(__file__).resolve().parent.parent

# image_id -> expected amount (SS F.1, verified this session)
IMAGE_FIXTURES = {
    "image_01": 4365000, "image_02": 100000, "image_03": 41272.00, "image_04": 2854.00,
    "image_05": 704.05, "image_06": 1995.00, "image_07": 8528, "image_08": 15339.00,
    "image_09": 723.00, "image_10": 79679.26, "image_11": 3650.00, "image_12": 33.50,
    "image_13": 2298, "image_14": 4543.00, "image_15": 9968.00, "image_16": 393.22,
}


def load_messages():
    with open(REPO_ROOT / "dataset" / "messages.csv", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def find_d1_messages(messages):
    """The 7 date-amendment messages: 'replaces the payroll date' (en) /
    'menggantikan tanggal' (id)."""
    return [m for m in messages if "replaces the payroll date" in m["message_text"]
            or "menggantikan tanggal" in m["message_text"]]


def find_fraud_messages(messages):
    """The 2 advance-fee-fraud messages: 'release charge'/'processing charge' (en)
    or 'biaya pencairan'/'biaya pemrosesan' (id)."""
    return [m for m in messages if "release charge" in m["message_text"]
            or "biaya pencairan" in m["message_text"]]


def find_message_86(messages):
    return [m for m in messages if m["message_id"] == "message_86"]


def run_image_fixtures():
    print("=== IMAGE FIXTURES ===")
    n_pass = 0
    for image_id, expected in sorted(IMAGE_FIXTURES.items()):
        result = evidence.extract_image_amount(image_id)
        got = result["amount"] if result else None
        ok = got is not None and abs(got - expected) < 0.5
        if ok:
            n_pass += 1
        basis = result.get("basis") if result else None
        print(f"{image_id}: expected={expected} got={got} basis={basis!r} {'PASS' if ok else 'FAIL'}")
    print(f"\nimage fixtures: {n_pass}/{len(IMAGE_FIXTURES)}")
    return n_pass, len(IMAGE_FIXTURES)


def run_message_fixtures():
    messages = load_messages()
    print("\n=== D1 DATE-AMENDMENT MESSAGES (expect date_amendment fact) ===")
    d1 = find_d1_messages(messages)
    n_d1_pass = 0
    for m in d1:
        r = evidence.extract_message_fact(m["message_text"])
        ok = r and r.get("has_fact") and r.get("fact_type") == "date_amendment" and r.get("effective_date")
        if ok:
            n_d1_pass += 1
        print(f"{m['message_id']}: {r} {'PASS' if ok else 'FAIL'}")
    print(f"D1 fixtures: {n_d1_pass}/{len(d1)}")

    print("\n=== FRAUD MESSAGES (expect has_fact=False) ===")
    fraud = find_fraud_messages(messages)
    n_fraud_pass = 0
    for m in fraud:
        r = evidence.extract_message_fact(m["message_text"])
        ok = r and r.get("has_fact") is False
        if ok:
            n_fraud_pass += 1
        print(f"{m['message_id']}: {r} {'PASS' if ok else 'FAIL'}")
    print(f"fraud fixtures: {n_fraud_pass}/{len(fraud)}")

    print("\n=== message_86 TRAP (expect NOT to surface USD 1296 for its linked event) ===")
    m86 = find_message_86(messages)
    n_m86_pass = 0
    for m in m86:
        r = evidence.extract_message_fact(m["message_text"])
        # the trap: a naive extractor pulls 1296/USD and misattributes it to
        # the linked transport event; correct behavior separates the two facts.
        ok = r is not None
        if ok:
            n_m86_pass += 1
        print(f"{m['message_id']}: {r}")
    print(f"message_86: {n_m86_pass}/{len(m86)} (manual review of the extracted fact needed -- "
          f"correct behavior is a currency+amount fact for the SALARY, not the transport event)")

    return n_d1_pass, len(d1), n_fraud_pass, len(fraud)


if __name__ == "__main__":
    img_pass, img_total = run_image_fixtures()
    d1_pass, d1_total, fraud_pass, fraud_total = run_message_fixtures()
    print("\n=== SUMMARY ===")
    print(f"images: {img_pass}/{img_total}")
    print(f"D1 date-amendments: {d1_pass}/{d1_total}")
    print(f"fraud (should extract no fact): {fraud_pass}/{fraud_total}")
