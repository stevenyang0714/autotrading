"""The real glossary file is valid, and every backend metric matches its glossary version."""

import pytest
from pydantic import ValidationError

from autotrading.config_sync import load_glossary
from autotrading.domain.glossary import REQUIRED_FIELDS, GlossaryTerm
from autotrading.domain.metrics import METRICS
from autotrading.settings import Settings

GLOSSARY = load_glossary(Settings(_env_file=None).resolved_glossary_path())  # type: ignore[call-arg]
COMPLETE = {term.term_id: term for term in GLOSSARY.complete_terms()}


def test_required_fields_are_the_seventeen_of_02_section_22() -> None:
    assert len(REQUIRED_FIELDS) == 17


def test_ui_terms_are_complete() -> None:
    expected = {
        "source_tier",
        "license_status",
        "access_status",
        "data_freshness",
        "freshness_sla",
        "rate_limit",
        "update_cadence",
        "ingestion_status",
        "dead_letter",
        "as_of",
        "planned_phase",
        "page_data_health",
    }
    assert expected <= set(COMPLETE)
    assert len([t for t in COMPLETE if t.startswith("dashboard_")]) == 15


def test_every_backend_metric_matches_its_glossary_version() -> None:
    # M0.4 validation rule 3.
    for metric in METRICS:
        assert metric.term_id in COMPLETE, f"{metric.term_id} has no complete glossary entry"
        assert COMPLETE[metric.term_id].methodology_version == metric.methodology_version


def test_complete_term_missing_a_field_is_rejected() -> None:
    fields = COMPLETE["dead_letter"].model_dump()
    fields["example"] = None
    with pytest.raises(ValidationError, match="missing"):
        GlossaryTerm(**fields)


def test_seed_terms_may_be_incomplete() -> None:
    seed = next(t for t in GLOSSARY.terms if t.status == "seed")
    assert seed.full_definition is None or seed.full_definition


def test_content_hash_tracks_content_not_status() -> None:
    term = COMPLETE["rate_limit"]
    assert term.content_sha256() == term.model_copy(update={"status": "seed"}).content_sha256()
    changed = term.model_copy(update={"caveats": term.caveats + " Updated."})
    assert changed.content_sha256() != term.content_sha256()


def test_every_complete_term_has_a_chinese_hint() -> None:
    import yaml

    path = Settings(_env_file=None).resolved_glossary_path().with_name("glossary_zh.yaml")  # type: ignore[call-arg]
    zh = yaml.safe_load(path.read_text(encoding="utf-8"))["terms"]
    assert set(zh) == set(COMPLETE), "glossary_zh.yaml must cover exactly the complete terms"
    for term_id, entry in zh.items():
        assert set(entry) == {"name", "hint"} and entry["name"] and entry["hint"], term_id
