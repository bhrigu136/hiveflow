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

