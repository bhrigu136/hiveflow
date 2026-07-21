from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_login import LoginManager
import os

os.environ.setdefault('TZ', 'UTC')

from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
limiter = Limiter(key_func=get_remote_address)

# ── Pusher Real-Time WebSocket Lazy Initializer ────────────────────────────────
pusher_client = None

def get_pusher():
    global pusher_client
    if pusher_client is None:
        app_id = os.environ.get('PUSHER_APP_ID')
        key = os.environ.get('PUSHER_KEY')
        secret = os.environ.get('PUSHER_SECRET')
        cluster = os.environ.get('PUSHER_CLUSTER', 'ap2')
        if app_id and key and secret:
            try:
                from pusher import Pusher
                pusher_client = Pusher(
                    app_id=app_id,
                    key=key,
                    secret=secret,
                    cluster=cluster,
                    ssl=True
                )
            except Exception:
                pusher_client = None
    return pusher_client


def broadcast_event(channel, event, data, *, failure_desc):
    """Best-effort Pusher broadcast for a single event.

    Skips silently when Pusher isn't configured; if the trigger raises, logs a
    warning instead of propagating — the primary write has already been
    committed, so a Pusher outage must never break the request. Extracted from
    the identical guard/try/except/log blocks in the discussion and meeting-intel
    routes. ``failure_desc`` is the human label used in the warning, e.g.
    ``'new-comment broadcast failed for discussion 42'``.
    """
    from flask import current_app
    pusher = get_pusher()
    if not pusher:
        return
    try:
        pusher.trigger(channel, event, data)
    except Exception as e:
        # Broad catch is intentional: a Pusher outage must never break the
        # request. Logged rather than swallowed silently.
        current_app.logger.warning(
            f'[pusher] {failure_desc}: {type(e).__name__}: {e}'
        )


def broadcast_batch(channel, event, payloads, *, failure_desc):
    """Best-effort Pusher broadcast of many payloads to one channel/event.

    The batch sibling of :func:`broadcast_event` (e.g. caption finals). Same
    contract — skip when Pusher isn't configured, and on the first failing
    trigger stop and log a single warning instead of propagating — matching the
    previous inline behaviour: one ``try`` around the whole loop, one warning.
    """
    from flask import current_app
    pusher = get_pusher()
    if not pusher:
        return
    try:
        for payload in payloads:
            pusher.trigger(channel, event, payload)
    except Exception as e:
        current_app.logger.warning(
            f'[pusher] {failure_desc}: {type(e).__name__}: {e}'
        )

