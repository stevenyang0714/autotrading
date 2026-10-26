"""The Taiwan universe from the TWSE OpenAPI (M3.7, ADR-039), inside the api container:

    python -m autotrading.jobs.twse_refresh             # `make twse-refresh`: queue a run now
    python -m autotrading.jobs.twse_refresh --companies # the run also fetches the company file
    python -m autotrading.jobs.twse_refresh --factors   # `make twse-factors`: Taiwan snapshots
    python -m autotrading.jobs.twse_refresh --factors-backfill  # every session since 2016
    python -m autotrading.jobs.twse_refresh --rank      # `make twse-rank`: the market caps

--rank recomputes the market-cap ranking (TW2) from the latest stored STOCK_DAY_ALL and company
files and compares its top 10 with config/universe_tw.yaml (frozen: a difference is reported,
never applied).
"""

import argparse
import json
import sys
from decimal import Decimal

from sqlalchemy import select

from autotrading.adapters.twse.client import COMPANIES, DAY, SOURCE_ID, public_url
from autotrading.db.models import RawPayload
from autotrading.domain.twse import company_rows, day_rows, rank_market_cap, session_of
from autotrading.infra.object_store import make_s3_client
from autotrading.jobs import actors
from autotrading.repositories.universe import taiwan_universe
from autotrading.settings import get_settings

TRILLION = Decimal(10) ** 12


def _latest(path: str) -> tuple[bytes, str] | None:
    settings = get_settings()
    with actors.sessions()() as session:
        row = session.scalars(
            select(RawPayload)
            .where(RawPayload.source_id == SOURCE_ID, RawPayload.source_url == public_url(path))
            .order_by(RawPayload.fetched_at.desc())
            .limit(1)
        ).first()
    if row is None:
        return None
    body = make_s3_client(settings).get_object(Bucket=settings.s3_bucket, Key=row.object_key)
    return body["Body"].read(), row.sha256


def rank() -> int:
    day, companies = _latest(DAY), _latest(COMPANIES)
    if day is None or companies is None:
        print("No stored STOCK_DAY_ALL or company file yet: run `make twse-refresh` first.")
        return 1
    days = day_rows(json.loads(day[0]))
    ranked = rank_market_cap(days, company_rows(json.loads(companies[0])))
    print(f"Market caps on {session_of(days)} (TWD trillion):")
    for place, r in enumerate(ranked[:15], 1):
        print(f"  {place:2d} {r.code} {r.name}  {r.market_cap / TRILLION:.2f}")
    print(f"STOCK_DAY_ALL sha256 {day[1]}\nt187ap03_L    sha256 {companies[1]}")
    frozen = list(taiwan_universe().equities)
    top = [r.code for r in ranked[:10]]
    if top == frozen:
        print("The top 10 equals config/universe_tw.yaml.")
    else:
        print(f"The top 10 differs from config/universe_tw.yaml (frozen, not changed): {top}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", action="store_true")
    parser.add_argument("--factors", action="store_true")
    parser.add_argument("--factors-backfill", action="store_true")
    parser.add_argument("--rank", action="store_true")
    args = parser.parse_args()
    if args.rank:
        return rank()
    if args.factors_backfill:
        years = actors.start_taiwan_factor_backfill()
        print(f"Queued the Taiwan factor backfill: {years} years (ADR-040 TW17).")
        return 0
    if args.factors:
        actors.start_taiwan_factor_evaluation(manual=True)
        print("Queued the Taiwan factor snapshots (definitions for market TW).")
        return 0
    run_id = actors.start_twse_refresh(manual=True, companies=args.companies)
    print(
        "TWSE refresh skipped: twse_openapi is not enabled."
        if run_id is None
        else f"Queued {run_id}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
