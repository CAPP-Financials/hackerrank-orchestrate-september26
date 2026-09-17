# FAILURES.md

Numbered, append-only record of every failure/decision-reversal hit while
building this submission. Each entry: exact incorrect behavior or
superseded decision → root cause → fix → measured effect.

## F-001 — "No caching in production" reversed for local-model deployment (2026-09-17)

- Prior decision: `evidence.py` shipped a per-run `_dev_cache`
  (`DEV_CACHE_ENABLED = False` in production), on the explicit ground
  that the graded submission's official run should make every call live
  against the hosted `claude-sonnet-5` model, for clean cost-transparency
  reporting.
- Why it stopped holding: the same evidence layer is being reused for a
  personal deployment against a local Ollama model, where a call takes
  seconds rather than milliseconds and schema adherence is weaker, so
  re-asking the same question can silently return a different answer
  rather than a cheap, deterministic replay.
- Fix: `code/cache.py` — a content-addressed cache keyed on
  `sha256(payload + model)`, where `payload` includes the tool schema,
  so any change to the prompt, schema, or model produces a new key
  instead of a stale replay. Always on, not a dev-only toggle. Wired
  into both `evidence.extract_image_amount` and
  `evidence.extract_message_fact`.
- Measured effect: `tests/test_cache.py` — cache miss returns a
  distinguishable sentinel (`cache.MISS`, not `None`, since a resolved
  "no fact" is a legitimate cached value); a model/schema change
  produces a different key; `extract_message_fact` never calls the
  model again once an answer is cached (verified by making the model
  call raise if invoked after a pre-populated cache hit).
