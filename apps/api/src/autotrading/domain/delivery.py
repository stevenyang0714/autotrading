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


def message(rules: DeliveryRuleSet, alert: StoredAlert) -> str:
    """The plain-text message for one alert: title, kind, time and rule versions, up to three
    evidence labels, where to look, and the disclaimer."""
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
