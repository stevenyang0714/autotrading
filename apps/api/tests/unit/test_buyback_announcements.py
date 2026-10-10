# ruff: noqa: RUF001  (issuers' sentences keep their typographic quotes and dashes)
"""Buyback announcements from 8-K and press-release sentences (M1.4a, ADR-025 B1)."""

from datetime import date
from decimal import Decimal

import pytest

from autotrading.domain.buyback_announcements import (
    MAX_SENTENCE,
    document_text,
    sentences,
    statement,
    statements,
)

B = Decimal(10**9)


@pytest.mark.parametrize(
    ("sentence", "kind", "amount", "remaining"),
    [
        # Apple, 8-K EX-99.1 of 2024-05-02 (both sentences of the release).
        (
            "“Given our confidence in Apple’s future and the value we see in our stock, our "
            "Board has authorized an additional $110 billion for share repurchases.",
            "increase",
            110 * B,
            None,
        ),
        (
            "The board of directors has also authorized an additional program to repurchase up "
            "to $110 billion of the Company’s common stock.",
            "increase",
            110 * B,
            None,
        ),
        # NVIDIA, 8-K EX-99.1 of 2025-08-27, and its 2026-09-28 release (title, then text).
        (
            "As of the end of the second quarter, the company had $14.7 billion remaining under "
            "its share repurchase authorization.",
            "remaining",
            Decimal("14.7") * B,
            None,
        ),
        (
            "NVIDIA Announces a $150 Billion Share Repurchase Authorization Increase",
            "increase",
            150 * B,
            None,
        ),
        (
            "NVIDIA today announced that its Board of Directors has authorized an additional $150 "
            "billion under the company’s existing share repurchase program, increasing the total "
            "remaining amount authorized to $235 billion.",
            "increase",
            150 * B,
            235 * B,
        ),
        # ExxonMobil, 8-K EX-99.1 of 2025-08-01 and 2025-10-31: a yearly plan (B9).
        (
            "Industry-leading year-to-date shareholder distributions of $18.4 billion included "
            "$8.6 billion of dividends and $9.8 billion of share repurchases, consistent with "
            "the company's plan to deliver $20 billion of share repurchases this year.",
            "plan",
            20 * B,
            None,
        ),
        (
            "Shareholder distributions of $27.8 billion included $12.9 billion of dividends and "
            "$14.9 billion of share repurchases, consistent with the company's plan to "
            "repurchase $20 billion of shares this year.",
            "plan",
            20 * B,
            None,
        ),
        ("Meta Announces a $50 Billion Share Repurchase Program", "new", 50 * B, None),
        # Meta, 8-K and EX-99.1 of 2024-02-01.
        (
            "On February 1, 2024, Meta announced an increase of $50 billion in the amount "
            "authorized for repurchases under the program.",
            "increase",
            50 * B,
            None,
        ),
        (
            "We also announced a $50 billion increase in our share repurchase authorization today.",
            "increase",
            50 * B,
            None,
        ),
        (
            "As of December 31, 2023, $30.93 billion remained available and authorized for "
            "repurchases under the program.",
            "remaining",
            Decimal("30.93") * B,
            None,
        ),
        (
            "As of December 31, 2023, we had $30.93 billion available and authorized for "
            "repurchases.",
            "remaining",
            Decimal("30.93") * B,
            None,
        ),
        (
            "The Board approved a new $500 million stock repurchase program.",
            "new",
            500 * 10**6,
            None,
        ),
    ],
)
def test_authorizations_plans_and_remaining_amounts(
    sentence: str, kind: str, amount: Decimal, remaining: Decimal | None
) -> None:
    found = statement(sentence)
    assert found is not None, sentence
    assert (found.kind, found.amount, found.remaining_amount) == (kind, amount, remaining)
    assert len(found.sentence) <= MAX_SENTENCE


@pytest.mark.parametrize(
    "sentence",
    [
        # Executed repurchases, however large, are not authorizations (NVIDIA, Meta).
        "We returned $10.0 billion to shareholders in the second quarter through $9.7 billion of "
        "share repurchases and $244 million of cash dividends.",
        "During the first half of fiscal 2026, NVIDIA returned $24.3 billion to shareholders in "
        "the form of shares repurchased and cash dividends.",
        "Under its repurchase authorization, the company repurchased $5.0 billion of shares.",
        "Capital return program – We repurchased $13.4 billion of our Class A common stock.",
        # Debt, not shares.
        "The Board approved a tender offer to repurchase up to $2 billion of the Company's notes.",
        # Recaps and status lines (Meta 2021, AutoZone, Alphabet 2021-07, JPMorgan supplements).
        "This authorization is in addition to the previously authorized repurchases of up to $34 "
        "billion of our shares of Class A common stock.",
        "Since the inception of the repurchase program in 1998, and including the above amount, "
        "AutoZone’s Board of Directors has authorized $26.15 billion in share repurchases.",
        "As we previously announced in April 2021, the Alphabet board authorized the company to "
        "repurchase up to an additional $50 billion of its Class C capital stock.",
        "The Firm is authorized to purchase up to $30 billion of common shares under the current "
        "repurchase program.",
        "(a)The Firm was authorized to purchase up to $30 billion of common shares under its "
        "repurchase program announced on April 13, 2022.",
        "(a)Effective July 1, 2024, the Firm’s Board of Directors had authorized a common share "
        "repurchase program of $30 billion that replaced the previous program.",
        "(b)The Firm’s Board of Directors authorized a new common share repurchase program of up "
        "to $50 billion effective July 1, 2025, which replaced the previous program.",
        # No amount, or no repurchase.
        "The Board authorized a share repurchase program.",
        "Revenue was $33.1 billion and increased 16%.",
    ],
)
def test_executed_buybacks_debt_and_other_amounts_never_match(sentence: str) -> None:
    assert statement(sentence) is None


def test_a_stated_date_identifies_a_repeated_announcement() -> None:
    found = statement(
        "On August 26, 2025, the Board of Directors approved an additional $60.0 billion to the "
        "Company’s share repurchase authorization, without expiration."
    )
    assert found is not None
    assert (found.kind, found.amount, found.stated_date) == ("increase", 60 * B, date(2025, 8, 26))


def test_document_text_keeps_blocks_and_drops_hidden_xbrl() -> None:
    raw = (
        b"<html><body><div style='display:none'><ix:header>2025-08-26<br>hidden</ix:header>"
        b"</div><p>NVIDIA reports results.</p><ul><li>Our Board has authorized an additional "
        b"$60.0 billion for share repurchases.</li><li>Revenue was $46.7 billion.</li></ul>"
        b"<table><tr><td>Share repurchases</td><td>$ 9,720</td></tr></table></body></html>"
    )
    text = document_text(raw)
    assert "hidden" not in text and "2025-08-26" not in text
    assert sentences(text)[:2] == [
        "NVIDIA reports results.",
        "Our Board has authorized an additional $60.0 billion for share repurchases.",
    ]
    found = statements(text)
    assert [(s.kind, s.amount) for s in found] == [("increase", 60 * B)]


def test_long_sentences_are_cut_around_the_amount() -> None:
    sentence = (
        "In light of " + "a long preamble about strategy, " * 12 + "our Board has authorized "
        "an additional $90 billion for share repurchases, " + "and further commentary " * 10 + "."
    )
    found = statement(sentence)
    assert found is not None and len(found.sentence) <= MAX_SENTENCE
    assert "$90 billion" in found.sentence and found.sentence.startswith("…")


def test_one_statement_per_kind_and_amount_in_a_document() -> None:
    text = (
        "Our Board has authorized an additional $110 billion for share repurchases.\n"
        "The board of directors has also authorized an additional program to repurchase up to "
        "$110 billion of the Company’s common stock."
    )
    assert len(statements(text)) == 1


def test_programs_of_the_same_size_with_their_own_dates_are_kept_apart() -> None:
    # Microsoft's 2024 summary lists the 2019 and 2021 programs; the 2021 and 2024 ones are $60B.
    text = (
        "On September 14, 2021, our Board of Directors approved a share repurchase program "
        "authorizing up to $60.0 billion in share repurchases.\n"
        "On September 16, 2024, our Board of Directors approved a new share repurchase program "
        "authorizing up to $60.0 billion in share repurchases."
    )
    assert [s.stated_date for s in statements(text)] == [date(2021, 9, 14), date(2024, 9, 16)]


def test_a_remaining_amount_still_counts_in_a_recap() -> None:
    found = statement(
        "Share repurchases – We repurchased $14.37 billion of our Class A common stock in the "
        "third quarter and had $7.97 billion remaining on our prior share repurchase authorization."
    )
    assert found is not None and (found.kind, found.amount) == ("remaining", Decimal("7.97") * B)
