"""Alert delivery rules (M3.0b, ADR-037): which alerts are pushed, quiet hours, the message."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from autotrading.domain.delivery import (
    DIGEST_TITLES,
    Check,
    Condition,
    Context,
    DeliveryRulesFile,
    Facts,
    StoredAlert,
    dcf_gap,
    digest,
    message,
    not_pushed,
)
from autotrading.repositories.delivery import digest_due, digest_week
from autotrading.settings import get_settings

FILE = DeliveryRulesFile.model_validate(
    yaml.safe_load(Path(get_settings().resolved_config_dir() / "delivery_rules.yaml").read_text())
)
RULES = FILE.active()
# A released version never changes (ADR-037): a new rule_version is the only way to edit one.
PINNED = {
    "0.1.0": "7b6a95934e7c41dad84ef2bd9988eff7bbf90b9cd3e8af3d15d9d0b17738149a",
    # Chinese messages with reasons and a weekly digest (ADR-038)
    "0.2.0": "9d534f27fd81bfaa5b35b7616fd068f3ceb30aeee295ba14c12b3a545229bd9f",
    # the Taiwan screens' report (ADR-042)
    "0.3.0": "9a9ea04df53dea6e5ea21dfb64cda860ad8fcc6d6f42387f5a2b839c35c04d3f",
    # the report of screen rules 0.2.0 (ADR-042 SC10)
    "0.4.0": "eadbb85f625945b4a820c537bade177036eecda6803148e680e3442b78863912",
}
FIRST = next(r.rule_set() for r in FILE.rule_sets if r.rule_version == "0.1.0")
NOW = datetime(2026, 10, 20, 3, 20, tzinfo=UTC)  # 11:20 Singapore time


def alert(**changes: object) -> StoredAlert:
    base: dict[str, object] = {
        "id": "a-1",
        "rule_version": "0.6.0",
        "kind": "regime",
        "level": 2,
        "previous_level": 1,
        "title": "Market stress rose to HIGH (was ELEVATED)",
        "known_at": NOW - timedelta(minutes=5),
        "backfilled": False,
        "evidence": [{"table": "regime_assessments", "id": "r-1", "label": "VIX above 30"}],
    }
    base.update(changes)
    return StoredAlert(**base)  # type: ignore[arg-type]


def test_every_released_rule_set_is_pinned() -> None:
    assert {r.rule_version: r.rule_set().content_sha256() for r in FILE.rule_sets} == PINNED
    assert (RULES.channel, RULES.alert_rule_version, RULES.max_per_run) == ("telegram", "0.6.0", 10)
    assert set(RULES.kinds) == {"regime", "level_change", "rotation", "momentum", "portfolio"}


def test_which_alerts_are_pushed() -> None:
    assert not_pushed(RULES, alert(), NOW) is None
    for kind in ("rotation", "momentum", "portfolio"):
        assert not_pushed(RULES, alert(kind=kind), NOW) is None
    assert not_pushed(RULES, alert(kind="event", level=0), NOW) == "event alerts are not pushed"
    assert not_pushed(RULES, alert(backfilled=True), NOW) == "backfilled"
    assert not_pushed(RULES, alert(rule_version="0.5.0"), NOW) == "alert rules 0.5.0, not 0.6.0"
    old = alert(known_at=NOW - timedelta(hours=49))
    assert not_pushed(RULES, old, NOW) == "older than 48 hours"


def test_company_levels_are_pushed_into_and_out_of_l3() -> None:
    up = alert(kind="level_change", level=3, previous_level=2)
    down = alert(kind="level_change", level=2, previous_level=4)
    low = alert(kind="level_change", level=2, previous_level=1)
    assert not_pushed(RULES, up, NOW) is None
    assert not_pushed(RULES, down, NOW) is None
    assert not_pushed(RULES, low, NOW) == "below L3"


@pytest.mark.parametrize(
    ("hour", "minute", "quiet"),
    [(15, 0, True), (22, 59, True), (23, 0, False), (14, 59, False), (3, 20, False)],
)
def test_quiet_hours_span_midnight_singapore_time(hour: int, minute: int, quiet: bool) -> None:
    # 15:00 UTC is 23:00 SGT; 22:59 UTC is 06:59 SGT; 23:00 UTC is 07:00 SGT
    at = datetime(2026, 10, 20, hour, minute, tzinfo=UTC)
    assert RULES.quiet_hours.holds(at) is quiet


def test_the_message_is_plain_text_with_the_disclaimer_and_no_link() -> None:
    # 0.1.0's English message; 0.2.0's Chinese one has its own tests
    evidence = [{"table": "t", "id": str(i), "label": f"flag {i}"} for i in range(5)]
    text = message(FIRST, alert(evidence=evidence))
    lines = text.split("\n")
    assert lines[0] == "[autotrading] Market stress rose to HIGH (was ELEVATED)"
    assert lines[1] == "Market stress · known 2026-10-20 11:15 +08 · alert rules 0.6.0"
    assert lines[2] == "Evidence: flag 0; flag 1; flag 2 (+2 more)"
    assert lines[-1] == "Rule output, unvalidated, not advice. Paper only."
    assert "http" not in text and "<" not in text
    long = message(FIRST, alert(title="x" * 5000))
    assert len(long) <= 4000 and long.endswith("Paper only.")


def test_the_rules_file_needs_one_active_version() -> None:
    raw = yaml.safe_load(
        Path(get_settings().resolved_config_dir() / "delivery_rules.yaml").read_text()
    )
    raw["rule_sets"][0]["status"] = "retired"
    with pytest.raises(ValueError, match="exactly one rule set must be active"):
        DeliveryRulesFile.model_validate(raw)


# ---------- Chinese messages with reasons (0.2.0, M3.0c, ADR-038) ----------


def company(symbol: str, zh: str, name: str, sector: str, **changes: object) -> Facts:
    base: dict[str, object] = {
        "symbol": symbol,
        "zh": zh,
        "label": f"{symbol} {zh}（{name}，{sector}）",
        "about": "",
    }
    base.update(changes)
    return Facts(**base)  # type: ignore[arg-type]


MOMENTUM = (
    Condition("momentum_12_1", Decimal("21.09"), Decimal(0), True),
    Condition("relative_momentum_12_1", Decimal("4.60"), Decimal(0), True),
)


def test_an_s4_target_change_lists_who_enters_leaves_and_why() -> None:
    entered = company(
        "AAPL",
        "蘋果",
        "Apple",
        "資訊科技",
        about="iPhone、Mac 與服務",
        weight=Decimal("25.00"),
        conditions=MOMENTUM,
        pe=Decimal("31.2"),
        pe_percentile=Decimal("85"),
        fcf_yield=Decimal("3.1"),
        fcf_percentile=Decimal("40"),
        dcf_margin=Decimal("-12"),
        buyback_state="active",
    )
    left = company(
        "JPM",
        "摩根大通",
        "JPMorgan Chase",
        "金融",
        conditions=(
            Condition("momentum_12_1", Decimal("8.1"), Decimal(0), True),
            Condition("relative_momentum_12_1", Decimal("-0.6"), Decimal(0), False),
        ),
    )
    kept = company("NVDA", "輝達", "NVIDIA", "資訊科技", weight=Decimal("25.00"))
    context = Context(
        entered=(entered,),
        left=(left,),
        kept=(kept,),
        stress="normal",
        quadrant="disinflationary_slowdown",
        review="每個紐約月份第一次評估時調整（S4）",
        holding_months=Decimal("4.2"),
    )
    text = message(RULES, alert(kind="momentum", direction="up"), context)
    lines = text.split("\n")
    assert lines[0] == "[autotrading] S4 動能｜每月目標調整"
    assert lines[1] == "時間：2026-10-20 11:15（新加坡）· 警示規則 0.6.0"
    assert lines[2] == "規則訊號（模擬，非建議）："
    assert "＋進入 AAPL 蘋果（Apple，資訊科技），權重 25.00%" in lines
    assert "  動能：12-1 動能 +21.1%；比 SPY 的 12-1 動能 +4.6 個百分點" in lines
    assert (
        "  估值：P/E 31.2，自身歷史第 85 百分位；FCF 殖利率 3.1%，第 40 百分位；"
        "DCF 合理價（目前假設）比股價低 11%"
    ) in lines
    assert "  庫藏股：執行中" in lines
    assert "－離開 JPM 摩根大通（JPMorgan Chase，金融）" in lines
    assert "  原因：比 SPY 的 12-1 動能 -0.6 個百分點（需高於 0）" in lines
    assert "繼續持有（每檔 25.00%）：NVDA 輝達" in lines
    assert any("過去回測持有中位數約 4 個月（只是持有時間，不是報酬）" in line for line in lines)
    assert "市場：壓力正常；通膨降溫的放緩（放緩、通膨溫和）" in lines
    assert lines[-1] == "規則輸出、未經驗證、不是投資建議；僅供模擬（Paper only）。"
    assert "買入建議" not in text and "賣出建議" not in text and "http" not in text


def test_a_company_level_message_reads_its_checks_in_chinese() -> None:
    context = Context(
        company=company("GOOGL", "谷歌", "Alphabet", "通訊服務", buyback_state="high_conviction"),
        checks=(
            Check(2, True, "buybacks executed and valuation support"),
            Check(3, True, "market confirmation passes"),
            Check(4, False, "standard paper position risk check fails"),
        ),
    )
    up = alert(kind="level_change", level=3, previous_level=2, direction="up", ticker="GOOGL")
    lines = message(RULES, up, context).split("\n")
    assert lines[0] == "[autotrading] 公司等級｜GOOGL 谷歌 升到 L3 交易候選（原 L2 論點）"
    assert "  L2 論點：通過（有執行買回，也有估值支持）" in lines
    assert "  L4 可執行：未通過（標準模擬部位未通過風險檢查）" in lines
    assert "  庫藏股：高信心（買回加上估值支持）" in lines


def test_a_stress_change_names_its_flags_in_chinese() -> None:
    context = Context(flags=("VIX term structure inverted", "Oil shock"), stress="high")
    lines = message(RULES, alert(direction="up"), context).split("\n")
    assert lines[0] == "[autotrading] 市場壓力｜升到高（原升高）"
    assert "亮起的壓力旗標：VIX 期限結構倒掛；油價急變" in lines


def test_without_a_context_the_chinese_message_falls_back_to_the_evidence() -> None:
    lines = message(RULES, alert(kind="portfolio", level=1, direction="up"), None).split("\n")
    assert lines[0] == "[autotrading] 模擬組合｜回撤超過上限"
    assert "依據：VIX above 30" in lines
    assert lines[-1].endswith("僅供模擬（Paper only）。")


def test_a_long_chinese_message_keeps_the_footer() -> None:
    many = tuple(
        company(f"S{i}", "名" * 50, "N" * 50, "業", about="說" * 200, conditions=MOMENTUM)
        for i in range(30)
    )
    text = message(RULES, alert(kind="momentum"), Context(entered=many))
    assert len(text) <= 4000 and text.endswith("僅供模擬（Paper only）。")


def test_the_dcf_margin_reads_as_fair_value_against_price() -> None:
    assert dcf_gap(Decimal("-1120")) is not None
    assert round(dcf_gap(Decimal("-1120")) or 0) == -92  # fair value 8% of the price
    assert round(dcf_gap(Decimal("18")) or 0) == 22
    assert dcf_gap(Decimal("100")) is None


def test_the_weekly_digest_lists_every_candidate_with_its_reasons() -> None:
    xom = company(
        "XOM",
        "埃克森美孚",
        "Exxon Mobil",
        "能源",
        weight=Decimal("25"),
        conditions=MOMENTUM,
        pe=Decimal("23.4"),
        pe_percentile=Decimal("73"),
        buyback_state="active",
    )
    azo = company(
        "AZO", "AutoZone", "AutoZone", "非必需消費", note="L4 可執行", dcf_margin=Decimal("18")
    )
    texts = digest(
        RULES,
        date(2026, 10, 19),
        "normal",
        "goldilocks",
        [(DIGEST_TITLES["S4"], [xom]), (DIGEST_TITLES["S1"], [azo]), (DIGEST_TITLES["S3"], [])],
    )
    assert len(texts) == 1
    lines = texts[0].split("\n")
    assert lines[0] == "[autotrading] 每週規則候選（模擬，非建議）｜2026-10-19 這週"
    assert lines[1] == "市場：壓力正常；金髮女孩（成長、通膨溫和）"
    assert (
        "• XOM 埃克森美孚（Exxon Mobil，能源） 25%：12-1 動能 +21%；比 SPY +5 個百分點；"
        "P/E 23（第 73 百分位）；庫藏股執行中"
    ) in lines
    assert (
        "• AZO AutoZone（AutoZone，非必需消費）：L4 可執行；DCF 合理價（目前假設）比股價高 22%"
        in lines
    )
    assert lines[lines.index(DIGEST_TITLES["S3"]) + 1] == "（目前沒有）"
    assert lines[-1] == RULES.footer


def test_a_long_digest_is_split_with_the_disclaimer_on_each_message() -> None:
    many = [
        company(f"S{i}", "名" * 40, "N" * 40, "業", weight=Decimal("1"), conditions=MOMENTUM)
        for i in range(40)
    ]
    sections = [(DIGEST_TITLES[k], many) for k in ("S4", "S1", "S3")]
    texts = digest(RULES, date(2026, 10, 19), None, None, sections)
    assert len(texts) > 1
    assert all(len(t) <= 4000 and t.endswith(RULES.footer) for t in texts)
    assert texts[1].startswith(
        f"[autotrading] 每週規則候選（模擬，非建議）｜2026-10-19 這週（2/{len(texts)}）"
    )


@pytest.mark.parametrize(
    ("at", "due"),
    [
        (datetime(2026, 10, 19, 0, 0, tzinfo=UTC), True),  # Monday 08:00 Singapore time
        (datetime(2026, 10, 19, 0, 59, tzinfo=UTC), True),
        (datetime(2026, 10, 19, 1, 0, tzinfo=UTC), False),  # 09:00
        (datetime(2026, 10, 20, 0, 0, tzinfo=UTC), False),  # Tuesday
    ],
)
def test_the_digest_is_due_on_its_weekday_and_hour(at: datetime, due: bool) -> None:
    assert digest_due(RULES, at) is due
    assert digest_week(RULES, at) == date(2026, 10, 19)
    assert not digest_due(FIRST, at)  # 0.1.0 has no digest
