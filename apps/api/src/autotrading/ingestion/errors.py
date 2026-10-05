"""Error text that is safe to store and show: credentials in URLs are redacted."""

import re

MAX_MESSAGE_LENGTH = 500

_SECRET_PARAM = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|key|token|access[_-]?token|secret|signature)=)[^&\s'\"]+"
)
_URL_CREDENTIALS = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")


def sanitize_error(exc: BaseException) -> tuple[str, str]:
    """(exception class name, redacted and truncated message)."""
    message = _SECRET_PARAM.sub(r"\1***", str(exc))
    message = _URL_CREDENTIALS.sub(r"\1***:***@", message)
    return type(exc).__name__, message[:MAX_MESSAGE_LENGTH]
