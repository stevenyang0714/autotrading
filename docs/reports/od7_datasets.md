# OD-7 Survivorship-free US equity history: dataset comparison

**Status:** For Steven's decision. Checked 2026-10-12 from each provider's public pages (linked); prices change, so re-check the provider's page on the day of purchase. Nothing has been bought or connected, and no provider is added to `config/sources.yaml` until Steven decides (ADR-029).

**Why it matters:** backtests on today's universe ignore the companies that were delisted, merged away or dropped from the index, so their results look better than reality (survivorship bias). Until OD-7 is decided, the Strategy Lab (M2.5) shows a backtest's method, trades and costs but **not its performance**, with the reason (M2 file, P2-2).

**What Phase 2 needs:**
- daily prices of delisted US equities, adjusted for splits and dividends, from about 2005;
- the S&P 500 membership on each past date (who was in the index then);
- REST or file access that works from Python on macOS;
- a personal, non-professional license (ADR-001: no redistribution).

## Comparison

| Provider | Delisted prices | Index membership history | Fundamentals | Access on macOS | Personal-use license | Price (2026-10-12) |
|---|---|---|---|---|---|---|
| **Sharadar, bought directly** | About 21,000 active and delisted tickers from December 1997: split-adjusted OHLCV, a close adjusted for splits, dividends and spinoffs, and the unadjusted close ([stocks docs](https://www.sharadar.com/docs/stocks)) | S&P 500, from January 1998 ([sp500 docs](https://www.sharadar.com/docs/sp500)) | From 1998, delisted included; the "AR" dimensions are point in time, keyed to the 10-K/10-Q filing date ([fundamentals docs](https://www.sharadar.com/docs/fundamentals)) | REST (api.sharadar.com) and bulk zip downloads; no operating-system dependency ([llms.txt](https://www.sharadar.com/llms.txt)) | Individuals, non-professional only; no sharing; the data must be deleted within 30 days of cancelling, backtest outputs may be kept ([terms](https://www.sharadar.com/terms)) | **Prices**, full history, including the `sp500`, `actions` and `tickers` tables: **USD 39/month or 299/year**. **Bundle** with fundamentals: **USD 69/month or 499/year** ([subscribe](https://www.sharadar.com/subscribe)) |
| **Norgate Platinum / Diamond** | Platinum from 1990, Diamond from 1950; dividends and capital events, configurable adjustment | S&P 500 (from 1957), S&P 100/400/600/1500, Russell 1000/2000/3000 (from July 1990), Nasdaq-100, DJIA and others ([content tables](https://norgatedata.com/data-content-tables.php)) | Current snapshot only, no history | The `norgatedata` Python package and its NDU updater run on Windows only; on a Mac this needs a Windows virtual machine (e.g. Parallels). Native Mac support is "planned medium term" ([PyPI](https://pypi.org/project/norgatedata/), [NDU FAQ](https://norgatedata.com/ndu-faq.php)) | Personal, non-commercial; two machines; extracted data may be processed on any system while subscribed ([FAQ](https://norgatedata.com/faq.php)) | Platinum **USD 630 per 12 months** (346.50 per 6 months); Diamond **787.50 per 12 months**; no monthly plan ([packages](https://norgatedata.com/stockmarketpackages.php)) |
| **CRSP via WRDS** | The reference dataset, from 1926 | S&P 500 and others | Through Compustat | WRDS web and Python | Academic, non-commercial research under the institution's agreement; personal investing is almost certainly excluded ([example library guide](https://guides.libraries.psu.edu/WRDS)) | Not sold to individuals |
| **Massive (formerly Polygon)** | Partly: the tickers endpoint marks delisted names, but the bar endpoints do not say whether delisted symbols are served; bars are adjusted for splits only; history from September 2003 ([tickers](https://massive.com/docs/rest/stocks/tickers/all-tickers.md), [bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars.md)) | None (ETF holdings only) | Financials on the Advanced plan | REST, S3 flat files, Python client | Individual use; Advanced is for non-professionals; redistribution needs a business plan ([terms](https://massive.com/legal/market-data-terms-of-service)) | Starter USD 29/month (5 years), Developer 79 (10 years), **Advanced 199/month** (full history); about 20% off yearly ([pricing](https://massive.com/pricing)) |
| **EODHD** | Yes, but names delisted before 2018 have end-of-day prices without splits or dividends ([delisted page](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)) | Add-on for S&P 500/400/100/600, **about 12 years** (from about 2014) | Separate plan, USD 59.99/month | REST | Personal plans | USD 19.99/month or 199/year, plus **29.99/month** for constituents ([pricing](https://eodhd.com/pricing), [add-on](https://eodhd.com/financial-apis/sp-and-dow-jones-indices-historical-constituents-data-api)) |
| **Tiingo** | Not confirmed | None | Add-on, price on request | REST | "Internal use only" | Power USD 30/month or 300/year ([pricing](https://www.tiingo.com/about/pricing)) |
| **QuantConnect** | Through its security master and AlgoSeek prices | Not checked | Not checked | Usable **only inside its LEAN engine** ([dataset](https://www.quantconnect.com/data/quantconnect-us-equity-security-master)) | Not checked | Not verified |

## Recommendation

**First choice: Sharadar Prices, bought directly (USD 299 a year).**
- It covers what Phase 2 needs: delisted prices from 1998 adjusted for splits, dividends and spinoffs, the S&P 500 membership history, corporate actions and a stable identifier per security.
- It is a plain REST API and bulk files, so it fits the existing Python adapters on macOS with no Windows machine.
- Its history covers backtests starting anywhere from 2005 to 2016.
- The Bundle (USD 499 a year) only adds a cross-check of our EDGAR fundamentals against Sharadar's point-in-time data; not needed for Phase 2.
- The license requires deleting the stored dataset within 30 days of cancelling; stored backtest results may be kept. With the append-only tables, deletion would need a planned procedure before signing up.

**Second choice: Norgate Platinum (USD 630 a year), only if more than the S&P 500 is needed** (S&P 400/600, Russell or Nasdaq-100 membership). It needs a Windows virtual machine to run the updater and export files to the Mac.

**Not recommended:**
- **Massive:** no index membership, and full history costs USD 199 a month (P2-1 already defers Massive).
- **EODHD:** membership history only from about 2014, and names delisted before 2018 lack adjustments.
- **CRSP:** its licensing does not cover personal investing.

## What deciding means for the build

- **If Steven buys Sharadar:** a new source in `config/sources.yaml` (license status, personal use), an adapter behind the price and membership interfaces, a backfill of the delisted names and the S&P 500 membership since 2005, and the Strategy Lab may then report performance with the survivorship check. Planned with M2.5, in plan mode first.
- **If Steven decides not to buy now:** backtests stay on the current 10 equities and 8 ETFs and report method, trades and costs only (the default in P2-2). M2.1 to M2.4 do not depend on OD-7.

## Could not verify

- Sharadar's price on Nasdaq Data Link (needs a login); Sharadar now sells personal licenses directly and points professionals to Nasdaq.
- Where Sharadar's S&P 500 history starts: its own docs say January 1998, another vendor (QuantRocket) says 1957.
- Whether Massive's bars serve delisted symbols, and how it handles reused tickers.
- Which EODHD plans include delisted tickers.
- Tiingo's delisted coverage.
- FMP's prices (its pricing page refused the request); it does list historical S&P 500 constituents and delisted companies.
- QuantConnect and AlgoSeek prices.
- Whether Norgate's updater runs under Windows 11 on Apple Silicon in Parallels (Norgate names Parallels but not ARM).
- INSEAD's own WRDS terms.
- Whether Norgate's 12-month price on its page is current (the page is undated).
