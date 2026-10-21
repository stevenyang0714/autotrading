"""The Telegram Bot API client (M3.0b, ADR-037): outbound only, the token never logged or
reported, retries on 429 and 5xx, only the message id kept."""

import json
import logging

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from autotrading.adapters.telegram.client import (
    TelegramClient,
    TelegramConfigError,
    TelegramError,
    chat_id,
    configured,
)
from autotrading.settings import Settings

TOKEN = "123456:ABC-secret-token"
CHAT = "987654321"


def client(handler: object, sleeps: list[float] | None = None) -> TelegramClient:
    return TelegramClient(
        TOKEN,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_a_message_is_sent_as_plain_text_and_only_its_id_is_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = {"message_id": 42, "chat": {"id": int(CHAT), "username": "steven"}}
        return httpx.Response(200, json={"ok": True, "result": reply})

    caplog.set_level(logging.DEBUG)
    assert client(handler).send(CHAT, "hello") == 42
    request = seen[0]
    assert request.url.host == "api.telegram.org"
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    body = json.loads(request.content)
    assert body == {"chat_id": CHAT, "text": "hello", "disable_web_page_preview": True}
    assert "parse_mode" not in body
    assert TOKEN not in caplog.text and CHAT not in caplog.text


def test_429_and_5xx_are_retried_honouring_retry_after(caplog: pytest.LogCaptureFixture) -> None:
    replies = iter(
        [
            httpx.Response(
                429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}
            ),
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json={"ok": True, "result": {"message_id": 5}}),
        ]
    )
    sleeps: list[float] = []
    caplog.set_level(logging.DEBUG)
    assert client(lambda _: next(replies), sleeps).send(CHAT, "x") == 5
    assert sleeps == [7.0, 4.0]
    assert TOKEN not in caplog.text


def test_a_refusal_reports_a_cleaned_reason_without_the_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        reason = f"Bad Request: chat not found for bot{TOKEN}"
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": reason})

    caplog.set_level(logging.DEBUG)
    with pytest.raises(TelegramError) as raised:
        client(handler).send(CHAT, "x")
    assert raised.value.code == 400
    assert str(raised.value) == "sendMessage: Bad Request: chat not found for bot***"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert TOKEN not in caplog.text


def test_a_network_failure_names_the_error_type_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(TelegramError) as raised:
        client(handler).send(CHAT, "x")
    assert str(raised.value) == "sendMessage failed: ConnectError"
    assert TOKEN not in str(raised.value)


def test_only_three_methods_are_allowed() -> None:
    with pytest.raises(TelegramError, match="not an allowed method"):
        client(lambda _: httpx.Response(200)).call("deleteMessage", {})


def test_recent_chats_lists_who_wrote_to_the_bot() -> None:
    updates = [
        {"update_id": 1, "message": {"chat": {"id": 11, "username": "steven"}}},
        {"update_id": 2, "message": {"chat": {"id": 11, "username": "steven"}}},
        {"update_id": 3, "my_chat_member": {"chat": {"id": -22, "title": "group"}}},
    ]
    found = client(lambda _: httpx.Response(200, json={"ok": True, "result": updates}))
    assert found.recent_chats() == [("11", "steven"), ("-22", "group")]


def test_settings_decide_whether_delivery_is_configured() -> None:
    empty = Settings(telegram_bot_token=None, telegram_chat_id=None)
    assert not configured(empty)
    with pytest.raises(TelegramConfigError, match="TELEGRAM_BOT_TOKEN is not set"):
        TelegramClient.from_settings(empty)
    with pytest.raises(TelegramConfigError, match="make telegram-check"):
        chat_id(empty)
    both = Settings(telegram_bot_token=SecretStr(TOKEN), telegram_chat_id=SecretStr(CHAT))
    assert configured(both)
    assert TOKEN not in repr(both) and CHAT not in repr(both)
