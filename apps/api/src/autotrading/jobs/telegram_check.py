"""Set up and test Telegram alert delivery (M3.0b, ADR-037): `make telegram-check`.

Steven runs this himself, on the Mac (it reads .env directly), after creating his bot with
@BotFather and putting TELEGRAM_BOT_TOKEN in .env:

- without TELEGRAM_CHAT_ID it lists the chats that wrote to the bot (send the bot any message
  first) so he can copy his chat id into .env;
- with both set it sends one test message.

It prints the chat id only when asked for it, never the token. After editing .env, run
`make up` so the worker sees the new variables.
"""

import sys

from autotrading.adapters.telegram.client import (
    TelegramClient,
    TelegramConfigError,
    TelegramError,
    chat_id,
)
from autotrading.settings import get_settings

TEST_MESSAGE = (
    "[autotrading] Telegram delivery is set up. Alerts chosen by the delivery rules arrive "
    "here.\nRule output, unvalidated, not advice. Paper only."
)


def main() -> int:
    settings = get_settings()
    try:
        client = TelegramClient.from_settings(settings)
    except TelegramConfigError as exc:
        print(exc)
        return 1
    with client:
        try:
            chat = chat_id(settings)
        except TelegramConfigError:
            try:
                bot = client.bot_name()
                chats = client.recent_chats()
            except TelegramError as exc:
                print(f"Telegram refused the request: {exc}")
                return 1
            print(f"The token in .env belongs to the bot {bot}.")
            if not chats:
                print(
                    f"No chat has written to {bot} yet. In Telegram, search for {bot} (not "
                    "@BotFather), press Start and send it any message, then run this again. If "
                    "you messaged a bot with another name, the token in .env is that other "
                    "bot's: copy the right one from @BotFather (/mybots, API Token)."
                )
                return 1
            print("Chats that wrote to the bot (put yours in .env, then run `make up`):")
            for found, name in chats:
                print(f"  TELEGRAM_CHAT_ID={found}    ({name})")
            return 0
        try:
            client.send(chat, TEST_MESSAGE)
        except TelegramError as exc:
            print(f"The test message was not sent: {exc}")
            return 1
    print("Test message sent. Run `make up` if you just edited .env, so the worker sees it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
