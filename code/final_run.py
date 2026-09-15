"""One-shot script for the official, submitted final run: live evidence
extraction (no dev cache), writes output.csv and evaluation/usage_report.md
from the SAME run, then runs the invariant sweep on the result."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence
evidence.DEV_CACHE_ENABLED = False  # LOCKED DECISION: official run is live, no cache

import main as main_mod
import usage_tracker
import validate
import ingest

usage_tracker.reset()
rows = main_mod.process_all("requests.csv")
print(f"Processed {len(rows)} requests")

repo_root = Path(__file__).resolve().parent.parent
main_mod.write_output(rows, repo_root / "output.csv")
print("Wrote output.csv")

usage_tracker.write_report(repo_root / "code" / "evaluation" / "usage_report.md", len(rows))
print("Wrote usage_report.md")

s = usage_tracker.summary()
print(f"Final run usage: {s['n_calls']} calls, ${s['cost']:.4f}")

requests = {r["request_id"]: r for r in ingest.load_requests("requests.csv")}
problems = validate.sweep(rows, requests)
print(f"invariant violations: {len(problems)}/250")
for rid, v in problems.items():
    print(f"  {rid}: {v}")
print("DONE")
