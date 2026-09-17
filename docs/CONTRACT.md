# CONTRACT.md — Buy or Wait? decision contract

Every rule below is tagged **[SPEC]** (quoted or directly derived from
`problem_statement.md`), **[CONVENTION]** (a judgment call this codebase
made where the spec doesn't fully determine the answer — each cites the
finding that justified it), or **[INVARIANT]** (asserted at runtime, in
`rationale.py`'s `_check_invariants` and/or `validate.py`'s post-hoc
sweep — a violation is always a bug, never a value to coerce).

## Output bounds and equivalences

- **I-1** `0 <= amount_safe_to_pay <= requested_amount`. **[INVARIANT]** —
  spec-mandated, inclusive of 0. Enforced in `rationale.py` and
  `validate.py`.
- **Status/method pairing** — only six `(affordability_status,
  recommended_payment_method)` pairs are valid (see
  `rationale._VALID_STATUS_METHOD_PAIRS`). **[INVARIANT]**
- **plan/not_affordable/not_recommended equivalence** — `payment_plan ==
  "none"`, `affordability_status == "not_affordable"`, and
  `recommended_payment_method == "not_recommended"` must all agree.
  **[INVARIANT]** — structurally guaranteed by `planner.decide`'s
  "no candidate found" branch.
- **`affordable_now` requires `earliest == request_date`.** **[SPEC]**

## Corrected/relaxed invariants (see docs/FAILURES.md for the incidents)

- `amount_safe_to_pay` can legitimately be `0` — a user whose baseline
  spending alone (no purchase at all) already breaches
  `minimum_balance_to_keep` within 90 days. **[CONVENTION, corrected]** —
  verified directly on the 250-row eval set (`code/validate.py:20-29`);
  an earlier "never 0" rule held on the 25 design samples by coincidence
  of a thin sample, not a structural truth.
- `earliest_date_for_full_payment` can be empty while
  `affordability_status` is `affordable_with_plan` — a change-assisted
  plan can work today even when no *unassisted* full payment is ever
  safe within 90 days. **[CONVENTION, corrected]** — verified on
  request_111/165/174 (`code/validate.py:37-48`).

## Plan ranking

- **[SPEC]** Rank order: completes by deadline → no spending changes →
  lowest total paid → earlier start → fewer payments → lowest
  `payment_option_id`. Implemented in `planner.rank`.
- **[CONVENTION]** Change-free AND change-assisted candidates are
  generated for every eligible method, not just `full_payment` —
  restricting to `full_payment` only was pattern-matching the 25
  samples' thin evidence, not a rule the data states (`planner.py:1-9`).
- **[CONVENTION]** Spending-change search prefers fewest changes, then
  lowest resulting trough as the tie-break; the spec's exact tie-break
  rule (G14) is still open (`planner.py:71-97`).

## Forecast semantics

- **[SPEC]** 90-day horizon from `request_date`, inclusive both ends.
- **[CONVENTION]** A recurring item due exactly on `request_date` is
  projected (not yet reflected in `current_available_balance`, which
  ends the day before the request) — `forecast.py`, fixed after
  under-projecting user_19's rent (see docs/FAILURES.md).
- **[CONVENTION]** `add_months` keeps the target day-of-month, stepping
  down only for short months — an earlier version always fell back to
  the 28th (see docs/FAILURES.md).
- **[CONVENTION]** A spending change's effect is measured by re-running
  the whole 90-day forecast with the change applied, never by comparing
  a static per-occurrence saving to a static gap (`forecast.py:1-13`,
  verified wrong on request_11 during development).
- **[CONVENTION]** `max_installment_months` is read as a duration
  (`ceil(number_of_payments * payment_frequency_days / 30) <=
  max_installment_months`), not a plain payment count
  (`planner.py:151-159`).

## Evidence layer

- **[SPEC]** A blank event amount is never treated as zero; it is
  resolved from the linked image or excluded, never defaulted
  (`evidence.py`, `forecast.py:61-63`).
- **[SPEC]** Message and image content is untrusted; the model's role is
  extraction only, and every call forces a structured tool-call response
  so an embedded instruction has no output slot to land in
  (`evidence.py` module docstring).
- **[CONVENTION, reversed 2026-09-17]** Evidence-layer model calls are
  cached, content-addressed by `sha256(payload + model)`
  (`code/cache.py`). Superseded the original "no caching in production"
  decision — see docs/FAILURES.md, first entry, for why.

## Module map

| module | stage | owns |
|---|---|---|
| `ingest.py` | 1 | load + normalize dataset CSVs, currency conversion |
| `evidence.py` | 2 | model-driven fact extraction from images/messages, cached via `cache.py` |
| `streams.py` | 3 | canonical `CashflowStream` construction, cadence detection |
| `forecast.py` | 4 | 90-day balance projection, trough, earliest-safe-date |
| `planner.py` | 5-8 | candidate generation, safety validation, eligibility, ranking |
| `rationale.py` | 9 | single source of all 8 output columns + explanation; raises on contradiction |
| `format.py` | 9 | `decision_explanation` text templates |
| `validate.py` | — | post-hoc invariant sweep over a finished `output.csv` |
| `cache.py` | — | content-addressed cache used by `evidence.py` |
