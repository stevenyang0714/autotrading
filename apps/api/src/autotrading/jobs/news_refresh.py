"""Manual news refresh (inside the api container):

    make news-refresh    # GDELT (last 24 hours) and every enabled feed, now
    make news-backfill   # GDELT, one run per day over the last 14 days (run once)

The worker executes the runs (GDELT allows about one request every 10 seconds, so a GDELT run
takes a few minutes); progress shows on the Data Health page.
"""

import logging
import sys

from autotrading.jobs import actors


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if "--backfill" in argv:
        runs = actors.start_news_gdelt_backfill()
        if not runs:
            print("gdelt is not enabled in config/sources.yaml.")
            return 1
        print(f"Queued {len(runs)} news.gdelt backfill runs (one per day)")
        return 0
    gdelt = actors.start_news_gdelt(manual=True)
    feeds = actors.start_news_feeds(manual=True)
    if gdelt is None and not feeds:
        print("No news source is enabled in config/sources.yaml.")
        return 1
    print(
        ("Queued news.gdelt run " + str(gdelt) if gdelt else "GDELT not enabled")
        + f"; {len(feeds)} feed runs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
