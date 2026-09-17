"""
Content-addressed cache for evidence-layer model calls. Key = sha256 of the
full request payload (everything that determines the answer: the prompt
content, the tool schema, any context hint) plus the model tag, so a change
to any of those is a new key rather than a silent replay of a stale answer.

Always on -- the earlier design (evidence.py's per-run `_dev_cache`, keyed
loosely by id/hash and disabled in production) was a defensible call for a
hosted model graded once on cost transparency. It does not hold once these
calls might run against a local model, where a call is slow and schema
adherence weaker, so re-asking the same question can silently get a
different answer. Reversed here; see docs/FAILURES.md, first entry.
"""
import hashlib
import json
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "evidence"

MISS = object()


def _key(payload, model):
    blob = json.dumps({"payload": payload, "model": model}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get(payload, model):
    """Returns the cached value, or the MISS sentinel if there is none.
    A cached `None` is a legitimate resolved value (e.g. "no fact in this
    message") and must be distinguishable from a miss -- callers compare
    with `is cache.MISS`, never `is None`."""
    path = CACHE_DIR / f"{_key(payload, model)}.json"
    if not path.exists():
        return MISS
    return json.loads(path.read_text(encoding="utf-8"))["value"]


def put(payload, model, value):
    """Writes `value` (must be JSON-serializable) to the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_key(payload, model)}.json"
    path.write_text(json.dumps({"value": value}, indent=2), encoding="utf-8")
