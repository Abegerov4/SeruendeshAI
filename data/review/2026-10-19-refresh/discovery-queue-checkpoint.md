# Discovery queue checkpoint

Frozen at 2026-10-19T00:01:53.966658+00:00 for repository review. The candidate-discovery process is still running in shell session 60592. It began with 1091 no-website food rows; this checkpoint records 330 rows started and 660 actual public-source requests. These are attempts and unreviewed candidates, not confirmed facts. There are zero confirmed no-information results and zero exhaustive source reviews.

The active pass uses public 2GIS name searches and Bing searches containing the canonical name and address. Actual request URLs are recorded. For 2GIS, the event query metadata also retains the full branch locator for review; the actual URL uses the name alone. Exact address or independent coordinates within 200 m must be reviewed before a candidate can be accepted.

Yandex Maps search returned 429 and its persistent provider circuit remains blocked. Skipped rows issue no Yandex requests. Google search returned 429 and DuckDuckGo required a human challenge during feasibility probes; neither was bypassed. A 403/429 or detected challenge stops further calls to that provider. Empty search results and source failures never authorize exclusion.

## Continue

Leave session 60592 running. After it finishes or stops, resume from the append-only ledger with:

```sh
.venv/bin/python data/review/2026-10-19-refresh/discovery-queue.py --limit 2000 --max-requests 2500 --delay 1.25
```

Recorded row/provider attempts are skipped. --retry-incomplete can revisit ordinary source errors while respecting persistent provider blocks. Do not clear blocks merely to force coverage. For a summary without network, run the same command with --prepare-only.

The runner writes only local discovery candidates, cache, ledger, provider state and summary. It never changes canonical records, accepted facts or quarantine. Minimum three independent successful source checks and an explicit completed human source review are required before no-information can be marked; three empty pages alone are insufficient.

The authoritative moving ledger is discovery-queue-events.jsonl. Cache, ledger, host state and runtime summary are local moving files; this checkpoint and discovery-final-review.json are frozen review artifacts. The unfinished wider queue must not be described as whole-catalog verified enrichment.
