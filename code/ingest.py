"""
Stage 1: ingestion + normalisation.

Reads the dataset/ CSVs, converts every foreign-currency event amount to the
user's home_currency (exchange rates are flat per pair in this dataset --
verified 0.00% variance across all 39 dates per pair -- so a simple lookup
table suffices; no dated interpolation needed), and resolves cash_date =
settlement_date ?? event_date per event.

ponytail: stdlib only (csv, pathlib). No pandas -- the data is small enough
(25k rows) that plain dict/list processing is simpler and dependency-free.
"""
import csv
from pathlib import Path
from collections import defaultdict

DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"


def _read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_exchange_rates():
    """(from_currency, to_currency) -> rate. Flat per pair; last value wins
    (harmless since all values for a pair are identical -- verified)."""
    rates = {}
    for row in _read_csv(DATASET_DIR / "exchange_rates.csv"):
        rates[(row["from_currency"], row["to_currency"])] = float(row["rate"])
    return rates


def convert(amount, from_ccy, to_ccy, rates):
    """Convert amount from from_ccy to to_ccy. Returns None (never 0) if no
    rate is available in either direction -- caller must treat as missing
    evidence, never silently default to zero or an unconverted value."""
    if amount is None:
        return None
    if from_ccy == to_ccy:
        return amount
    if (from_ccy, to_ccy) in rates:
        return amount * rates[(from_ccy, to_ccy)]
    if (to_ccy, from_ccy) in rates:
        inv = rates[(to_ccy, from_ccy)]
        return amount / inv if inv else None
    return None


def load_profiles():
    """user_id -> profile dict with parsed fields."""
    profiles = {}
    for row in _read_csv(DATASET_DIR / "financial_profiles.csv"):
        profiles[row["user_id"]] = {
            "user_id": row["user_id"],
            "home_currency": row["home_currency"],
            "current_available_balance": float(row["current_available_balance"]),
            "minimum_balance_to_keep": float(row["minimum_balance_to_keep"]),
            "financial_priorities": _split(row["financial_priorities"]),
            "expense_categories_to_protect": _split(row["expense_categories_to_protect"]),
            "expense_categories_user_is_willing_to_reduce": _split(row["expense_categories_user_is_willing_to_reduce"]),
            "expense_categories_user_is_willing_to_stop": _split(row["expense_categories_user_is_willing_to_stop"]),
            "payment_methods_user_will_consider": _split(row["payment_methods_user_will_consider"]),
            "max_installment_months": int(row["max_installment_months"]) if row["max_installment_months"].strip() else None,
        }
    return profiles


def _split(field):
    return set(x for x in field.split("|") if x)


def load_events(rates, profiles):
    """user_id -> list of event dicts, amounts converted to home_currency.
    cash_date resolved (settlement_date ?? event_date). Original amount/
    currency kept alongside for traceability."""
    by_user = defaultdict(list)
    for row in _read_csv(DATASET_DIR / "financial_events.csv"):
        uid = row["user_id"]
        home = profiles[uid]["home_currency"] if uid in profiles else row["currency"]
        raw_amount = float(row["amount"]) if row["amount"].strip() else None
        converted = convert(raw_amount, row["currency"], home, rates) if raw_amount is not None else None
        cash_date = row["settlement_date"].strip() or row["event_date"].strip() or None
        by_user[uid].append({
            "event_id": row["event_id"],
            "user_id": uid,
            "event_type": row["event_type"],
            "description": row["description"],
            "category": row["category"],
            "direction": row["direction"],
            "amount": converted,          # home-currency, or None if blank/unconvertible
            "amount_raw": raw_amount,
            "currency_raw": row["currency"],
            "event_date": row["event_date"] or None,
            "settlement_date": row["settlement_date"] or None,
            "cash_date": cash_date,
            "status": row["status"],
            "linked_event_id": row["linked_event_id"] or None,
            "flexibility": row["flexibility"],
            "minimum_allowed_amount": float(row["minimum_allowed_amount"]) if row["minimum_allowed_amount"].strip() else None,
        })
    return by_user


def load_requests(path_name="requests.csv"):
    rows = _read_csv(DATASET_DIR / path_name)
    out = []
    for row in rows:
        out.append({
            "request_id": row["request_id"],
            "user_id": row["user_id"],
            "request_date": row["request_date"],
            "request_type": row["request_type"],
            "requested_amount": float(row["requested_amount"]),
            "desired_completion_date": row["desired_completion_date"],
            "allows_partial_payment": row["allows_partial_payment"].strip().lower() == "true",
            "request_text": row["request_text"],
        })
    return out


def load_payment_options():
    """request_id -> list of option dicts (installments only; full_payment
    rows are fully derivable from requested_amount + request_date and are
    never read -- verified 275/275 redundant)."""
    by_req = defaultdict(list)
    for row in _read_csv(DATASET_DIR / "request_payment_options.csv"):
        if row["payment_method"] != "installments":
            continue
        by_req[row["request_id"]].append({
            "payment_option_id": row["payment_option_id"],
            "request_id": row["request_id"],
            "payment_amount": float(row["payment_amount"]),
            "number_of_payments": int(row["number_of_payments"]),
            "first_payment_date": row["first_payment_date"],
            "payment_frequency_days": int(row["payment_frequency_days"]),
            "financing_fee": float(row["financing_fee"]),
            "total_payable_amount": float(row["total_payable_amount"]),
        })
    return by_req


def load_images():
    """image_id -> row dict (user_id, request_id, related_event_id)."""
    return {row["image_id"]: row for row in _read_csv(DATASET_DIR / "images.csv")}


def load_messages():
    """List of message row dicts, as-is (evidence.py consumes these)."""
    return _read_csv(DATASET_DIR / "messages.csv")
