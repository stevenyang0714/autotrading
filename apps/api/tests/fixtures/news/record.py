"""Re-record the news fixtures from GDELT and the configured feeds (opt-in, live network).

    cd apps/api && uv run python -m tests.fixtures.news.record [--feeds-only]

Runs the real job fetches (adapters/news), so the recorded URLs are exactly what replay
requests:
- `news.gdelt` for every configured equity over a fixed window (GDELT_WINDOW; GDELT's index was
  about four days behind on 2026-10-06, so the window ends where its data did);
- `news.rss.<id>` for every configured feed. What is recorded is the stripped feed the job
  stores (no full text), not the original response.
Also picks a real syndication case (one headline on several sites, naming a universe company)
for the integration tests, and fails if none exists.
"""

import json
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from autotrading.adapters.news.client import NewsRequestError
from autotrading.adapters.news.config import entities
from autotrading.adapters.news.gdelt import GdeltJob, articles
from autotrading.adapters.news.refresh import gdelt_params
from autotrading.adapters.news.rss import RSS_JOBS, job_name
from autotrading.domain.news import Company, canonical_url, find_mentions, normalize_title
from autotrading.ingestion.job import FetchContext, Window

HERE = Path(__file__).resolve().parent
GDELT_WINDOW = (datetime(2026, 9, 29, tzinfo=UTC), datetime(2026, 10, 2, 12, tzinfo=UTC))


def gdelt_throttle() -> None:
    time.sleep(20)  # GDELT asks for at most one request every 5 seconds; it counts per address


def no_throttle() -> None:
    pass


def main(argv: list[str]) -> None:
    feeds_only = "--feeds-only" in argv  # keep the recorded GDELT files, re-record the feeds
    files: dict[str, str] = {}
    runs: list[dict[str, Any]] = []
    gdelt = gdelt_params(*GDELT_WINDOW)
    # One equity at a time, saved as it arrives: GDELT throttles hard (often for minutes, from
    # a shared address), so a failed equity is skipped and a rerun resumes with the rest.
    progress = HERE / "gdelt_progress.json"
    done: dict[str, str] = json.loads(progress.read_text()) if progress.exists() else {}
    manifest_path = HERE / "manifest.json"
    if manifest_path.exists():  # keep GDELT files of an earlier recording; re-record feeds
        earlier = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
        done.update({u: n for u, n in earlier.items() if n.startswith("gdelt_")})
    for ticker in sorted(entities().companies):
        name = f"gdelt_{ticker}.json"
        if name in done.values() or feeds_only:
            continue
        try:
            (payload,) = GdeltJob({**gdelt, "tickers": [ticker]}, Window()).fetch(
                FetchContext(run_id=uuid4(), acquire=gdelt_throttle)
            )
        except NewsRequestError as exc:
            print(f"{ticker}: {exc}; skipped, rerun to retry")
            continue
        (HERE / name).write_bytes(payload.content)
        done[payload.source_url] = name
        progress.write_text(json.dumps(done, indent=2))
    recorded = sorted(name.removeprefix("gdelt_").removesuffix(".json") for name in done.values())
    if not recorded:
        raise SystemExit("GDELT refused every request; try again later")
    runs.append({"job": GdeltJob.name, "params": {**gdelt, "tickers": recorded}})
    files.update(done)
    for source_id, job_class in sorted(RSS_JOBS.items()):
        runs.append({"job": job_name(source_id), "params": {}})
        (payload,) = job_class({}, Window()).fetch(
            FetchContext(run_id=uuid4(), acquire=no_throttle)
        )
        name = f"feed_{source_id}.xml"
        (HERE / name).write_bytes(payload.content)
        files[payload.source_url] = name
        assert b"purl.org/rss/1.0/modules/content" not in payload.content, source_id

    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "gdelt_window": [t.isoformat() for t in GDELT_WINDOW],
        "gdelt_not_recorded": sorted(set(entities().companies) - set(recorded)),
        "stripped": "feeds are stored as the jobs store them: full text removed, summaries cut "
        "to 300 characters (adapters/news/rss.py strip_full_text)",
        "runs": runs,
        "files": files,
        "syndication_case": _syndication_case(files),
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    progress.unlink(missing_ok=True)
    print(f"recorded {len(files)} files into {HERE}")


def _syndication_case(files: dict[str, str]) -> dict[str, Any]:
    """The headline naming a universe company that the most distinct sites carried."""
    companies = [
        Company(ticker, tuple(cfg.aliases), cfg.bare_ticker)
        for ticker, cfg in entities().companies.items()
    ]
    copies: dict[str, dict[str, str]] = defaultdict(dict)  # title key -> domain -> url
    titles: dict[str, str] = {}
    for name in files.values():
        if not name.startswith("gdelt_"):
            continue
        for article in articles((HERE / name).read_bytes()):
            title = str(article.get("title") or "")
            key = normalize_title(title)
            if len(key.split()) < 4 or not find_mentions(title, companies):
                continue
            copies[key].setdefault(str(article["domain"]), canonical_url(str(article["url"])))
            titles[key] = title
    if not copies:
        raise SystemExit("no GDELT article names a universe company")
    key = max(copies, key=lambda k: (len(copies[k]), k))
    if len(copies[key]) < 2:
        raise SystemExit("no headline was carried by two or more sites")
    return {"title": titles[key], "title_key": key, "canonical_urls": sorted(copies[key].values())}


if __name__ == "__main__":
    main(sys.argv[1:])
