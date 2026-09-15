# HackerRank Orchestrate

Starter repository for the **HackerRank Orchestrate** 24-hour hackathon (September 2026).

## Buy or Wait?

Build an AI-powered financial agent that decides whether a user can safely afford a requested expense.

A user may ask: **"Can I afford this laptop?"**

Answering well takes more than the current balance. The agent must account for recurring expenses, pending payments, essential spending, confirmed income, available payment options, and relevant details buried in messages and images.

For every request, the agent decides whether the user should pay in full, pay partially, use installments, wait, or not proceed. The recommendation must be personalized: two users with the same balance can deserve different answers based on their commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

A recommendation is safe only if the user can complete the full payment plan, cover essential expenses, and stay above their preferred minimum balance throughout the forecast period.

Read [`problem_statement.md`](./problem_statement.md) for the full task spec, input/output schema, allowed values, conflict-resolution rules, and submission format.

---

## My Solution

Python, entry point `code/main.py`. Two layers:

- **Deterministic core** (`ingest.py`, `streams.py`, `forecast.py`, `planner.py`, `format.py`,
  `validate.py`) — no model calls. Reconstructs each user's recurring cash-flow streams from
  `financial_events.csv`, projects a 90-day balance curve, generates every eligible payment
  candidate (full / partial / each installment option / wait, change-assisted where needed),
  ranks them per the spec's stated order, and writes `output.csv`.
- **Evidence extraction** (`evidence.py`) — the only stage that calls a model: **Claude Sonnet 5**
  (`claude-sonnet-5`), via the `anthropic` SDK, structured tool-call output only (never free
  text a downstream step could "read" as an instruction — this is what keeps prompt-injection
  attempts in the message data inert by construction). Fills blank event amounts from linked
  images and applies income date/amount amendments from linked messages.

The model's role is deliberately limited to extraction: it turns an unstructured receipt image
or message body into a typed fact (`amount`, `currency`, `effective_date`, `fact_type`,
`confidence`), never a decision. Every affordability call, ranking, and dollar figure is
produced by deterministic code so the same inputs always reach the same conclusion, the whole
decision path is auditable and testable, and an adversarial message has no output slot to
inject a directive into — a live test against the dataset's two actual advance-fee-fraud
messages confirms both are correctly extracted as "no fact," never as income or an expense.

### Architecture — nine stages

```text
dataset/*.csv + media/images/*.png
   │
   ├─ 1. Ingest & normalize      currency conversion, cash-date resolution
   ├─ 2. Evidence resolution     Claude Sonnet 5 → typed facts (images, messages)
   ├─ 3. Canonical state         group events into per-user CashflowStreams,
   │                             detect cadence (monthly / interval / one-off),
   │                             collapse linked_event_id lifecycle chains
   ├─ 4. 90-day forecast         project streams forward → balance curve, trough
   ├─ 5. Candidate plans         full / partial / each installment option / wait /
   │                             change-assisted full payment (re-forecast based)
   ├─ 6. Safety validation       reject any candidate breaching minimum balance
   ├─ 7. Eligibility filter      accepted payment methods, installment-month cap,
   │                             partial-payment allowance
   ├─ 8. Ranking                 deadline met → no spending changes → lowest cost →
   │                             earlier start → fewer payments → lowest option id
   └─ 9. Emit + validate         write output.csv, run the invariant sweep
```

Stages 1 and 3–9 are pure deterministic code. Stage 2 is the only place a model is called, and
it caches during development only — the official run that produced the submitted `output.csv`
makes every call live, with no cache.

### Results (the actual submitted run)

- **250/250 rows generated, 0 invariant violations** on the submitted `output.csv` (bounds,
  plan-sum identities, installment-matches-option, flexible-only spending changes, the
  status/method/plan consistency rule).
- **209 live model calls** (198 message extractions, 11 image extractions), **282,011 total
  tokens**, **$1.2347 total cost** (~$0.0049/request) — see
  [`code/evaluation/usage_report.md`](./code/evaluation/usage_report.md) for the full breakdown.
- Against the 25 publicly solved samples: **17/25** exact categorical match
  (`affordability_status` / `recommended_payment_method` / `payment_plan` shape), **6/25** also
  within 1% on `amount_safe_to_pay`. The dataset has no ground truth for the 250 evaluation
  requests, so this is the only real accuracy signal available pre-submission — reported as-is
  rather than rounded up.
- `code/fragility_check.py` flags **10/250** requests whose forecasted capacity sits within 3%
  of a decision boundary (`0` or `requested_amount`) — see Known Limitations.

### Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the repo root (gitignored, never committed) with:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Run

```bash
python3 code/main.py
```

Reads `dataset/requests.csv`, writes `output.csv` to the repo root, and regenerates
`code/evaluation/usage_report.md` from that same run (`python3 code/final_run.py` is the
identical entrypoint used for the actual submitted run, with the token/cost report wired in
explicitly).

Other scripts: `code/replay_samples.py` (checks the pipeline against the 25 solved samples in
`dataset/sample_requests.csv`), `code/test_evidence.py` (isolated eval of `evidence.py` against
known-correct extractions before it's wired into the forecast), `code/validate.py` (the
invariant sweep, importable and also run automatically as part of `final_run.py`),
`code/fragility_check.py` (flags predictions whose forecasted capacity sits close to a
decision boundary — see Known Limitations).

### Key modelling decisions

A few places the spec doesn't fully determine the answer; documented rather than left implicit:

- **`max_installment_months` is read as a duration** — an option is eligible only if
  `ceil(number_of_payments × payment_frequency_days / 30) ≤ max_installment_months`, not a
  plain `number_of_payments ≤ max_installment_months`. Affects 6 of 261 eligible-cap options in
  the eval set; the samples don't discriminate between the two readings.
- **Recurring streams are detected, not read** — no field states recurrence. A stream is
  `monthly` when its historical occurrences share a day-of-month (±2 days) across ≥3
  occurrences, or `interval` when the median gap between occurrences falls in [3, 35] days.
- **Spending changes are evaluated by re-forecasting**, not by comparing a static per-occurrence
  saving against a static gap — a change permanently reduces every future occurrence of a
  stream within the horizon, and whether it closes the gap is answered by re-running the whole
  90-day forecast with the change applied.
- **Overlapping same-category expense descriptions are pooled** before interval-cadence
  detection (e.g. 6-8 distinct "groceries" descriptions for one user), so the forecast computes
  one rate for the category instead of summing many independent per-description projections.
- **Income streams whose description drifts** (a raise, a relabelled payroll row, "Next
  confirmed salary") are merged into one continuing stream when they share a day-of-month and
  don't overlap in time — gated to users with ≤3 distinct income descriptions, since unrestricted
  merging was checked directly and found to wrongly blend genuinely concurrent income (dual
  earners, multiple gig-payout streams).

### Known limitations (disclosed, not silently shipped)

- **Gig/irregular-income cadence** is the largest remaining source of forecast error — income
  patterns that are neither monthly nor a clean 3-35 day interval (several one-off or
  quarterly-ish payments) are under-projected. Affects a specific, identifiable subset of users;
  not fixed in this submission.
- **Category pooling trades one bias for another.** It fixes over-summation for users with many
  overlapping expense descriptions, but the correct degree of pooling varies by user in a way
  no single global rule captures — verified directly (not assumed) on a case where pooling
  under-drains despite identical description-count structure to cases it correctly fixes.
- **`code/fragility_check.py`** flags 10 of 250 requests whose forecasted capacity sits within a
  few percent of a decision boundary (`0` or `requested_amount`) — these are the rows most
  likely to have their categorical output flipped by a small forecast-accuracy error, and are
  worth a manual second look given the deadline allowed for it.
- **Two invariants from the initial design (documented in the development transcript) turned
  out to be over-fit to the 25 solved samples, not universal**: `amount_safe_to_pay` can
  legitimately be `0` (the tightest-headroom user in the dataset genuinely breaches their
  minimum balance from baseline spending alone), and `earliest_date_for_full_payment` can be
  empty while the request is still `affordable_with_plan` (a change-assisted plan works today
  even when no *unassisted* full payment is ever safe within 90 days). `code/validate.py`
  reflects the corrected understanding, verified against the real 250-row eval set rather than
  assumed from the smaller sample.

---

## Quick Start

Clone the repository and move into the project directory:

```bash
git clone https://github.com/CAPP-Financials/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26
```

(This is a fork/personal copy built for the HackerRank Orchestrate hackathon; the original
starter repo is [interviewstreet/hackerrank-orchestrate-september26](https://github.com/interviewstreet/hackerrank-orchestrate-september26).)

Build your solution in `code/main.py`, or use another language and document its entry point clearly.

Your solution must:

- Read the input files from `dataset/`
- Generate one prediction for every request
- Write the final predictions to `output.csv` in the repository root

Run the starter Python entry point with:

```bash
python3 code/main.py
```

After running your solution, confirm that `output.csv` exists in the repository root and contains the required columns and one row for every request.

## Important File Locations

```text
dataset/        Input data and the blank output template. Do not modify the input data.
code/           Your solution code.
output.csv      Final generated predictions in the repository root.
code.zip        ZIP file containing your complete solution for submission.
```

The blank template at `dataset/output.csv` is provided as a reference. Your final generated file must be the root-level `output.csv`.

---

## Repository Layout

```text
.
├── AGENTS.md                         # Rules for AI coding tools + transcript logging
├── problem_statement.md              # Full challenge statement
├── README.md                         # You are here
├── code/                             # Your solution code
├── output.csv                        # Final generated predictions
└── dataset/
    ├── requests.csv                  # 250 requests to evaluate — predict these
    ├── output.csv                    # Blank submission template
    ├── sample_requests.csv           # 25 solved examples
    ├── financial_profiles.csv        # Balances, minimum balance, priorities, preferences
    ├── financial_events.csv          # Historical, pending, and confirmed transactions
    ├── request_payment_options.csv   # Payment options available per request
    ├── exchange_rates.csv            # Fixed, dated conversion rates
    ├── messages.csv                  # Messages tied to users, requests, or events
    ├── images.csv                    # Payroll letters, statements, bills, receipts
    └── media/
        └── images/
```

Only `dataset/requests.csv` requires predictions. Everything else is context. Join user records with `user_id`, request records with `request_id`, supporting evidence with `related_event_id`, and exchange rates with the rate date and currency pair.

Amounts are in the user's `home_currency` — the dataset uses INR, ZAR, IDR, USD, and EUR, and every conversion rate you need is in `exchange_rates.csv`. All dates are `YYYY-MM-DD`. Live exchange rates, market data, and banking access are not required.

---

## What You Need to Build

For every row in `dataset/requests.csv`, produce one row in `output.csv` with:

| Column | Meaning |
|---|---|
| `request_id` | The request being answered |
| `amount_safe_to_pay` | Largest amount safe to pay on `request_date` before optional spending changes, after protecting essentials and the minimum balance |
| `affordability_status` | `affordable_now`, `affordable_with_plan`, `affordable_later`, or `not_affordable` |
| `recommended_payment_method` | `full_payment`, `partial_payment`, `installments`, `wait`, or `not_recommended` |
| `payment_plan` | Chronological `<YYYY-MM-DD>:<amount>` entries joined by `\|`, or `none` |
| `earliest_date_for_full_payment` | Earliest date the full amount is forecast safe as one payment; empty if never within the forecast |
| `spending_changes_needed` | Up to three `stop:<event_id>` / `reduce_to:<event_id>:<amount>` changes joined by `\|`, or `none` |
| `decision_explanation` | Short explanation and the financial facts behind it |

`0 <= amount_safe_to_pay <= requested_amount` must always hold. Installment plans must exactly match a supplied payment option, and only recurring expenses marked flexible may be changed.

`affordable_with_plan` means the full request is completed through a partial-payment schedule, installments, or permitted spending changes. Recommend `partial_payment` only when the request allows it, the user accepts it, `0 < amount_safe_to_pay < requested_amount`, and `earliest_date_for_full_payment` is on or before `desired_completion_date`. Use exactly two payments: pay `amount_safe_to_pay` on `request_date`, then pay the remaining amount on `earliest_date_for_full_payment`. The two payments must add up to `requested_amount`. Unlike installments, partial payment does not need to match a supplied payment option.

---

## Suggested Workflow

1. Inspect `dataset/sample_requests.csv` — 25 requests with completed output columns — to understand the expected format and decision style.
2. Reconstruct each user's financial state from `financial_profiles.csv` and `financial_events.csv`: separate recurring expenses from one-time events, reserve pending transactions, count confirmed salary only on its settlement date, and de-duplicate repeated representations of the same event.
3. When an event has a blank `amount`, find its `event_id` as `related_event_id` in `images.csv` and extract the amount from the linked image. Never treat a blank amount as zero. Pull in any other relevant messages, images, and payment options for the request.
4. Forecast forward and generate a plan that keeps the balance above the minimum at every step.
5. Verify deterministically — bounds, plan feasibility, schedule match, flexible-only spending changes — before writing `output.csv`.
6. Score yourself on the solved samples, then run the full dataset.

You may use any language or runtime. Python, JavaScript, and TypeScript are all reasonable choices.

---

## Requirements

Your solution must:

- be runnable from the terminal
- read the provided files from `dataset/`
- produce a valid `output.csv` with the exact required columns in the exact required order
- include one prediction for every `request_id` in `dataset/requests.csv`
- not use organizer-only files or hardcoded labels
- keep behavior deterministic where possible

If you use API keys or secrets, read them from environment variables. Never hardcode secrets in the repo.

---

## Evaluation

Your `output.csv` will be compared against hidden ground-truth values.

The scoring will consider:

- accuracy of `amount_safe_to_pay`
- correctness of `affordability_status`
- correctness of `recommended_payment_method` and `payment_plan`
- accuracy of `earliest_date_for_full_payment`
- validity of `spending_changes_needed`
- usefulness and consistency of `decision_explanation`

### Token Usage And Cost Analysis

Your `code.zip` must include one token-usage file:

```text
evaluation/usage_report.md
```

The report must cover model providers and names, model calls, input and output tokens, total and average tokens per request, estimated total and per-request cost. The reported values must correspond to the final full-dataset run that produced your `output.csv`.

---

## Chat Transcript Logging

This repo includes an [`AGENTS.md`](./AGENTS.md) file for AI coding tools. It asks compatible tools to append conversation summaries to a `log.txt` in the repository root — the same directory as `AGENTS.md`:

| Platform | Path |
|---|---|
| macOS / Linux | `<repo root>/log.txt` |
| Windows | `<repo root>\log.txt` |

The path resolves relative to `AGENTS.md`, so it stays correct across clones, renames, and checkouts. `log.txt` is gitignored — upload it as your chat transcript at submission time. Do not paste secrets into the chat.

In case, the harness you are using is not in the repo root, you can explicitly ask the agent to look for the AGENTS.md in this folder & then continue.

---

## Submission

Submit the following files as instructed by HackerRank:

| File | Description |
|---|---|
| `code.zip` | Full runnable solution, prompts/configuration, README, and the required `evaluation/` folder |
| `output.csv` | Predictions for every row in `dataset/requests.csv` |
| `chat_transcript` | The `log.txt` described above, showing how you developed or used the system |

Before submitting, confirm:

- `output.csv` has one row per row in `dataset/requests.csv` (250 rows plus the header).
- `output.csv` has the exact required columns in the exact required order.
- Every `amount_safe_to_pay` satisfies `0 <= amount_safe_to_pay <= requested_amount`.
- Every installment plan matches a supplied payment option, and every spending change targets a flexible recurring expense.
- Your runnable code, setup instructions, and `evaluation/` folder are included in `code.zip`.
