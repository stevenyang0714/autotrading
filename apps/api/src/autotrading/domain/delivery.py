"""Alert delivery outside the app (M3.0b, ADR-037; OD-2 decided in ADR-035). Pure; no I/O.

A versioned delivery rule set decides which stored alerts are pushed to a channel (Telegram):
market stress changes, companies entering or leaving L3/L4, new S3 and S4 targets and the
paper portfolio's drawdown, under one pinned alert rule version. Backfilled alerts and alerts
older than `max_age_hours` are never pushed; during quiet hours delivery waits. Each message
is plain text, ends with the same disclaimer, and carries no secret, chat id or link.

Research only: a pushed alert is a rule output, unvalidated, and never advice to buy or sell.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

PushedKind = Literal["regime", "level_change", "rotation", "momentum", "portfolio"]
MAX_MESSAGE = 4000  # Telegram allows 4096 characters
MAX_EVIDENCE = 3

KIND_LABELS = {
    "regime": "Market stress",
    "level_change": "Company level",
    "rotation": "S3 ETF rotation",
    "momentum": "S4 momentum",
    "portfolio": "Paper portfolio",
}


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuietHours(_Rule):
    start: time
    end: time
    timezone: str

    def holds(self, at: datetime) -> bool:
        """Whether `at` falls in the quiet hours (which may span midnight)."""
        local = at.astimezone(ZoneInfo(self.timezone)).time()
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end


class DigestRule(_Rule):
    """The weekly digest (M3.0c, ADR-038): every rule candidate at once, on one weekday."""

    weekday: Annotated[int, Field(ge=0, le=6)]  # 0 = Monday
    at: time  # local, in the quiet hours' timezone


class DeliveryRuleSet(_Rule):
    """One released rule version: immutable, like the alert rule sets (ADR-028)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    channel: Literal["telegram"]
    alert_rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    kinds: Annotated[list[PushedKind], Field(min_length=1)]
    min_company_level: Annotated[int, Field(ge=0, le=4)]  # level_change: into or out of it
    max_age_hours: Annotated[int, Field(gt=0)]
    quiet_hours: QuietHours
    max_per_run: Annotated[int, Field(gt=0)]
    max_attempts: Annotated[int, Field(gt=0)]
    footer: Annotated[str, Field(min_length=1)]
    # 0.2.0 (M3.0c, ADR-038): Chinese messages with every holding's name, sector and reasons,
    # and a weekly digest. The defaults keep 0.1.0's content and hash.
    language: Literal["en", "zh"] = "en"
    details: bool = False
    digest: DigestRule | None = None

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class DeliveryRuleSetEntry(DeliveryRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> DeliveryRuleSet:
        return DeliveryRuleSet.model_validate(self.content())


class DeliveryRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[DeliveryRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "DeliveryRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> DeliveryRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


# ---------- choosing and writing ----------


@dataclass(frozen=True)
class StoredAlert:
    """The fields of a stored alert that delivery reads."""

    id: str
    rule_version: str
    kind: str
    level: int
    previous_level: int | None
    title: str
    known_at: datetime
    backfilled: bool
    evidence: list[dict[str, str]]
    direction: str | None = None
    ticker: str | None = None


# ---------- the context of a message (M3.0c, ADR-038): plain values read from stored rows ----


@dataclass(frozen=True)
class Condition:
    """One rule condition as the assessment read it."""

    measure: str
    value: Decimal | None
    threshold: Decimal
    passed: bool


@dataclass(frozen=True)
class Facts:
    """A company or ETF in a message: who it is and what the stored rows say about it at T."""

    symbol: str
    zh: str
    label: str  # 'XOM 埃克森美孚（Exxon Mobil，能源）'
    about: str
    weight: Decimal | None = None
    conditions: tuple[Condition, ...] = ()
    pe: Decimal | None = None
    pe_percentile: Decimal | None = None
    fcf_yield: Decimal | None = None
    fcf_percentile: Decimal | None = None
    dcf_margin: Decimal | None = None  # percent: (fair value - price) / fair value
    buyback_state: str | None = None
    note: str | None = None  # e.g. the company's convergence level in the weekly digest


@dataclass(frozen=True)
class Check:
    """One convergence level check of a company alert."""

    level: int
    passed: bool | None
    detail: str


@dataclass(frozen=True)
class Context:
    entered: tuple[Facts, ...] = ()
    left: tuple[Facts, ...] = ()
    kept: tuple[Facts, ...] = ()
    company: Facts | None = None
    checks: tuple[Check, ...] = ()
    flags: tuple[str, ...] = ()
    stress: str | None = None
    quadrant: str | None = None
    review: str | None = None  # how often the rule reviews its target
    holding_months: Decimal | None = None  # median of the closed backtest holdings


def not_pushed(rules: DeliveryRuleSet, alert: StoredAlert, now: datetime) -> str | None:
    """Why the rules do not push this alert, or None when they do."""
    if alert.rule_version != rules.alert_rule_version:
        return f"alert rules {alert.rule_version}, not {rules.alert_rule_version}"
    if alert.backfilled:
        return "backfilled"
    if alert.kind not in rules.kinds:
        return f"{alert.kind} alerts are not pushed"
    if (
        alert.kind == "level_change"
        and max(alert.level, alert.previous_level or 0) < rules.min_company_level
    ):
        return f"below L{rules.min_company_level}"
    if now - alert.known_at > timedelta(hours=rules.max_age_hours):
        return f"older than {rules.max_age_hours} hours"
    return None


def _label(item: dict[str, str]) -> str:
    return item.get("label") or item.get("table") or "evidence"


def message(rules: DeliveryRuleSet, alert: StoredAlert, context: Context | None = None) -> str:
    """The plain-text message for one alert. Under rules with `language: zh` (0.2.0) the
    Chinese message with names and reasons (`chinese`); otherwise the title, kind, time and
    rule versions, up to three evidence labels, where to look, and the disclaimer."""
    if rules.language == "zh":
        return chinese(rules, alert, context if rules.details else None)
    local = alert.known_at.astimezone(ZoneInfo(rules.quiet_hours.timezone))
    labels = [_label(e) for e in alert.evidence[:MAX_EVIDENCE]]
    more = len(alert.evidence) - len(labels)
    evidence = "; ".join(labels) + (f" (+{more} more)" if more > 0 else "")
    lines = [
        f"[autotrading] {alert.title}",
        f"{KIND_LABELS.get(alert.kind, alert.kind)} · known {local:%Y-%m-%d %H:%M} "
        f"{local.tzname()} · alert rules {alert.rule_version}",
        f"Evidence: {evidence}" if evidence else "",
        "Details in the Alerts Center on the Mac.",
        rules.footer,
    ]
    text = "\n".join(line for line in lines if line)
    if len(text) <= MAX_MESSAGE:
        return text
    head = "\n".join(line for line in lines[:2] if line)
    return f"{head[: MAX_MESSAGE - len(rules.footer) - 2]}\n{rules.footer}"


# ---------- Chinese messages (0.2.0, M3.0c, ADR-038) ----------

STRESS_ZH = {"normal": "正常", "elevated": "升高", "high": "高", "crisis": "危機"}
STRESS_BY_LEVEL = ("normal", "elevated", "high", "crisis")
LEVEL_ZH = {0: "L0 資訊", 1: "L1 觀察", 2: "L2 論點", 3: "L3 交易候選", 4: "L4 可執行"}
QUADRANT_ZH = {
    "goldilocks": "金髮女孩（成長、通膨溫和）",
    "reflation": "再通膨（成長、通膨偏高）",
    "stagflation": "停滯性通膨（放緩、通膨偏高）",
    "disinflationary_slowdown": "通膨降溫的放緩（放緩、通膨溫和）",
}
BUYBACK_ZH = {
    "none": "無",
    "watch": "觀察（已宣布、未明顯執行）",
    "active": "執行中",
    "high_conviction": "高信心（買回加上估值支持）",
    "trade_ready": "可交易（另有市場確認與風險檢查）",
}
HEADS_ZH = {
    "momentum": "S4 動能",
    "rotation": "S3 ETF 輪動",
    "regime": "市場壓力",
    "level_change": "公司等級",
    "portfolio": "模擬組合",
}
DISCLAIMER_SIGNAL = "規則訊號（模擬，非建議）："
FLAGS_ZH = {
    "Credit stressed or distressed": "信用利差緊張",
    "Volatility elevated or stressed": "波動升高",
    "Financial conditions tighter than average": "金融情勢偏緊",
    "Financial stress above normal": "金融壓力高於正常",
    "VIX term structure inverted": "VIX 期限結構倒掛",
    "Stocks well below their high": "股市明顯低於高點",
    "Dollar surge": "美元急升",
    "Oil shock": "油價急變",
    "Stocks and bonds falling together": "股債同跌",
}
CHECKS_ZH = {
    "buybacks executed and valuation support": "有執行買回，也有估值支持",
    "market confirmation passes": "市場確認通過：股價表現優於自身與大盤",
    "market confirmation fails": "市場確認未通過",
    "standard paper position risk check passes": "標準模擬部位通過風險檢查",
    "standard paper position risk check fails": "標準模擬部位未通過風險檢查",
    "no valuation support": "沒有估值支持",
    "no valuation reading": "沒有估值資料",
    "buyback state WATCH: not executing": "庫藏股只在觀察，尚未執行",
    "no buyback state assignment at this date": "這天沒有庫藏股評估",
}


def check_zh(detail: str) -> str:
    """A convergence check's detail in Chinese where it is a known phrase."""
    if detail in CHECKS_ZH:
        return CHECKS_ZH[detail]
    for level in ("L2", "L3"):
        prefix = f"needs {level} first"
        if detail.startswith(prefix):
            rest = detail[len(prefix) :].strip()
            return f"需先達到 {level}" + (f"（{rest.strip('()')}）" if rest else "")
    return detail


def _sign(value: Decimal, digits: int = 1) -> str:
    return f"{value:+.{digits}f}"


def _condition(c: Condition) -> str:
    """'12-1 動能 +21.1%', '比 SPY 的 12-1 動能 -1.2 個百分點（需高於 0）'."""
    need = "" if c.passed else f"（需高於 {c.threshold:g}）"
    if c.value is None:
        return f"{c.measure} 無資料"
    if c.measure == "momentum_12_1":
        return f"12-1 動能 {_sign(c.value)}%{need}"
    if c.measure == "relative_momentum_12_1":
        return f"比 SPY 的 12-1 動能 {_sign(c.value)} 個百分點{need}"
    if c.measure == "close_vs_sma_200":
        side = "高於" if c.value > 0 else "低於"
        return f"收盤{side} 200 日均線 {abs(c.value):.1f}%{need}"
    return f"{c.measure} {_sign(c.value)}{need}"


def dcf_gap(margin: Decimal) -> Decimal | None:
    """The DCF fair value against the price, in percent, from the stored margin of safety
    (fair value - price) / fair value: fair value / price - 1."""
    if margin >= 100:
        return None
    return (Decimal(1) / (1 - margin / 100) - 1) * 100


def _dcf(margin: Decimal) -> str | None:
    gap = dcf_gap(margin)
    if gap is None:
        return None
    side = "高" if gap >= 0 else "低"
    return f"DCF 合理價（目前假設）比股價{side} {abs(gap):.0f}%"


def _valuation(f: Facts) -> str | None:
    parts = []
    if f.pe is not None:
        rank = f"，自身歷史第 {f.pe_percentile:.0f} 百分位" if f.pe_percentile is not None else ""
        parts.append(f"P/E {f.pe:.1f}{rank}")
    if f.fcf_yield is not None:
        rank = f"，第 {f.fcf_percentile:.0f} 百分位" if f.fcf_percentile is not None else ""
        parts.append(f"FCF 殖利率 {f.fcf_yield:.1f}%{rank}")
    if f.dcf_margin is not None and (found := _dcf(f.dcf_margin)):
        parts.append(found)
    return "  估值：" + "；".join(parts) if parts else None


def _company(f: Facts, sign: str | None = None) -> list[str]:
    weight = f"，權重 {f.weight:.2f}%" if f.weight is not None else ""
    lines = [f"{sign + ' ' if sign else ''}{f.label}{weight}"]
    if f.about:
        lines.append(f"  {f.about}")
    if f.conditions:
        why = "原因" if sign == "－離開" else "動能"
        shown = [c for c in f.conditions if not c.passed] if sign == "－離開" else f.conditions
        lines.append(f"  {why}：" + "；".join(_condition(c) for c in shown or f.conditions))
    found = _valuation(f)
    if found:
        lines.append(found)
    if f.buyback_state:
        lines.append(f"  庫藏股：{BUYBACK_ZH.get(f.buyback_state, f.buyback_state)}")
    return lines


def _headline(alert: StoredAlert, context: Context | None) -> str:
    up = alert.direction != "down"
    if alert.kind == "regime":
        now = STRESS_BY_LEVEL[alert.level] if 0 <= alert.level < 4 else str(alert.level)
        was = STRESS_BY_LEVEL[alert.previous_level] if alert.previous_level is not None else ""
        return f"{'升到' if up else '降到'}{STRESS_ZH.get(now, now)}（原{STRESS_ZH.get(was, was)}）"
    if alert.kind == "level_change":
        who = (
            f"{context.company.symbol} {context.company.zh}"
            if context and context.company
            else (alert.ticker or "")
        )
        was = LEVEL_ZH.get(alert.previous_level or 0, "")
        return f"{who} {'升到' if up else '降到'} {LEVEL_ZH.get(alert.level, '')}（原 {was}）"
    if alert.kind == "rotation":
        return "轉防守（壓力升高）" if "defensive switch" in alert.title else "每月目標調整"
    if alert.kind == "momentum":
        return "每月目標調整"
    if alert.kind == "portfolio":
        return "回撤超過上限" if alert.level else "回撤回到上限內"
    return alert.title


def _body(alert: StoredAlert, context: Context) -> list[str]:
    lines: list[str] = []
    if alert.kind in ("momentum", "rotation"):
        lines.append(DISCLAIMER_SIGNAL)
        for f in context.entered:
            lines += _company(f, "＋進入")
        for f in context.left:
            lines += _company(f, "－離開")
        if context.kept:
            weights = {f.weight for f in context.kept}
            each = (
                f"（每檔 {next(iter(weights)):.2f}%）"
                if len(weights) == 1 and None not in weights
                else ""
            )
            lines.append(
                f"繼續持有{each}：" + "、".join(f"{f.symbol} {f.zh}" for f in context.kept)
            )
        if not (context.entered or context.left):
            lines.append("持有的標的不變，只調整權重。")
    elif alert.kind == "level_change" and context.company:
        lines += _company(context.company)
        if context.checks:
            lines.append("收斂檢查：")
            for c in context.checks:
                status = "通過" if c.passed else ("未通過" if c.passed is False else "無資料")
                lines.append(
                    f"  {LEVEL_ZH.get(c.level, c.level)}：{status}（{check_zh(c.detail)}）"
                )
    elif alert.kind == "regime" and context.flags:
        lines.append("亮起的壓力旗標：" + "；".join(FLAGS_ZH.get(f, f) for f in context.flags))
    if not lines:  # a regime change with no flag on, the drawdown alert: its evidence
        labels = [FLAGS_ZH.get(_label(e), _label(e)) for e in alert.evidence[:MAX_EVIDENCE]]
        lines.append("依據：" + "；".join(labels) if labels else alert.title)
    return lines


def _tail(context: Context | None) -> list[str]:
    if context is None:
        return []
    lines = []
    if context.review:
        months = (
            f"；過去回測持有中位數約 {context.holding_months:.0f} 個月（只是持有時間，不是報酬）"
            if context.holding_months is not None
            else ""
        )
        lines.append(f"規則節奏：{context.review}{months}")
    if context.stress or context.quadrant:
        stress = STRESS_ZH.get(context.stress or "", "無資料")
        quadrant = QUADRANT_ZH.get(context.quadrant or "", "無資料")
        lines.append(f"市場：壓力{stress}；{quadrant}")
    return lines


def chinese(rules: DeliveryRuleSet, alert: StoredAlert, context: Context | None) -> str:
    """The Chinese message: headline, time, the rule signal with each holding's name, sector
    and reasons, the rule's rhythm, the market, where to look and the disclaimer. Without a
    context (nothing resolved), the evidence labels instead. Never a link, a chat id or a
    recommendation; within Telegram's length, dropping details first."""
    local = alert.known_at.astimezone(ZoneInfo(rules.quiet_hours.timezone))
    head = [
        f"[autotrading] {HEADS_ZH.get(alert.kind, alert.kind)}｜{_headline(alert, context)}",
        f"時間：{local:%Y-%m-%d %H:%M}（新加坡）· 警示規則 {alert.rule_version}",
    ]
    if context is not None:
        body = _body(alert, context)
    else:
        labels = [_label(e) for e in alert.evidence[:MAX_EVIDENCE]]
        body = [alert.title, "依據：" + "；".join(labels)] if labels else [alert.title]
    end = ["詳見 Mac 上的 Alerts Center。", rules.footer]
    full = "\n".join([*head, *body, *_tail(context), *end])
    if len(full) <= MAX_MESSAGE:
        return full
    short = "\n".join([*head, alert.title, *end])
    if len(short) <= MAX_MESSAGE:
        return short
    keep = MAX_MESSAGE - len(rules.footer) - 1
    return "\n".join([*head, alert.title])[:keep] + "\n" + rules.footer


# ---------- the weekly digest (0.2.0, M3.0c, ADR-038) ----------

DIGEST_TITLES = {
    "S4": "S4 動能（目前目標；每月第一次評估時調整）：",
    "S1": "S1 庫藏股＋估值（達到 L3/L4 的公司；每天評估）：",
    "S3": "S3 ETF 輪動（目前目標；每月調整、壓力高時轉防守）：",
}


def _brief(f: Facts) -> str:
    """One digest line: who, weight and the main reasons."""
    parts: list[str] = []
    if f.note:
        parts.append(f.note)
    for c in f.conditions:
        if c.value is None:
            continue
        if c.measure == "momentum_12_1":
            parts.append(f"12-1 動能 {_sign(c.value, 0)}%")
        elif c.measure == "relative_momentum_12_1":
            parts.append(f"比 SPY {_sign(c.value, 0)} 個百分點")
        elif c.measure == "close_vs_sma_200":
            parts.append(f"{'高於' if c.value > 0 else '低於'} 200 日均線 {abs(c.value):.0f}%")
    if f.pe is not None:
        rank = f"（第 {f.pe_percentile:.0f} 百分位）" if f.pe_percentile is not None else ""
        parts.append(f"P/E {f.pe:.0f}{rank}")
    if f.dcf_margin is not None and (found := _dcf(f.dcf_margin)):
        parts.append(found)
    if f.buyback_state and f.buyback_state != "none":
        parts.append(f"庫藏股{BUYBACK_ZH.get(f.buyback_state, f.buyback_state).split('（')[0]}")
    weight = f" {f.weight:.0f}%" if f.weight is not None else ""
    return f"• {f.label}{weight}" + (f"：{'；'.join(parts)}" if parts else "")


def digest(
    rules: DeliveryRuleSet,
    week: date,
    stress: str | None,
    quadrant: str | None,
    sections: list[tuple[str, list[Facts]]],
) -> list[str]:
    """The week's digest of every rule candidate, in as many messages as Telegram's length
    needs, each with the header and the disclaimer."""
    head = f"[autotrading] 每週規則候選（模擬，非建議）｜{week:%Y-%m-%d} 這週"
    stress_zh = STRESS_ZH.get(stress or "", "無資料")
    market = f"市場：壓力{stress_zh}；{QUADRANT_ZH.get(quadrant or '', '無資料')}"
    end = [
        "每一行都是規則讀數，不是買賣建議；規則的報酬沒有驗證過（OD-7）。",
        rules.footer,
    ]
    blocks: list[list[str]] = []
    for title, rows in sections:
        block = [title, *(_brief(f) for f in rows)] if rows else [title, "（目前沒有）"]
        blocks.append(block)
    messages: list[list[str]] = [[market]]
    for block in blocks:
        current = messages[-1]
        size = len("\n".join([head, *current, *block, *end]))
        if size > MAX_MESSAGE and len(current) > 1:
            messages.append([])
        messages[-1].extend(block)
    total = len(messages)
    out = []
    for i, lines in enumerate(messages, start=1):
        title = head if total == 1 else f"{head}（{i}/{total}）"
        text = "\n".join([title, *lines, *end])
        if len(text) > MAX_MESSAGE:
            keep = MAX_MESSAGE - len(rules.footer) - 1
            text = "\n".join([title, *lines])[:keep] + "\n" + rules.footer
        out.append(text)
    return out
