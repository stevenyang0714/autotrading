"""Outbound-only access to the Telegram Bot API (M3.0b, ADR-037; OD-2 decided in ADR-035).

The bot token is part of every request path (`/bot<token>/<method>`), so it must never reach
a log, an exception chain or the database: the client allows only api.telegram.org and three
methods, silences httpx's request log, raises its errors `from None`, and replaces the token
in any text it reports. The chat id travels in the JSON body only. Nothing inbound: no
webhook, no polling loop; `recent_chats` exists only for `make telegram-check`, which Steven
runs himself to find his chat id.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, Self
from urllib.parse import urlparse

import httpx2 as httpx

from autotrading.settings import Settings, get_settings

logger = logging.getLogger(__name__)
for noisy in ("httpx2", "httpcore2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

HOST = "api.telegram.org"
BASE_URL = f"https://{HOST}"
METHODS = frozenset({"getMe", "getUpdates", "sendMessage"})
# where an update carries its chat (a private message is `message`; `/start` too)
UPDATE_KINDS = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "my_chat_member",
    "chat_member",
    "callback_query",
)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
TIMEOUT_SECONDS = 20.0
MAX_ERROR = 300


class TelegramConfigError(RuntimeError):
    """Telegram is not configured; the message says what to set, never the value."""


class TelegramError(RuntimeError):
    """Telegram refused or failed a request after the client's own retries. The message is
    cleaned of the token; `code` is Telegram's error code or the HTTP status."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _secret(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    return str(getter()).strip() if callable(getter) else ""


def configured(settings: Settings | None = None) -> bool:
    """Whether both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
    current = settings or get_settings()
    return bool(_secret(current.telegram_bot_token) and _secret(current.telegram_chat_id))


def chat_id(settings: Settings | None = None) -> str:
    current = settings or get_settings()
    value = _secret(current.telegram_chat_id)
    if not value:
        raise TelegramConfigError("TELEGRAM_CHAT_ID is not set: run `make telegram-check`.")
    return value


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token.strip():
            raise TelegramConfigError(
                "TELEGRAM_BOT_TOKEN is not set: create a bot with @BotFather and add its token "
                "to .env (ADR-037)."
            )
        self._token = token.strip()
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
        )
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Self:
        current = settings or get_settings()
        return cls(_secret(current.telegram_bot_token))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def clean(self, text: str) -> str:
        """Text safe to log or store: the token replaced, at most 300 characters."""
        return text.replace(self._token, "***")[:MAX_ERROR]

    def call(self, method: str, payload: dict[str, Any]) -> Any:
        """One Bot API method; returns its `result`. 429 and 5xx are retried with backoff."""
        if method not in METHODS:
            raise TelegramError(f"refused: {method} is not an allowed method")
        path = f"/bot{self._token}/{method}"
        if urlparse(f"{BASE_URL}{path}").hostname != HOST:  # defence in depth; BASE_URL is fixed
            raise TelegramError("refused: not the Telegram API host")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._client.post(path, json=payload)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
                self._sleep(self._backoff(attempt, None))
                continue
            try:
                body = response.json()
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            if response.status_code == 200 and body.get("ok") is True:
                return body.get("result")
            code = body.get("error_code") or response.status_code
            parameters = body.get("parameters") or {}
            retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
            reason = self.clean(str(body.get("description") or f"HTTP {response.status_code}"))
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise TelegramError(f"{method}: {reason}", int(code)) from None
            delay = self._backoff(attempt, retry_after)
            logger.warning("Telegram %s returned %s; retrying in %.1fs", method, code, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def send(self, chat: str, text: str) -> int:
        """Send a plain-text message (no parse mode, no link preview); returns its message id.
        Only the id is kept from Telegram's reply."""
        result = self.call(
            "sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": True}
        )
        return int(result["message_id"])

    def bot_name(self) -> str:
        """The bot's own @username (not a secret), so Steven can check the token is his bot."""
        me = self.call("getMe", {}) or {}
        return f"@{me.get('username')}" if me.get("username") else str(me.get("first_name", ""))

    def recent_chats(self) -> list[tuple[str, str]]:
        """(chat id, title or name) of the chats that wrote to the bot recently, for
        `make telegram-check` only."""
        found: dict[str, str] = {}
        for update in self.call("getUpdates", {"timeout": 0}) or []:
            for kind in UPDATE_KINDS:
                carrier = update.get(kind) or {}
                if kind == "callback_query":
                    carrier = carrier.get("message") or {}
                chat = carrier.get("chat") or {}
                if "id" in chat:
                    name = chat.get("title") or chat.get("username") or chat.get("first_name")
                    found[str(chat["id"])] = str(name or "")
        return list(found.items())

    @staticmethod
    def _backoff(attempt: int, retry_after: object) -> float:
        if isinstance(retry_after, int) and retry_after >= 0:
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        return min(BASE_BACKOFF_SECONDS * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)
