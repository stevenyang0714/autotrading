"""Glossary Registry contract (02 §22, M0.4).

Source of truth: docs/glossary/glossary_seed.yaml. A `complete` term has all 17 fields of
02 §22 filled and may be used in the UI; a `seed` term is a draft and may not.
"""

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 02 §22, in order.
REQUIRED_FIELDS: tuple[str, ...] = (
    "term_id",
    "display_name",
    "category",
    "short_definition",
    "full_definition",
    "formula",
    "unit",
    "example",
    "interpretation",
    "why_it_matters",
    "source",
    "source_url",
    "as_of",
    "update_cadence",
    "caveats",
    "related_terms",
    "methodology_version",
)

TermStatus = Literal["seed", "complete"]


class GlossaryTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    term_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    short_definition: str = Field(min_length=1)
    full_definition: str | None = None
    formula: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    example: str | None = None
    direction: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    source: str | None = None
    source_url: str | None = Field(default=None, pattern=r"^https?://")
    as_of: str | None = None
    update_cadence: str = Field(min_length=1)
    caveats: str = Field(min_length=1)
    related_terms: list[str]
    methodology_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    status: TermStatus

    @model_validator(mode="after")
    def complete_means_all_fields(self) -> Self:
        if self.status == "complete":
            missing = [name for name in REQUIRED_FIELDS if not getattr(self, name)]
            if missing:
                raise ValueError(f"{self.term_id} is complete but missing {missing}")
        return self

    def content_sha256(self) -> str:
        """Hash of everything except status: same version + different hash = forgotten bump."""
        content = self.model_dump(exclude={"status"})
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class GlossaryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    terms: list[GlossaryTerm]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        ids = [term.term_id for term in self.terms]
        duplicates = sorted({term_id for term_id in ids if ids.count(term_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate term ids: {duplicates}")
        known = set(ids)
        dangling = sorted(
            {f"{t.term_id}->{r}" for t in self.terms for r in t.related_terms if r not in known}
        )
        if dangling:
            raise ValueError(f"related_terms point to unknown terms: {dangling}")
        return self

    def complete_terms(self) -> list[GlossaryTerm]:
        return [term for term in self.terms if term.status == "complete"]
