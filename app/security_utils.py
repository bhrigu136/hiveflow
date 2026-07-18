"""Login-session tracking, device/IP detection and activity logging.

This module powers the "Security / Your Devices" feature: every login is
recorded with the device, IP address and approximate location, each request
refreshes the session's last-seen time and optionally logs an activity entry,
and revoked sessions are force-logged-out on their next request.

Everything here is best-effort: a failure to look up a location or write an
activity row must never break a real user request, so the public helpers
swallow their own exceptions.
"""
import secrets
import threading
from datetime import datetime, timezone, timedelta

import requests
from flask import request, session, current_app, url_for
from flask_login import current_user, logout_user

from app.extensions import db

SESSION_KEY = 'login_session_token'

# How often we bother updating last_seen (avoid a DB write on every single hit).
_LAST_SEEN_THROTTLE = timedelta(seconds=60)

# Endpoints we never log to the activity trail — high-frequency polling and
# static assets would otherwise flood the table with noise.
_ACTIVITY_DENYLIST = {
    'static',
    'auth.theme_update',
    'auth.security',            # viewing the security page itself
    'notifications.unread_count',
    'notifications.list_notifications',
}


# ─── Client IP ────────────────────────────────────────────────────────────────

def get_client_ip() -> str:
    """Best-effort real client IP, honouring the proxy chain on Render/Heroku.

    X-Forwarded-For is a comma-separated list; the left-most entry is the
    original client. Falls back to the socket peer address.
    """
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'


def _is_private_ip(ip: str) -> bool:
    """True for localhost / LAN addresses that have no public geolocation."""
    if not ip or ip in ('unknown', '127.0.0.1', '::1', 'localhost'):
        return True
    return (
        ip.startswith('10.')
        or ip.startswith('192.168.')
        or ip.startswith('172.16.')
        or ip.startswith('172.17.')
        or ip.startswith('172.18.')
        or ip.startswith('172.19.')
        or ip.startswith('172.2')      # 172.20–172.29
        or ip.startswith('172.30.')
        or ip.startswith('172.31.')
        or ip.startswith('fc')         # IPv6 unique-local
        or ip.startswith('fd')
    )


def lookup_location(ip: str) -> str:
    """Resolve an IP to "City, Country" using the free ip-api.com service.

    Returns 'Local network' for private/loopback IPs and 'Unknown' on any
    failure. Runs with a short timeout so a slow/unreachable lookup never
    noticeably delays login.
    """
    if _is_private_ip(ip):
        return 'Local network'
    try:
        resp = requests.get(
            f'http://ip-api.com/json/{ip}',
            params={'fields': 'status,country,city'},
            timeout=4,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'success':
                city = data.get('city') or ''
                country = data.get('country') or ''
                label = ', '.join(part for part in (city, country) if part)
                return label or 'Unknown'
    except Exception as e:  # network error, timeout, bad JSON — degrade quietly
        current_app.logger.info(f'[geo] lookup failed for {ip}: {type(e).__name__}')
    return 'Unknown'


# ─── User-Agent parsing (dependency-free, good-enough heuristics) ──────────────

def parse_user_agent(ua: str) -> tuple[str, str, str]:
    """Return (browser, os, device) parsed from a User-Agent string.

    Deliberately simple substring matching — covers the common cases without
    pulling in an extra dependency. Order matters (e.g. Edge/Chrome both
    contain 'Chrome'; iPad/iPhone before generic Mac).
    """
    if not ua:
        return ('Unknown browser', 'Unknown OS', 'Desktop')
    u = ua.lower()

    # ── OS / device ──
    if 'iphone' in u:
        os_name, device = 'iOS (iPhone)', 'Mobile'
    elif 'ipad' in u:
        os_name, device = 'iPadOS', 'Tablet'
    elif 'android' in u:
        os_name = 'Android'
        device = 'Mobile' if 'mobile' in u else 'Tablet'
    elif 'windows' in u:
        os_name, device = 'Windows', 'Desktop'
    elif 'mac os' in u or 'macintosh' in u:
        os_name, device = 'macOS', 'Desktop'
    elif 'cros' in u:
        os_name, device = 'ChromeOS', 'Desktop'
    elif 'linux' in u:
        os_name, device = 'Linux', 'Desktop'
    else:
        os_name, device = 'Unknown OS', 'Desktop'

    # ── Browser (check the more specific brands first) ──
    if 'edg/' in u or 'edge' in u:
        browser = 'Edge'
    elif 'opr/' in u or 'opera' in u:
        browser = 'Opera'
    elif 'samsungbrowser' in u:
        browser = 'Samsung Internet'
    elif 'chrome' in u and 'chromium' not in u:
        browser = 'Chrome'
    elif 'chromium' in u:
        browser = 'Chromium'
    elif 'firefox' in u or 'fxios' in u:
        browser = 'Firefox'
    elif 'safari' in u:
        browser = 'Safari'
    else:
        browser = 'Unknown browser'

    return (browser, os_name, device)


# ─── Login / logout lifecycle ─────────────────────────────────────────────────

def record_login_session(user) -> None:
    """Create a LoginSession for the just-authenticated user and remember its
    token in the Flask session cookie. Call immediately after login_user()."""
    from app.models import LoginSession

    ip = get_client_ip()
    ua = request.headers.get('User-Agent', '')
    browser, os_name, device = parse_user_agent(ua)

    token = secrets.token_urlsafe(32)
    ls = LoginSession(
        user_id=user.id,
        session_token=token,
        ip_address=ip,
        location=lookup_location(ip),
        user_agent=ua[:1000] if ua else None,
        browser=browser,
        os=os_name,
        device=device,
    )
    db.session.add(ls)
    db.session.commit()

    session[SESSION_KEY] = token
    session.permanent = True

    # If this device/location is new for the user, send a security alert email.
    try:
        if _is_new_login_device(user.id, browser, os_name, ls.location, ls.id):
            send_new_login_alert(user, ls)
    except Exception as e:
        current_app.logger.info(f'[login-alert] skipped: {type(e).__name__}: {e}')


def _is_new_login_device(user_id, browser, os_name, location, exclude_id) -> bool:
    """True when the user has logged in before but never from this
    browser+OS+location combination. The very first login ever returns False
    (nothing to compare against, so no alert)."""
    from app.models import LoginSession

    prior = LoginSession.query.filter(
        LoginSession.user_id == user_id,
        LoginSession.id != exclude_id,
    )
    if prior.count() == 0:
        return False  # first login on the account — don't alert
    match = prior.filter(
        LoginSession.browser == browser,
        LoginSession.os == os_name,
        LoginSession.location == location,
    ).first()
    return match is None


def send_new_login_alert(user, ls) -> None:
    """Email the user that their account was signed into from a new device.

    The email body and the (external) security-page link are built here, inside
    the active request context, then the actual HTTP send is handed to a daemon
    thread so a slow mail provider never delays the login response.
    """
    if not getattr(user, 'email', None):
        return

    when = (ls.created_at or datetime.now(timezone.utc)).strftime('%b %d, %Y at %I:%M %p UTC')
    security_url = url_for('auth.security', _external=True)
    name = user.name or user.username or 'there'

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;">
        <div style="text-align:center;margin-bottom:24px;">
            <h2 style="color:#1a1a2e;margin:0;">HiveFlow</h2>
            <p style="color:#666;font-size:14px;">New sign-in detected</p>
        </div>
        <div style="background:#f8f9fa;border-radius:12px;padding:24px;">
            <p style="color:#333;font-size:15px;margin:0 0 14px;">Hi <strong>{name}</strong>,</p>
            <p style="color:#666;font-size:14px;margin:0 0 18px;">
                Your HiveFlow account was just signed into from a device or location we
                haven't seen before:
            </p>
            <table style="width:100%;font-size:14px;color:#333;border-collapse:collapse;">
                <tr><td style="padding:6px 0;color:#888;">Device</td><td style="padding:6px 0;text-align:right;"><strong>{ls.device_label}</strong></td></tr>
                <tr><td style="padding:6px 0;color:#888;">Location</td><td style="padding:6px 0;text-align:right;"><strong>{ls.location or 'Unknown'}</strong></td></tr>
                <tr><td style="padding:6px 0;color:#888;">IP address</td><td style="padding:6px 0;text-align:right;">{ls.ip_address or 'unknown'}</td></tr>
                <tr><td style="padding:6px 0;color:#888;">Time</td><td style="padding:6px 0;text-align:right;">{when}</td></tr>
            </table>
        </div>
        <div style="text-align:center;margin:22px 0;">
            <a href="{security_url}" style="display:inline-block;background:linear-gradient(135deg,#4361ee,#7c3aed);color:#fff;padding:13px 30px;border-radius:10px;text-decoration:none;font-weight:600;font-size:14px;">
                Review your devices
            </a>
        </div>
        <p style="color:#999;font-size:12px;text-align:center;margin-top:8px;">
            If this was you, no action is needed. If you don't recognise this,
            open the page above to log that device out, then change your password.
        </p>
    </div>
    """
    subject = 'HiveFlow — New sign-in to your account'

    def _deliver():
        try:
            from app.routes.auth import _send_via_brevo
            _send_via_brevo(user.email, subject, html)
        except Exception:
            pass  # best-effort; nothing to do if mail fails

    threading.Thread(target=_deliver, daemon=True).start()


def revoke_current_session() -> None:
    """Mark the active device's LoginSession as revoked. Call before
    logout_user() so the row reflects an intentional sign-out."""
    from app.models import LoginSession

    token = session.get(SESSION_KEY)
    if not token:
        return
    ls = LoginSession.query.filter_by(session_token=token, revoked=False).first()
    if ls:
        ls.revoked = True
        ls.revoked_at = datetime.now(timezone.utc)
        db.session.commit()
    session.pop(SESSION_KEY, None)


# ─── Per-request tracking (called from before/after_request) ──────────────────

def _humanize_action(endpoint: str | None, method: str) -> str:
    """Turn an endpoint + method into a readable activity label."""
    if not endpoint:
        return f'{method} {request.path}'
    # 'tasks.view_tasks' -> ('tasks', 'view tasks')
    _, _, name = endpoint.partition('.')
    name = name.replace('_', ' ').strip() or endpoint
    verb = 'Viewed' if method == 'GET' else 'Submitted'
    return f'{verb} {name}'


def track_request() -> bool:
    """before_request hook. Returns True normally; the caller should treat a
    returned Flask response (from logout redirect) specially.

    Responsibilities:
      • enforce remote revocation — a revoked device is logged out at once
      • refresh last_seen (throttled)
    The activity row itself is written in after_request (log_activity) once we
    know the endpoint resolved cleanly.
    """
    from app.models import LoginSession

    if not current_user.is_authenticated:
        return True
    token = session.get(SESSION_KEY)
    if not token:
        # Authenticated via an older cookie from before this feature existed —
        # mint a session row so they appear on the security page too.
        try:
            record_login_session(current_user)
        except Exception:
            db.session.rollback()
        return True

    ls = LoginSession.query.filter_by(session_token=token).first()
    if ls is None:
        return True
    if ls.revoked:
        # This device was logged out remotely — end the session now.
        session.pop(SESSION_KEY, None)
        logout_user()
        return False  # signal: user is no longer logged in

    now = datetime.now(timezone.utc)
    last = ls.last_seen
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or (now - last) > _LAST_SEEN_THROTTLE:
        ls.last_seen = now
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return True


def log_activity(response) -> None:
    """after_request hook — record a single activity row for meaningful hits."""
    from app.models import LoginSession, ActivityLog

    try:
        if not current_user.is_authenticated:
            return
        endpoint = request.endpoint
        if not endpoint or endpoint in _ACTIVITY_DENYLIST:
            return
        # Skip noisy redirects/errors and asset requests
        if response.status_code >= 400:
            return

        token = session.get(SESSION_KEY)
        session_id = None
        if token:
            ls = LoginSession.query.filter_by(session_token=token).first()
            session_id = ls.id if ls else None

        entry = ActivityLog(
            user_id=current_user.id,
            session_id=session_id,
            action=_humanize_action(endpoint, request.method),
            method=request.method,
            path=request.path[:255],
            ip_address=get_client_ip(),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        # Activity logging is strictly best-effort — never surface an error.
        try:
            db.session.rollback()
        except Exception:
            pass
