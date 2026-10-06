"""Build progress API (M0.6, ADR-016): milestones, phases, open decisions and the log, parsed
from the project documents on every request (domain/progress.py). Read-only; containers mount
docs/ read-only, so edits to the documents show without a rebuild."""

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotrading.domain.progress import (
    Decision,
    LogEntry,
    Milestone,
    Phase,
    parse_current,
    parse_log,
    parse_milestones,
    parse_open_decisions,
    parse_phases,
)
from autotrading.settings import get_settings

router = APIRouter(tags=["progress"])

# Milestone files are docs/milestones/M<phase>_*.md (M0_foundation.md, M1_*.md, ...).
MILESTONE_FILES = re.compile(r"M(\d+)_[a-z0-9_]+\.md")
FILES = {
    "roadmap": "milestones/ROADMAP.md",
    "status": "STATUS.md",
    "decisions": "decisions/DECISIONS.md",
}


class MilestoneOut(BaseModel):
    id: str
    title: str
    done: int
    total: int
    status: str


class PhaseOut(BaseModel):
    number: int
    scope: str
    blocking: str


class DecisionOut(BaseModel):
    id: str
    decision: str
    needed_by: str
    default: str


class LogOut(BaseModel):
    date: str
    milestone: str
    result: str


class Progress(BaseModel):
    read_at: datetime
    current: dict[str, str]
    milestones: list[MilestoneOut]
    phases: list[PhaseOut]
    open_decisions: list[DecisionOut]
    log: list[LogOut]


def _read(docs: Path, name: str) -> str:
    path = docs / FILES[name]
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"cannot read {FILES[name]}") from exc


def _milestone_files(docs: Path) -> list[Path]:
    """Milestone files in phase order: M0 before M1 before M2."""
    found = [
        (int(match.group(1)), path)
        for path in (docs / "milestones").glob("M*_*.md")
        if (match := MILESTONE_FILES.fullmatch(path.name))
    ]
    if not found:
        raise HTTPException(status_code=503, detail="no milestone files in docs/milestones")
    return [path for _, path in sorted(found)]


@router.get("/progress")
def progress() -> Progress:
    docs = get_settings().resolved_docs_dir()
    status_md = _read(docs, "status")
    current = parse_current(status_md)
    milestones: list[Milestone] = [
        milestone
        for path in _milestone_files(docs)
        for milestone in parse_milestones(path.read_text(encoding="utf-8"), current)
    ]
    phases: list[Phase] = parse_phases(_read(docs, "roadmap"))
    decisions: list[Decision] = parse_open_decisions(_read(docs, "decisions"))
    log: list[LogEntry] = parse_log(status_md)
    return Progress(
        read_at=datetime.now(UTC),
        current=current.fields,
        milestones=[MilestoneOut(**m.__dict__) for m in milestones],
        phases=[PhaseOut(**p.__dict__) for p in phases],
        open_decisions=[DecisionOut(**d.__dict__) for d in decisions],
        log=[LogOut(**e.__dict__) for e in log],
    )
