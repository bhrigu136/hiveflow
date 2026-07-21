"""Authentication flow tests.

Some tests here are xfail(strict=True): they specify the CORRECT behaviour for
findings that are still open (SEC-006, SEC-007). They are expected to fail now.
If one starts passing, strict xfail turns that into a suite failure — a prompt
to remove the marker and treat the finding as fixed. The xfail marker is thus a
live tracker of the open finding, expressed as an executable spec.
"""
import pytest

from app.extensions import db
from app.models import User


def _register(client, email, password="Passw0rd", name="Test User"):
    return client.post("/auth/register", data={
        "name": name, "email": email,
        "password": password, "confirm_password": password,
    })


@pytest.mark.integration
class TestRegistration:
    def test_valid_registration_creates_user(self, app, client):
        _register(client, "new@example.com")
        with app.app_context():
            u = User.query.filter_by(email="new@example.com").first()
            assert u is not None
            assert u.email_verified is False  # verification required

    def test_password_never_stored_plaintext(self, app, client):
        _register(client, "pw@example.com", password="Secret123")
        with app.app_context():
            u = User.query.filter_by(email="pw@example.com").first()
            assert "Secret123" not in (u.password_hash or "")
            assert u.check_password("Secret123")

    def test_weak_password_rejected(self, app, client):
        _register(client, "weak@example.com", password="short")
        with app.app_context():
            assert User.query.filter_by(email="weak@example.com").first() is None

    def test_password_mismatch_rejected(self, app, client):
        client.post("/auth/register", data={
            "name": "X", "email": "mm@example.com",
            "password": "Passw0rd", "confirm_password": "Different1",
        })
        with app.app_context():
            assert User.query.filter_by(email="mm@example.com").first() is None


@pytest.mark.integration
class TestLogin:
    def _make_verified_user(self, app, email="v@example.com"):
        with app.app_context():
            u = User(username="v", email=email, email_verified=True)
            u.set_password("Passw0rd")
            db.session.add(u)
            db.session.commit()

    def test_correct_credentials_succeed(self, app, client):
        self._make_verified_user(app)
        r = client.post("/auth/login",
                        data={"email": "v@example.com", "password": "Passw0rd"})
        assert r.status_code == 302  # redirect on success

    def test_wrong_password_fails(self, app, client):
        self._make_verified_user(app)
        r = client.post("/auth/login",
                        data={"email": "v@example.com", "password": "wrong"})
        assert r.status_code == 200  # re-renders the form, no redirect

    def test_unverified_user_blocked(self, app, client):
        with app.app_context():
            u = User(username="uv", email="uv@example.com", email_verified=False)
            u.set_password("Passw0rd")
            db.session.add(u)
            db.session.commit()
        r = client.post("/auth/login",
                        data={"email": "uv@example.com", "password": "Passw0rd"})
        # unverified accounts are blocked at login: the form re-renders (200)
        # rather than redirecting. This confirms verification IS enforced —
        # correcting PROJECT_SPEC §W1 / SECURITY §3, which claim it is not.
        assert r.status_code == 200


@pytest.mark.integration
@pytest.mark.security
class TestKnownOpenFindings:
    """Executable specs for findings that are still open. Expected to fail."""

    @pytest.mark.xfail(strict=True,
                       reason="SEC-007: forgot-password reveals whether an email exists")
    def test_forgot_password_does_not_leak_account_existence(self, app, client):
        with app.app_context():
            u = User(username="known", email="known@example.com", email_verified=True)
            u.set_password("Passw0rd")
            db.session.add(u)
            db.session.commit()

        existing = client.post("/auth/forgot-password",
                               data={"email": "known@example.com"},
                               follow_redirects=False)
        missing = client.post("/auth/forgot-password",
                              data={"email": "absent@example.com"},
                              follow_redirects=False)
        # Correct behaviour: identical response regardless of whether the
        # account exists. Currently the redirect target differs.
        assert existing.headers.get("Location") == missing.headers.get("Location")

    @pytest.mark.xfail(strict=True,
                       reason="SEC-006: session is not rotated on login (fixation)")
    def test_session_rotated_on_login(self, app, client):
        with app.app_context():
            u = User(username="fx", email="fx@example.com", email_verified=True)
            u.set_password("Passw0rd")
            db.session.add(u)
            db.session.commit()

        with client.session_transaction() as sess:
            sess["planted"] = "attacker-fixed-value"

        client.post("/auth/login",
                    data={"email": "fx@example.com", "password": "Passw0rd"})

        with client.session_transaction() as sess:
            # Correct behaviour: login clears the pre-auth session, so a planted
            # value does not survive. Currently there is no session.clear().
            assert "planted" not in sess
