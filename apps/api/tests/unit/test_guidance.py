# ruff: noqa: RUF001  (issuers' sentences keep their typographic quotes and dashes)
"""Earnings guidance from 8-K exhibits (M1.5, ADR-026 E3, P1-3): revenue, EPS and margins."""

from decimal import Decimal

import pytest

from autotrading.domain.buyback_announcements import MAX_SENTENCE, document_text
from autotrading.domain.guidance import guidance

B = Decimal(10**9)


def one(text: str) -> tuple[str, Decimal, Decimal, str, bool]:
    found = guidance(text)
    assert len(found) == 1, found
    g = found[0]
    assert len(g.sentence) <= MAX_SENTENCE
    return g.metric, g.low, g.high, g.period, g.adjusted


def test_a_forward_sentence_with_its_own_period() -> None:
    # Meta, 8-K EX-99.1 of 2024-02-01.
    assert one(
        "We expect first quarter 2024 total revenue to be in the range of $34.5-37 billion."
    ) == ("revenue", Decimal("34.5") * B, 37 * B, "first quarter 2024", False)
    assert one(
        "We expect fourth quarter 2021 total revenue to be in a range of $31.5 billion to $34 "
        "billion."
    )[1:3] == (Decimal("31.5") * B, 34 * B)


def test_an_outlook_section_gives_its_period_to_bullets_without_a_verb() -> None:
    # NVIDIA, 8-K EX-99.1 of 2026-08-26: the period is only in the line before the bullets.
    text = "\n".join(
        [
            "Outlook",
            "NVIDIA’s outlook for the third quarter of fiscal 2027 is as follows:",
            "•Revenue is expected to be $108.0 billion, plus or minus 2%.",
            "•GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis "
            "points.",
            "•GAAP and non-GAAP operating expenses are expected to be approximately $9.2 billion.",
            "Highlights",
            "•Second-quarter revenue was $89.0 billion, up 18% from the previous quarter.",
        ]
    )
    found = [(g.metric, g.low, g.high, g.period, g.rule) for g in guidance(text)]
    assert found == [
        (
            "revenue",
            Decimal("105.84") * B,
            Decimal("110.16") * B,
            "the third quarter of fiscal 2027",
            "outlook_section",
        ),
        (
            "gross_margin",
            Decimal("73.5"),
            Decimal("74.5"),
            "the third quarter of fiscal 2027",
            "outlook_section",
        ),
    ]  # operating expenses are not in scope (E3); results after "Highlights" never count


def test_gaap_and_non_gaap_values_respectively_are_two_points() -> None:
    text = (
        "NVIDIA’s outlook for the first quarter of fiscal 2022 is as follows:\n"
        "GAAP and non-GAAP gross margins are expected to be 63.8 percent and 66.0 percent, "
        "respectively, plus or minus 50 basis points."
    )
    assert [(g.low, g.high, g.adjusted) for g in guidance(text)] == [
        (Decimal("63.3"), Decimal("64.3"), False),
        (Decimal("65.5"), Decimal("66.5"), True),
    ]


def test_table_rows_and_bullets_of_a_guidance_section() -> None:
    # O'Reilly, 8-K EX-99.1 of 2026-07-29 (a table, one row per line), and Lowe's 2026-08-19.
    raw = (
        b"<p>Updated Full-Year 2026 Guidance</p><table>"
        b"<tr><td><p>Comparable store sales</p></td><td><p>4.0% to 6.0%</p></td></tr>"
        b"<tr><td>Total revenue</td><td>$18.9 billion to $19.2 billion</td></tr>"
        b"<tr><td>Gross profit as a percentage of sales</td><td>51.5% to 52.0%</td></tr>"
        b"<tr><td>Effective income tax rate</td><td>22.5%</td></tr>"
        b"<tr><td>Diluted earnings per share (1)</td><td>$3.20 to $3.30</td></tr></table>"
    )
    found = [(g.metric, g.low, g.high) for g in guidance(document_text(raw, rows=True))]
    assert found == [
        ("revenue_growth", Decimal("4.0"), Decimal("6.0")),
        ("revenue", Decimal("18.9") * B, Decimal("19.2") * B),
        ("gross_margin", Decimal("51.5"), Decimal("52.0")),
        ("eps", Decimal("3.20"), Decimal("3.30")),
    ]
    lowes = "\n".join(
        [
            "Fiscal Year 2026 Outlook",
            "•Total sales of $92.0 billion (previously $92.0 to 94.0 billion)",
            "•Operating income as a percentage of sales (operating margin) of 11.2% "
            "(previously 11.2% to 11.4%)",
            "•Adjusted1 diluted earnings per share of approximately $12.25 (previously $12.25 "
            "to $12.75)",
            "•53rd week expected to increase total sales by approximately $1.0 billion to $1.5 "
            "billion",
        ]
    )
    assert [(g.metric, g.low, g.high, g.adjusted) for g in guidance(lowes)] == [
        ("revenue", 92 * B, 92 * B, False),
        ("operating_margin", Decimal("11.2"), Decimal("11.2"), False),
        ("eps", Decimal("12.25"), Decimal("12.25"), True),
    ]  # "(previously ...)" is the old outlook; "increase ... by" is a change, not a level


@pytest.mark.parametrize(
    "text",
    [
        # Results, and comparisons with an earlier outlook (NVIDIA 2022-08 preliminary results).
        "Preliminary second quarter revenue of $6.70 billion versus outlook of $8.10 billion",
        "Our strong performance in the fourth quarter lifted our full-year comparable store "
        "sales growth to 2.9%, and we expect continued strength in 2025.",
        # Forward words without a future period, or a number (Microsoft, Meta 2021).
        "Several discrete items impacted our financial results in the quarter when compared to "
        "our forward-looking guidance provided on April 29, 2026, resulting in a benefit of "
        "$0.27 on diluted earnings per share.",
        "In the third and fourth quarters of 2021, we expect year-over-year total revenue growth "
        "rates to decelerate significantly on a sequential basis.",
        # Not revenue, EPS or a margin (E3): capital expenditures, expenses, tax rate.
        "Excluding acquisitions, the company expects full-year cash capital expenditures "
        "slightly below the lower end of the $27 billion to $29 billion guidance range.",
        "We expect full-year 2024 total expenses to be in the range of $94-99 billion.",
        # Safe-harbor text.
        "Forward-looking statements, including our expectations for fourth quarter 2026 revenue "
        "of $50 billion, involve risks and uncertainties.",
        # Asset sales are not sales (ExxonMobil 2023).
        "Outlook for full-year 2023\nTotal asset sales and divestments generated $0.9 billion.",
    ],
)
def test_results_other_metrics_and_vague_outlooks_never_count(text: str) -> None:
    assert guidance(text) == []


def test_apple_releases_give_no_numeric_guidance() -> None:
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "sec"
    for name in (
        "0000320193-24-000067_a8-kex991q2202403302024.htm",
        "0000320193-26-000011_a8-kex991q2202603282026.htm",
    ):
        assert guidance(document_text((fixture / name).read_bytes(), rows=True)) == []
