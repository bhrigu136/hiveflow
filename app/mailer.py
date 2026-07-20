"""Transactional email delivery.

Deliberately free of Flask and of any route module: both `routes.auth` and
`security_utils` need to send mail, and having the latter reach into the former
created an import cycle (`routes.auth` -> `security_utils` -> `routes.auth`)
that only survived because one side deferred its import inside a function body.
"""
import os

import requests

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_via_brevo(to_email: str, subject: str, html: str) -> str:
    """Send a transactional email via Brevo's HTTP API.

    Render blocks outbound SMTP, so we use HTTPS instead.
    Returns 'sent', 'unconfigured', or 'failed'.
    """
    api_key = os.environ.get('BREVO_API_KEY')
    sender = os.environ.get('MAIL_SENDER')
    if not api_key or not sender:
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
            return 'sent'
        print(f"[BREVO ERROR] {resp.status_code}: {resp.text[:300]}")
        return 'failed'
    except Exception as e:
        print(f"[BREVO ERROR] {type(e).__name__}: {e}")
        return 'failed'
