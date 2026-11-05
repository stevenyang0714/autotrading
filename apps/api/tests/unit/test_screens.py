"""The Taiwan screens (M3.11, ADR-042) on recorded responses: the rule file pinned to its hash,
returns across ex-dates (SC6), the movers' readings against a direct computation (SC7), the
screens and their watch lists over 30 recorded sessions (SC8, SC9), the coverage and history
gates (SC10) and the history summary (SC13)."""

import math
import statistics
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest
import yaml

from autotrading.adapters.finmind.client import DIVIDENDS
from autotrading.config_sync import load_screen_rules
from autotrading.domain.delivery import MAX_MESSAGE, _notes, screen_report
from autotrading.domain.finmind import dividend_results, price_rows
from autotrading.domain.provenance import end_of_day
from autotrading.domain.screens import (
    CloseBelowLevel,
    Company,
    DailyBar,
    NoteReading,
    PreviousRun,
    ScreenRuleSet,
    ScreenRulesFile,
    ScreenRunOut,
    StockReading,
    _invalidated,
    adjusted_window,
    describe,
    evaluate,
    history_summary,
    previous_of,
    read_stock,
)
from autotrading.domain.twse import company_rows, day_rows, ex_right_rows
from autotrading.repositories.delivery import load_delivery_rules
from autotrading.repositories.listed import industry_names
from autotrading.settings import get_settings
from tests.finmind_replay import PRICE_CODES, payload, price_history
from tests.twse_replay import payload as twse_payload

CONFIG = Path(get_settings().resolved_config_dir())
PINNED = {
    "0.1.0": "cf10f6d4deb1059efcf5562aef9bd593732dfa2c82e8a25fa83da3df701733a9",
    # not judged while the history is backfilled (SC10)
    "0.2.0": "66087bd1dbf7b785c5f632410053f68cbe4028b6ee96337549f4eb868a8644d0",
}
TAIPEI = "Asia/Taipei"


def rules_file() -> ScreenRulesFile:
    return ScreenRulesFile.model_validate(
        yaml.safe_load((CONFIG / "screen_rules.yaml").read_text(encoding="utf-8"))
    )


RULES = rules_file().active()
NAMES = {c.code: c for c in company_rows(twse_payload("d1", "t187ap03_L"))}
COMPANIES = {c: Company(c, NAMES[c].short_name, NAMES[c].industry) for c in PRICE_CODES}


def recorded(code: str, *, references: bool = True) -> list[DailyBar]:
    """A recorded FinMind price history as bars, with each ex-date's reference price from the
    recorded ex-dividend results (2330 and 2881)."""
    refs = (
        {r.ex_date: float(r.reference_price) for r in dividend_results(payload(code, DIVIDENDS))}
        if references and code in ("2330", "2881")
        else {}
    )
    return [
        DailyBar(
            session=r.session,
            open=float(r.open or 0),
            high=float(r.high or 0),
            low=float(r.low or 0),
            close=float(r.close),
            close_text=str(r.close),
            volume=float(r.volume),
            trade_value=float(r.value),
            change=float(r.change) if r.change is not None else None,
            reference=refs.get(r.session),
            cash=None,
            stock_ratio=None,
            feed="finmind",
            feed_status="end_of_day",
            row_id=f"{code}-{r.session}",
            published_at=end_of_day(r.session, TAIPEI),
        )
        for r in price_rows(price_history(code)[0])
        if r.close is not None and r.close > 0
    ]


BARS = {code: recorded(code) for code in PRICE_CODES}
SESSIONS = sorted({b.session for bars in BARS.values() for b in bars})


def run_at(session: date, previous: PreviousRun | None = None) -> ScreenRunOut:
    sessions = SESSIONS[: SESSIONS.index(session) + 1]
    return evaluate(
        RULES,
        known_at=end_of_day(session, TAIPEI),
        companies=COMPANIES,
        bars={c: [b for b in bars if b.session <= session] for c, bars in BARS.items()},
        sessions=sessions,
        flows={},
        previous=previous,
        industry_basis="as_known",
    )


def test_the_rule_file_has_one_active_set_pinned_to_its_hash() -> None:
    file = rules_file()
    assert load_screen_rules(CONFIG / "screen_rules.yaml").active() == RULES  # `make migrate`
    assert {r.rule_version: r.rule_set().content_sha256() for r in file.rule_sets} == PINNED
    assert RULES.market == "TW" and RULES.exclude_industries == ["91"]
    swing, breakout = RULES.screens
    assert describe(RULES, swing)["conditions"] == [
        "20 日平均成交值 ≥ NT$3,000 萬",
        "收盤價高於 20 日均線",
        "20 日均線高於 5 日前",
        "收盤價高於 60 日均線",
        "同產業有流動性的股票中 ≥ 50% 站上 20 日均線（≥ 5 檔才判斷）",
    ]
    assert describe(RULES, breakout)["invalidation"] == [
        "收盤跌回突破價之下",
        "觀察滿 20 個交易日且不再符合條件",
    ]
    assert describe(RULES, swing)["notes"] == [
        "外資近 5 日至少 3 日買超",
        "投信近 5 日至少 3 日買超",
    ]
    # a window too short for a condition is refused
    with pytest.raises(ValueError, match="window_sessions"):
        ScreenRuleSet.model_validate({**RULES.content(), "window_sessions": 30})


def test_an_ex_date_is_not_a_fall() -> None:
    """SC6: 2330 went ex a cash dividend on 2026-09-16 (previous close 2385, reference 2377.99,
    close 2380): the session's return is against the reference, and the closes before it are
    moved to its basis. Without the results the day is an unexplained gap, a raw ratio."""
    bars = BARS["2330"]
    sessions = [b.session for b in bars]
    window = adjusted_window(bars, sessions)
    i = sessions.index(date(2026, 9, 16))
    assert window.returns[i - 1] == pytest.approx(2380 / 2377.99 - 1)
    assert window.levels[i] / window.levels[i - 1] == pytest.approx(2380 / 2377.99)
    (event,) = [e for e in window.events if e.session == date(2026, 9, 16)]
    assert event.source == "ex_reference" and event.factor == pytest.approx(2377.99 / 2385)
    assert sum(e.source == "ex_reference" for e in window.events) == 6
    raw = adjusted_window(recorded("2330", references=False), sessions)
    (gap,) = [e for e in raw.events if e.session == date(2026, 9, 16)]
    assert gap.source == "unexplained" and raw.returns[i - 1] == pytest.approx(2380 / 2385 - 1)


def test_a_twse_ex_date_takes_its_reference_from_the_announced_dividend() -> None:
    """SC6: TWSE states a change of 0 for 0056 on its ex-date 2026-10-22; the reference is the
    previous close less the cash dividend TWT48U_ALL announced (58.75 - 1.72)."""
    rows = {
        d: {r.code: r for r in day_rows(twse_payload(d, "STOCK_DAY_ALL"))} for d in ("d1", "d2")
    }
    (told,) = [r for r in ex_right_rows(twse_payload("d1", "TWT48U_ALL")) if r.code == "0056"]

    def bar(day: str, cash: Decimal | None) -> DailyBar:
        r = rows[day]["0056"]
        assert r.close is not None and r.open is not None and r.high is not None
        assert r.low is not None
        return DailyBar(
            session=r.session,
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            close_text=str(r.close),
            volume=float(r.volume),
            trade_value=float(r.value),
            change=float(r.change) if r.change is not None else None,
            reference=None,
            cash=float(cash) if cash is not None else None,
            stock_ratio=None,
            feed="twse",
            feed_status="end_of_day",
            row_id=f"0056-{day}",
            published_at=end_of_day(r.session, TAIPEI),
        )

    sessions = [date(2026, 10, 21), date(2026, 10, 22)]
    window = adjusted_window([bar("d1", None), bar("d2", told.cash)], sessions)
    assert window.returns == (pytest.approx(56.30 / (58.75 - 1.72) - 1),)
    assert window.events[0].source == "dividend"
    untold = adjusted_window([bar("d1", None), bar("d2", None)], sessions)
    assert untold.events[0].source == "unexplained"


def test_the_movers_readings_match_a_direct_computation() -> None:
    """SC7 on 2454 at 2026-10-22: z1, z5 and the volume ratio from its own closes and volumes
    (its window has no adjusting event, so its returns are the raw ratios)."""
    reading = read_stock(RULES, COMPANIES["2454"], BARS["2454"], SESSIONS)
    assert isinstance(reading, StockReading)
    assert not any(e.source in ("ex_reference", "dividend") for e in reading.window.events)
    closes = [b.close for b in reading.window.bars]
    volumes = [b.volume for b in reading.window.bars]
    returns = [b / a - 1 for a, b in pairwise(closes)]
    sigma = statistics.stdev(returns[-61:-1])
    assert reading.z1 == pytest.approx(returns[-1] / sigma, rel=1e-12)
    assert reading.z5 == pytest.approx((closes[-1] / closes[-6] - 1) / (sigma * math.sqrt(5)))
    assert reading.volume_ratio == pytest.approx(volumes[-1] / statistics.fmean(volumes[-21:-1]))
    assert reading.liquid  # MediaTek trades far above NT$30m a session


def test_the_screens_and_watch_lists_over_thirty_recorded_sessions() -> None:
    previous = None
    runs: dict[date, ScreenRunOut] = {}
    for session in SESSIONS[-30:]:
        run = run_at(session, previous)
        assert run.status == "judged" and run.coverage.covered == run.coverage.expected == 6
        runs[session] = run
        previous = previous_of(run)
        assert run_at(session, previous) is not None

    def states(session: date, screen: int = 0) -> dict[str, str]:
        return {line.code: line.state for line in runs[session].screens[screen].lines}

    assert {c for c, s in states(date(2026, 9, 8)).items() if s == "entered"} == {
        "2330",
        "2408",
        "2454",
        "2881",
    }
    (ended,) = [x for x in runs[date(2026, 9, 11)].screens[0].lines if x.state == "invalidated"]
    assert (ended.code, ended.reason) == ("2408", "連續 2 日收盤低於 20 日均線")
    assert [m.code for m in runs[date(2026, 10, 15)].movers] == ["3711"]
    assert runs[date(2026, 10, 15)].movers[0].score == Decimal("2.6578")
    # 2881 stays while it meets the screen, and ends once it no longer does after 20 sessions
    assert states(date(2026, 10, 20)) == {"2881": "expired"}
    assert states(date(2026, 10, 21)) == {"2881": "entered"}
    fubon = runs[date(2026, 10, 22)].screens[0].lines[0]
    breadth = next(c for c in fubon.conditions if c.kind == "industry_breadth_min")
    assert breadth.status == "not_applicable"  # one liquid company in industry 17 here
    assert runs[date(2026, 10, 22)].breadth["24"].members == 5
    assert all(s.meeting == 0 for r in runs.values() for s in r.screens[1:])  # no breakout
    # the same inputs give the same document
    again = run_at(date(2026, 10, 22), previous_of(runs[date(2026, 10, 21)]))
    assert again.model_dump() == runs[date(2026, 10, 22)].model_dump()
    summary = history_summary(
        [s.screen_id for s in RULES.screens], [r.counts() for r in runs.values()]
    )
    assert summary[0].sessions == 30 and summary[0].max_meeting == 6
    assert summary[1].zero_share == Decimal(1)
    assert not any("return" in field for field in summary[0].model_dump())  # OD-7


def test_a_breakout_ends_below_its_level() -> None:
    """SC9: a range breakout's watch ends when the close falls below the level it broke."""
    reading = read_stock(RULES, COMPANIES["2330"], BARS["2330"], SESSIONS)
    assert isinstance(reading, StockReading)
    breakout = RULES.screens[1]
    assert isinstance(breakout.invalidation[0], CloseBelowLevel)
    found = reading.range(20)
    assert found is not None
    high = Decimal(found[0]).quantize(Decimal("0.0001"))
    assert reading.window.levels[-1] < found[0]  # 2385 against a 2590 high
    assert _invalidated(breakout, reading, high) == "收盤跌回突破價之下"
    assert _invalidated(breakout, reading, Decimal(2000)) is None


def test_a_session_below_the_coverage_is_not_judged() -> None:
    """SC10: without 2408's last bar, 5 of the 6 companies that traded before have one."""
    session = SESSIONS[-1]
    bars = {c: [b for b in v if b.session <= session] for c, v in BARS.items()}
    bars["2408"] = bars["2408"][:-1]
    run = evaluate(
        RULES,
        known_at=end_of_day(session, TAIPEI),
        companies=COMPANIES,
        bars=bars,
        sessions=SESSIONS,
        flows={},
        previous=None,
        industry_basis="as_known",
    )
    assert run.status == "not_judged" and run.screens == [] and run.movers == []
    assert (run.coverage.covered, run.coverage.expected) == (5, 6)
    assert run.reason is not None and "5 of 6" in run.reason and "83.3%" in run.reason


def test_a_session_while_the_history_is_backfilled_is_not_judged() -> None:
    """SC10 since 0.2.0: 2303 and 2408 traded but hold 30 sessions, so 4 of the 6 companies
    with a bar have 60 sessions of history (below 90%); 0.1.0 judged such a session."""
    session = SESSIONS[-1]
    bars = {c: [b for b in v if b.session <= session] for c, v in BARS.items()}
    for code in ("2303", "2408"):
        bars[code] = bars[code][-30:]

    def judged_with(rules: ScreenRuleSet) -> ScreenRunOut:
        return evaluate(
            rules,
            known_at=end_of_day(session, TAIPEI),
            companies=COMPANIES,
            bars=bars,
            sessions=SESSIONS,
            flows={},
            previous=None,
            industry_basis="as_known",
        )

    run = judged_with(RULES)
    assert RULES.rule_version == "0.2.0" and run.status == "not_judged" and run.screens == []
    assert (run.coverage.covered, run.coverage.read, run.coverage.unavailable["history"]) == (
        6,
        4,
        2,
    )
    assert run.reason is not None and "4 of the 6 companies" in run.reason
    assert "66.7%" in run.reason and "below 90%" in run.reason
    first = next(r.rule_set() for r in rules_file().rule_sets if r.rule_version == "0.1.0")
    assert judged_with(first).status == "judged"


def test_the_report_names_the_movers_and_screens_and_never_a_flow_number() -> None:
    """SC12: one plain-text message under Telegram's length, the page named but not linked,
    TWSE's and FinMind's attribution and the footer; flows as conditions met or not."""
    delivery = load_delivery_rules(CONFIG / "delivery_rules.yaml").active()
    assert delivery.screens is not None and delivery.screens.screen_rule_version == "0.2.0"
    run = run_at(date(2026, 10, 21), previous_of(run_at(date(2026, 10, 20))))  # 2881 met then
    (text,) = screen_report(delivery, run, industry_names(CONFIG), RULES.movers.push_top)
    assert len(text) <= MAX_MESSAGE and "http" not in text
    assert text.startswith("[autotrading] 台股研究篩選（非建議）｜2026-10-21 收盤")
    assert "異動前 0（相對自身波動與均量）：\n（今天沒有）" in text
    assert "波段趨勢：新進 1、觀察中 0、結束 0" in text
    assert "＋ 2881 富邦金（金融保險業） 收 " in text
    assert "外資近 5 日至少 3 日買超 無資料" in text  # no flows fetched for 2881 here
    assert "頁面：機會雷達 › 台股篩選" in text and "資料來源：臺灣證券交易所" in text
    assert "FinMind" in text and text.endswith(delivery.footer)
    met = NoteReading(
        kind="flow_net_buy", label="外資近 5 日至少 3 日買超", status="pass", days=4, of=5
    )
    assert _notes([met]) == "外資近 5 日至少 3 日買超 ✓"  # the 4 days stay on the web
    not_judged = run.model_copy(
        update={"status": "not_judged", "reason": "TWSE's files of 2026-10-22 are not stored yet"}
    )
    (short,) = screen_report(delivery, not_judged, {}, RULES.movers.push_top)
    assert "未判斷：TWSE's files of 2026-10-22 are not stored yet" in short
