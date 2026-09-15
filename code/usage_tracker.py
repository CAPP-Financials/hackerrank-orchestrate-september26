"""
Wraps every model call, accumulates tokens/cost, emits usage_report.md.

Must reflect the run that actually produced the submitted output.csv --
per the locked decision, generated in the same breath as the final Stage 4
run, never decoupled or amortized from an earlier run (goal graph Node 5
repair: a stale report is a silent submission defect).
"""
from pathlib import Path

# Anthropic list pricing per 1M tokens (USD), Sonnet-5 tier -- update if
# pricing changes; keep the number here, not scattered through the file.
PRICE_PER_M_INPUT = 3.00
PRICE_PER_M_OUTPUT = 15.00

_calls = []


def record(response, call_type):
    """response: an anthropic Message object (has .usage.input_tokens /
    .output_tokens). call_type: 'image_extraction' | 'message_extraction'."""
    u = response.usage
    _calls.append({
        "type": call_type,
        "model": response.model,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
    })


def reset():
    _calls.clear()


def summary():
    if not _calls:
        return {"n_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
    total_in = sum(c["input_tokens"] for c in _calls)
    total_out = sum(c["output_tokens"] for c in _calls)
    cost = (total_in / 1_000_000 * PRICE_PER_M_INPUT) + (total_out / 1_000_000 * PRICE_PER_M_OUTPUT)
    by_type = {}
    for c in _calls:
        t = c["type"]
        by_type.setdefault(t, {"n_calls": 0, "input_tokens": 0, "output_tokens": 0})
        by_type[t]["n_calls"] += 1
        by_type[t]["input_tokens"] += c["input_tokens"]
        by_type[t]["output_tokens"] += c["output_tokens"]
    return {"n_calls": len(_calls), "input_tokens": total_in, "output_tokens": total_out,
            "cost": cost, "by_type": by_type}


def write_report(out_path, n_requests):
    s = summary()
    lines = [
        "# Usage Report",
        "",
        "Final full-dataset run that produced `output.csv`.",
        "",
        "## Model",
        "",
        "- Provider: Anthropic",
        "- Model: claude-sonnet-5 (Stage 2 evidence extraction only -- the forecast/",
        "  planning engine, Stages 1/3-9, is deterministic code, no model calls)",
        "",
        "## Calls",
        "",
        f"- Total model calls: {s['n_calls']}",
    ]
    for t, d in s.get("by_type", {}).items():
        lines.append(f"  - {t}: {d['n_calls']} calls, "
                      f"{d['input_tokens']} input tokens, {d['output_tokens']} output tokens")
    lines += [
        "",
        "## Tokens",
        "",
        f"- Total input tokens: {s['input_tokens']}",
        f"- Total output tokens: {s['output_tokens']}",
        f"- Total tokens: {s['input_tokens'] + s['output_tokens']}",
        f"- Requests processed: {n_requests}",
        f"- Average tokens per request: {(s['input_tokens'] + s['output_tokens']) / n_requests:.1f}"
        if n_requests else "- Average tokens per request: n/a",
        "",
        "## Cost",
        "",
        f"- Rate: ${PRICE_PER_M_INPUT}/1M input tokens, ${PRICE_PER_M_OUTPUT}/1M output tokens "
        "(Anthropic list pricing, Sonnet-5 tier)",
        f"- Estimated total cost: ${s['cost']:.4f}",
        f"- Estimated cost per request: ${(s['cost'] / n_requests):.6f}" if n_requests else "- n/a",
        "",
    ]
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
