"""Rename the doubled CHECK constraint names from 0001-0004 to `ck_<table>_<suffix>`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06

0001-0004 passed full names such as `ck_sources_license_status` to CHECK constraints, and the
metadata naming convention (`ck_%(table_name)s_%(constraint_name)s`) prefixed them again, so the
database holds `ck_sources_ck_sources_license_status`. Only names change: no definition, row or
behaviour does. The longest doubled name has 58 characters, so none was truncated.

The downgrade restores the doubled names: the 0002 downgrade drops its CHECK constraints by the
name it created them with, which the convention doubles again.
"""

from collections.abc import Iterator, Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every CHECK constraint 0001-0004 created, by table (0005 and later pass bare suffixes).
CHECKS: dict[str, tuple[str, ...]] = {
    "signal_families": ("id_range",),
    "strategies": ("id_format", "default_mode"),
    "source_tiers": ("tier_range",),
    "sources": (
        "id_format",
        "license_status",
        "access_status",
        "update_cadence",
        "freshness_sla_positive",
        "rate_limit_positive",
        "rate_limit_burst_positive",
    ),
    "entities": ("entity_type", "country_format"),
    "instruments": ("instrument_type", "mic_format", "currency_format"),
    "identifiers": ("one_subject", "id_type", "namespace_format", "valid_range"),
    "financial_facts": (
        "precision",
        "license_status",
        "confidence_range",
        "effective_range",
        "source_url_scheme",
        "payload_sha256",
        "system_time_order",
        "version_positive",
        "metric_id_format",
        "value_finite",
        "currency_format",
        "period_order",
        "revision_reason",
        "revision_link",
    ),
    "audit_log": ("action",),
    "ingestion_runs": (
        "job_format",
        "idempotency_key_format",
        "status",
        "attempt_positive",
        "window_order",
    ),
    "raw_payloads": ("sha256_format", "size_non_negative", "source_url_scheme"),
    "dead_letters": ("attempts_positive", "resolution_complete"),
    "glossary_terms": ("term_id_format", "content_sha256_format", "source_url_scheme"),
    "filings": (
        "precision",
        "license_status",
        "confidence_range",
        "effective_range",
        "source_url_scheme",
        "payload_sha256",
        "accession_format",
        "cik_format",
        "form_not_empty",
    ),
}


def names() -> Iterator[tuple[str, str, str]]:
    """(table, doubled name, intended name) for every constraint in CHECKS."""
    for table, suffixes in CHECKS.items():
        for suffix in suffixes:
            yield table, f"ck_{table}_ck_{table}_{suffix}", f"ck_{table}_{suffix}"


def upgrade() -> None:
    for table, doubled, intended in names():
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {doubled} TO {intended}")


def downgrade() -> None:
    for table, doubled, intended in names():
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {intended} TO {doubled}")
