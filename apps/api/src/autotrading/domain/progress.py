"""Build progress from the project documents (M0.6 progress page, ADR-016).

Pure parsing of the Markdown the team already maintains: milestone acceptance checkboxes
(docs/milestones/M0_foundation.md), the phase table (ROADMAP.md), the Current section and log
of docs/STATUS.md and the open decisions table (docs/decisions/DECISIONS.md). Nothing is
stored; the page re-reads the files on each request, so edits show at once.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

MilestoneStatus = Literal["done", "in_progress", "not_started"]

_HEADING = re.compile(r"^## (M\d+\.\d+[a-z]?) (.+)$")
_BOX = re.compile(r"^\s*- \[( |x|X)\] ")
_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")


@dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    done: int
    total: int
    status: MilestoneStatus


@dataclass(frozen=True)
class Phase:
    number: int
    scope: str
    blocking: str


@dataclass(frozen=True)
class Decision:
    id: str
    decision: str
    needed_by: str
    default: str


@dataclass(frozen=True)
class LogEntry:
    date: str
    milestone: str
    result: str


@dataclass(frozen=True)
class Current:
    fields: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        return self.fields.get(key)


def _cells(line: str) -> list[str] | None:
    match = _TABLE_ROW.match(line.strip())
    if match is None:
        return None
    cells = [cell.strip() for cell in match.group(1).split("|")]
    if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
        return None  # header separator
    return cells


def _first_sentence(text: str, limit: int = 220) -> str:
    sentence = re.split(r"(?<=\.)\s", text, maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def parse_current(status_md: str) -> Current:
    """`- Key: value` bullets under `## Current` in docs/STATUS.md."""
    fields: dict[str, str] = {}
    in_section = False
    for line in status_md.splitlines():
        if line.startswith("## "):
            in_section = line.strip() == "## Current"
            continue
        if in_section and line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            fields[key.strip()] = value.strip()
    return Current(fields)


def parse_milestones(milestones_md: str, current: Current) -> list[Milestone]:
    """One entry per `## M0.x` heading; counts the acceptance checkboxes under it."""
    sections: list[tuple[str, str, list[str]]] = []
    for line in milestones_md.splitlines():
        heading = _HEADING.match(line.strip())
        if heading:
            sections.append((heading.group(1), heading.group(2).strip(), []))
        elif sections:
            sections[-1][2].append(line)
    active = current.get("Sub-milestone") or ""
    milestones = []
    for milestone_id, title, lines in sections:
        boxes = [m.group(1) for line in lines if (m := _BOX.match(line))]
        done = sum(1 for box in boxes if box.lower() == "x")
        is_active = re.match(rf"{re.escape(milestone_id)}\b", active) is not None
        status: MilestoneStatus
        if boxes and done == len(boxes) and not (is_active and "pending" in active.lower()):
            status = "done"
        elif done or is_active:
            status = "in_progress"
        else:
            status = "not_started"
        milestones.append(Milestone(milestone_id, title, done, len(boxes), status))
    return milestones


def parse_phases(roadmap_md: str) -> list[Phase]:
    """Rows of the first table in ROADMAP.md: phase number, scope, blocking decisions."""
    phases = []
    for line in roadmap_md.splitlines():
        cells = _cells(line)
        if cells and len(cells) >= 5 and cells[0].isdigit():
            phases.append(Phase(int(cells[0]), _first_sentence(cells[1]), cells[4]))
    return phases


def parse_open_decisions(decisions_md: str) -> list[Decision]:
    """Rows of the open decisions table in DECISIONS.md (ids OD-n)."""
    out = []
    for line in decisions_md.splitlines():
        cells = _cells(line)
        if cells and len(cells) >= 4 and re.fullmatch(r"OD-\d+", cells[0]):
            out.append(Decision(cells[0], _first_sentence(cells[1]), cells[2], cells[3]))
    return out


def parse_log(status_md: str, limit: int = 8) -> list[LogEntry]:
    """Newest log rows of docs/STATUS.md (the table is kept newest first)."""
    entries = []
    for line in status_md.splitlines():
        cells = _cells(line)
        if cells and len(cells) >= 3 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            entries.append(LogEntry(cells[0], cells[1], _first_sentence(cells[2])))
    return entries[:limit]
