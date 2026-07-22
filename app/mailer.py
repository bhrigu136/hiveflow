"""Transactional email delivery.

Deliberately free of Flask and of any route module: both `routes.auth` and
`security_utils` need to send mail, and having the latter reach into the former
created an import cycle (`routes.auth` -> `security_utils` -> `routes.auth`)
that only survived because one side deferred its import inside a function body.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_via_brevo(to_email: str, subject: str, html: str) -> str:
    """Send a transactional email via Brevo's HTTP API.

    Render blocks outbound SMTP, so we use HTTPS instead.
    Returns 'sent', 'unconfigured', or 'failed'.
    """
    api_key = os.environ.get('BREVO_API_KEY')
    sender = os.environ.get('MAIL_SENDER')
    if not api_key or not sender:
        logger.warning(
            "Email not sent: %s not configured. "
            "Set BREVO_API_KEY and MAIL_SENDER environment variables.",
            "BREVO_API_KEY" if not api_key else "MAIL_SENDER",
        )
        return 'unconfigured'

    try:
        resp = requests.post(
            BREVO_API_URL,
            headers={
                'api-key': api_key,
                'content-type': 'application/json',
                'accept': 'application/json',
            },
            json={
                'sender': {'email': sender, 'name': 'HiveFlow'},
                'to': [{'email': to_email}],
                'subject': subject,
                'htmlContent': html,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            logger.info("Email sent successfully to %s", to_email)
            return 'sent'
        # Truncate response body to avoid leaking sensitive data in logs
        body_snippet = resp.text[:200] if resp.text else '(empty)'
        logger.error(
            "[BREVO] HTTP %d sending to %s: %s",
            resp.status_code, to_email, body_snippet,
        )
        if resp.status_code == 401 and 'IP' in resp.text:
            logger.error(
                "[BREVO] 401 likely caused by IP restriction. "
                "Go to Brevo → Settings → Security → Authorized IPs "
                "→ Deactivate for API keys."
            )
        return 'failed'
    except Exception as e:
        logger.error("[BREVO] %s sending to %s: %s", type(e).__name__, to_email, e)
        return 'failed'
