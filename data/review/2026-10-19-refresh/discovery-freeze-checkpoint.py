#!/usr/bin/env python3
"""Freeze a bounded discovery run without committing raw HTTP caches or live state."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    raw = (HERE / "discovery-queue-events.jsonl").read_bytes()
    events = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    queue = json.loads((HERE / "discovery-queue.json").read_text())
    summary = json.loads((HERE / "discovery-queue-summary.json").read_text())
    targets = {r["id"] for r in queue["records"]}
    latest = {(e["canonical_id"], e["provider"]): e for e in events}
    complete = all((ident, provider) in latest for ident in targets for provider in ("2gis", "bing"))
    assert complete, "Do not label a partial pass finished"
    frozen = datetime.now(timezone.utc).isoformat()
    status = {
        "frozen_at": frozen, "pass_status": "bounded_discovery_pass_finished",
        "finished_at": summary["generated_at"], "launch_rows": len(targets),
        "rows_with_bounded_2gis_bing_outcomes": len(targets), "events": len(events),
        "actual_requests": sum(bool(e.get("actual_request")) for e in events),
        "event_outcomes": dict(Counter(e["outcome"] for e in events)),
        "provider_outcomes": {p: dict(Counter(e["outcome"] for e in events if e["provider"] == p))
                              for p in ("2gis", "bing", "yandex_maps")},
        "live_ledger_sha256": hashlib.sha256(raw).hexdigest(),
        "branch_fact_verification_complete": False, "no_information_confirmed": 0,
        "completed_exhaustive_searches": 0,
        "limitations": ["A bounded two-provider pass is not independent verification of every branch.",
                        "Yandex remained blocked after 429; Google 429 and DuckDuckGo human challenge were not bypassed.",
                        "Source errors and empty searches never establish closure or absence of information.",
                        "Candidates require separate exact-branch and field-specific review before publication."],
    }
    fields = ("canonical_id", "provider", "source_url", "final_url", "query", "checked_at", "actual_request",
              "http_status", "outcome", "error", "response_sha256", "row_sha256", "blocked_since", "reason")
    with (HERE / "discovery-checkpoint-events.jsonl").open("w") as handle:
        for event in events:
            record = {key: event[key] for key in fields if key in event}
            record["candidate_urls"] = [c["source_url"] for c in event.get("candidates", [])]
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary.update(pass_status=status["pass_status"], frozen_at=frozen,
                   branch_fact_verification_complete=False, live_ledger_sha256=status["live_ledger_sha256"])
    write(HERE / "discovery-checkpoint-summary.json", summary)
    write(HERE / "discovery-queue-live-status.json", status)
    (HERE / "discovery-queue-checkpoint.md").write_text(f"""# Discovery queue checkpoint

Frozen at {frozen}. Session 60592 finished successfully: all **{len(targets)} launch rows** have bounded public 2GIS/Bing outcomes from **{status['actual_requests']} actual requests**. The pass ended at {status['finished_at']}; no background process remains. This finishes the bounded discovery pass, not branch verification or an exhaustive internet search. Confirmed no-information results: **0**. Exhaustive branch searches: **0**.

Outcomes: {json.dumps(status['event_outcomes'], ensure_ascii=False)}. The versioned condensed ledger records actual request URLs, source hashes, errors and candidate URLs. Raw response text, the original live ledger and HTTP caches remain local and ignored. The complete local ledger SHA-256 is `{status['live_ledger_sha256']}`.

The public 2GIS search URL uses the name alone; its query metadata also retains the canonical address for review. Bing URLs include the canonical name/address. Exact distinctive name plus matching address or independently checked coordinates within 200 m is required. Address conflicts and possible rebrands remain held. A source's lack of an attribute means unknown.

Yandex Maps search returned 429 before the pass and was skipped for every row without new requests. Google returned 429 and DuckDuckGo required a human challenge during earlier feasibility probes. No block was bypassed. A minimum of three distinct successful providers plus an explicit completed human review is required before a no-information conclusion; neither two providers nor three empty pages establishes that conclusion.

## Continue later

Review the versioned branch decisions and accepted sidecar before another network pass. To retry only ordinary source failures while respecting persistent blocks, use the local resumable runner after choosing an explicit new bounded pass:

```sh
.venv/bin/python data/review/2026-10-19-refresh/discovery-queue.py --providers 2gis bing --retry-incomplete --limit 2000 --max-requests 460 --delay 1.25
```

The runner prepares a new queue from the unchanged master and excludes already accepted detail rows; its row count may therefore be smaller than the original 1091. Do not relabel this frozen launch cohort. Successful provider attempts are skipped, ordinary failures can be retried, and persistent provider circuits remain respected. Never delete or mark closed from an empty result, 404, timeout or challenge. The discovery runner never modifies canonical rows, quarantine or accepted facts.
""")
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
