"""Actor attribution for the audit triggers."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_actor(session: Session, actor: str) -> None:
    """Attribute every audited change in the current transaction to `actor`.

    The audit trigger reads `app.actor`; transaction-local, so it resets at commit/rollback.
    Without it, the database role name is recorded.
    """
    session.execute(text("SELECT set_config('app.actor', :actor, true)"), {"actor": actor})
