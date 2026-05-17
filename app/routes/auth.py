import os
import secrets
import requests
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin

from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.extensions import db, limiter

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _send_via_brevo(to_email: str, subject: str, html: str) -> str:
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

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ─── Helpers ─────────────────────────────────────────────

_ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
MAX_PROFILE_SIZE = 5 * 1024 * 1024  # 5 MB

# Magic-byte signatures for allowed image types.
# imghdr was removed in Python 3.13; this replaces it with no extra deps.
_IMAGE_SIGNATURES: list[tuple[bytes, str]] = [
    (b'\xff\xd8\xff', 'jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'png'),
    (b'GIF87a', 'gif'),
    (b'GIF89a', 'gif'),
    (b'RIFF', 'webp'),   # RIFF....WEBP — checked further below
]


def _detect_image_mime(header: bytes) -> str | None:
    """Return a MIME type string from raw file bytes, or None if unrecognised."""
    for sig, mime in _IMAGE_SIGNATURES:
        if header.startswith(sig):
            if mime == 'webp' and header[8:12] != b'WEBP':
                return None
            return mime
    return None


def _validate_image_upload(file) -> str | None:
    """Return an error message string, or None if the file is valid."""
    filename = file.filename
    if not filename or '.' not in filename:
        return 'File must have a valid image extension.'
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        return f"Allowed image types: {', '.join(_ALLOWED_IMAGE_EXTS)}."
    # Read first 16 bytes to detect MIME type from content
    header = file.read(16)
    file.seek(0)
    detected = _detect_image_mime(header)
    if detected is None:
        return 'File content does not match an allowed image type.'
    return None


def validate_password(password: str) -> str | None:
    """Return an error message if the password is weak, or None if acceptable.

    Rules (NIST-inspired):
    • At least 8 characters
    • At least one uppercase letter
    • At least one digit
    """
    import re
    if len(password) < 8:
        return 'Password must be at least 8 characters.'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter.'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one number.'
    return None


def send_verification_email(to_email: str, username: str, verify_url: str) -> str:
    """Send an email-verification link via Brevo.

    Returns 'sent', 'unconfigured', or 'failed'.
    """
    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;">
        <div style="text-align:center;margin-bottom:24px;">
            <h2 style="color:#1a1a2e;margin:0;">HiveFlow</h2>
            <p style="color:#666;font-size:14px;">Email Verification</p>
        </div>
        <div style="background:#f8f9fa;border-radius:12px;padding:24px;text-align:center;">
            <p style="color:#333;font-size:15px;margin-bottom:8px;">Hi <strong>{username}</strong>,</p>
            <p style="color:#666;font-size:14px;margin-bottom:20px;">Click the button below to verify your email address. This link expires in 24 hours.</p>
            <a href="{verify_url}" style="display:inline-block;background:linear-gradient(135deg,#4361ee,#7c3aed);color:#fff;padding:14px 32px;border-radius:10px;text-decoration:none;font-weight:600;font-size:15px;">
                Verify Email
            </a>
            <p style="color:#999;font-size:12px;margin-top:20px;">Or copy this link:<br>{verify_url}</p>
        </div>
        <p style="color:#999;font-size:12px;text-align:center;margin-top:20px;">
            If you didn't create a HiveFlow account, please ignore this email.
        </p>
    </div>
    """
    return _send_via_brevo(to_email, 'HiveFlow — Verify Your Email', html)


def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit OTP code."""
    return str(secrets.randbelow(900000) + 100000)


def _is_safe_redirect(target: str) -> bool:
    """Return True only if target is a relative URL on the same host.
    Prevents open-redirect attacks via the ?next= query parameter.
    """
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in ('http', 'https')
        and ref_url.netloc == test_url.netloc
    )


def send_reset_email(to_email, code, username):
    """Send password reset code via Brevo.

    Returns 'sent' on success, 'unconfigured' if no API key, 'failed' on error.
    """
    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <h2 style="color: #1a1a2e; margin: 0;">HiveFlow</h2>
            <p style="color: #666; font-size: 14px;">Password Reset Request</p>
        </div>
        <div style="background: #f8f9fa; border-radius: 12px; padding: 24px; text-align: center;">
            <p style="color: #333; font-size: 15px; margin-bottom: 8px;">Hi <strong>{username}</strong>,</p>
            <p style="color: #666; font-size: 14px; margin-bottom: 20px;">Use this code to reset your password. It expires in 10 minutes.</p>
            <div style="font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #4361ee; padding: 16px; background: #fff; border-radius: 8px; display: inline-block;">
                {code}
            </div>
            <p style="color: #666; font-size: 14px; margin-bottom: 20px;">Please don't share this code with anyone.</p>
        </div>
        <p style="color: #999; font-size: 12px; text-align: center; margin-top: 20px;">
            If you didn't request this, please ignore this email.
        </p>
    </div>
    """
    return _send_via_brevo(to_email, 'HiveFlow — Password Reset Code', html)


# ─── Register ────────────────────────────────────────────

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.view_tasks'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('auth.register'))

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('auth.register'))

        pw_error = validate_password(password)
        if pw_error:
            flash(pw_error, 'danger')
            return redirect(url_for('auth.register'))

        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash('An account with this email already exists.', 'warning')
            return redirect(url_for('auth.register'))

        # Use the part before @ as default username
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f"{base_username}{counter}"
            counter += 1

        user = User(username=username, name=name, email=email)
        user.set_password(password)

        # Generate email verification token
        token = user.generate_verify_token()
        db.session.add(user)
        db.session.commit()

        # Send verification email
        verify_url = url_for('auth.verify_email', token=token, _external=True)
        email_status = send_verification_email(email, name, verify_url)

        if email_status == 'sent':
            flash(
                'Account created! Please check your email to verify your address before logging in.',
                'success'
            )
        else:
            # SMTP not working — still allow registration but warn
            if os.environ.get('FLASK_ENV') == 'development':
                flash(
                    f'[DEV] Account created. Verification link: {verify_url}',
                    'info'
                )
            else:
                flash(
                    'Account created! We could not send a verification email right now. '
                    'You can request one again from the login page.',
                    'warning'
                )

        return redirect(url_for('auth.login'))

    return render_template('register.html')


# ─── Email Verification ──────────────────────────────────

@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    """Handle email verification link clicks."""
    user = User.query.filter_by(email_verify_token=token).first()

    if not user:
        flash('Invalid or expired verification link.', 'danger')
        return redirect(url_for('auth.login'))

    from datetime import timezone as tz
    if user.email_verify_expiry and user.email_verify_expiry.replace(tzinfo=tz.utc) < datetime.now(tz.utc):
        flash('Verification link has expired. Please request a new one.', 'danger')
        return redirect(url_for('auth.login'))

    user.email_verified = True
    user.email_verify_token = None
    user.email_verify_expiry = None
    db.session.commit()

    flash('Email verified successfully! You can now sign in.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-verification', methods=['POST'])
@limiter.limit("3 per minute")
def resend_verification():
    """Resend the verification email."""
    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Please enter your email address.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    if not user or user.email_verified:
        # Don't reveal whether the email exists
        flash('If an unverified account exists, a verification email has been sent.', 'info')
        return redirect(url_for('auth.login'))

    token = user.generate_verify_token()
    db.session.commit()

    verify_url = url_for('auth.verify_email', token=token, _external=True)
    send_verification_email(email, user.name or user.username, verify_url)

    flash('If an unverified account exists, a verification email has been sent.', 'info')
    return redirect(url_for('auth.login'))


# ─── Login ───────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.view_tasks'))

    if request.method == 'POST':
        email_or_username = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        # Try email first, then username
        user = User.query.filter_by(email=email_or_username.lower()).first()
        if not user:
            user = User.query.filter_by(username=email_or_username).first()

        if user and user.check_password(password):
            # Block login if email is not verified
            if not user.email_verified:
                flash(
                    'Please verify your email before signing in. '
                    'Check your inbox or request a new verification link below.',
                    'warning'
                )
                return render_template('login.html', show_resend=True, resend_email=email_or_username)

            login_user(user)
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
            # Guard against open-redirect attacks — only follow same-host URLs
            if next_page and not _is_safe_redirect(next_page):
                next_page = None
            return redirect(next_page or url_for('tasks.view_tasks'))
        else:
            flash('Invalid email/username or password.', 'danger')

    return render_template('login.html')


# ─── Logout ──────────────────────────────────────────────

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


# ─── Forgot Password ────────────────────────────────────

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("3 per minute")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.view_tasks'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        if not email:
            flash('Please enter your email address.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        user = User.query.filter_by(email=email).first()
        if not user:
            # Don't reveal whether email exists (security)
            flash('If an account with that email exists, a reset code has been sent.', 'info')
            return redirect(url_for('auth.forgot_password'))

        # Generate OTP
        code = generate_otp()
        user.reset_code = code
        user.reset_code_expiry = datetime.utcnow() + timedelta(minutes=10)
        db.session.commit()

        # Try to send email
        email_status = send_reset_email(email, code, user.name or user.username)

        is_production = os.environ.get('FLASK_ENV') == 'production'

        if email_status == 'sent':
            flash('A reset code has been sent to your email.', 'success')
        elif email_status == 'failed':
            if is_production:
                # Never expose the code in production — log it server-side only
                current_app.logger.error(
                    f"[PASSWORD RESET] SMTP failed for {email}. "
                    f"Code NOT sent. Manual intervention may be needed."
                )
                flash(
                    'We could not send the reset email right now. '
                    'Please try again in a few minutes or contact support.',
                    'danger'
                )
                return redirect(url_for('auth.forgot_password'))
            else:
                # Dev mode only — safe to show the code locally
                flash(f'[DEV] SMTP failed. Reset code: {code}', 'warning')
        else:
            # SMTP not configured at all
            if is_production:
                current_app.logger.critical(
                    '[PASSWORD RESET] SMTP is not configured in production! '
                    'Set MAIL_USERNAME and MAIL_PASSWORD env vars.'
                )
                flash(
                    'Password reset is temporarily unavailable. Please contact support.',
                    'danger'
                )
                return redirect(url_for('auth.forgot_password'))
            else:
                flash(f'[DEV] SMTP not configured. Reset code: {code}', 'info')

        return redirect(url_for('auth.reset_password', email=email))

    return render_template('forgot_password.html')


# ─── Reset Password ─────────────────────────────────────

@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def reset_password():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.view_tasks'))

    email = request.args.get('email', '')

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        # Collect OTP digits
        code_digits = [request.form.get(f'code{i}', '') for i in range(1, 7)]
        code = ''.join(code_digits)
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not email or not code or not new_password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('auth.reset_password', email=email))

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('auth.reset_password', email=email))

        pw_error = validate_password(new_password)
        if pw_error:
            flash(pw_error, 'danger')
            return redirect(url_for('auth.reset_password', email=email))

        user = User.query.filter_by(email=email).first()
        if not user or user.reset_code != code:
            flash('Invalid reset code.', 'danger')
            return redirect(url_for('auth.reset_password', email=email))

        if user.reset_code_expiry and user.reset_code_expiry < datetime.utcnow():
            flash('Reset code has expired. Please request a new one.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        # Update password
        user.set_password(new_password)
        user.reset_code = None
        user.reset_code_expiry = None
        db.session.commit()

        flash('Password reset successful! Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', email=email)


# ─── Profile Page ────────────────────────────────────────
@auth_bp.route('/profile', methods=['GET'])
@login_required
def profile():
    today = datetime.now().date()
    total_tasks = len(current_user.tasks)
    completed_tasks = sum(1 for t in current_user.tasks if t.status == 'Completed')
    orgs_joined = len(current_user.org_memberships)
    
    # Calculate tasks due today (not completed)
    due_today = sum(1 for t in current_user.tasks if t.deadline == today and t.status != 'Completed')
    
    return render_template('profile.html', 
                           total_tasks=total_tasks, 
                           completed_tasks=completed_tasks, 
                           orgs_joined=orgs_joined,
                           due_today=due_today)

# ─── Profile Update ──────────────────────────────────────

@auth_bp.route('/profile_update', methods=['POST'])
@login_required
def profile_update():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    # Update basic info
    if name:
        current_user.name = name
        
    remove_picture = request.form.get('remove_picture') == 'true'
    
    if remove_picture:
        if current_user.profile_picture and current_user.profile_picture != 'default.png':
            old_file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', current_user.profile_picture)
            if os.path.exists(old_file_path):
                os.remove(old_file_path)
        current_user.profile_picture = 'default.png'
    else:
        file = request.files.get('profile_picture')
        if file and file.filename != '':
            # ── Validate file size ────────────────────────────────────────
            file.seek(0, 2)  # seek to end
            file_size = file.tell()
            file.seek(0)
            if file_size > MAX_PROFILE_SIZE:
                flash('Profile picture must be 5 MB or smaller.', 'danger')
                return redirect(request.referrer or url_for('tasks.view_tasks'))

            # ── Validate extension + actual MIME content ──────────────────
            upload_error = _validate_image_upload(file)
            if upload_error:
                flash(upload_error, 'danger')
                return redirect(request.referrer or url_for('tasks.view_tasks'))

            # Delete old profile picture if it exists
            if current_user.profile_picture and current_user.profile_picture != 'default.png':
                old_file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', current_user.profile_picture)
                if os.path.exists(old_file_path):
                    os.remove(old_file_path)

            filename = secure_filename(file.filename)
            # Create a collision-proof unique filename
            ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
            unique_filename = f"user_{current_user.id}_{secrets.token_hex(8)}.{ext}"

            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
            os.makedirs(upload_folder, exist_ok=True)

            file_path = os.path.join(upload_folder, unique_filename)
            file.save(file_path)
            current_user.profile_picture = unique_filename
    
    if email and email != current_user.email:
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash('Email already in use.', 'danger')
            return redirect(request.referrer or url_for('tasks.view_tasks'))
        current_user.email = email

    # Password update logic
    if current_password or new_password or confirm_password:
        if not current_user.check_password(current_password):
            flash('Incorrect current password.', 'danger')
            return redirect(request.referrer or url_for('tasks.view_tasks'))
        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return redirect(request.referrer or url_for('tasks.view_tasks'))
        pw_error = validate_password(new_password)
        if pw_error:
            flash(pw_error, 'danger')
            return redirect(request.referrer or url_for('tasks.view_tasks'))
        
        current_user.set_password(new_password)
        flash('Profile and password updated successfully.', 'success')
    else:
        flash('Profile updated successfully.', 'success')

    db.session.commit()
    return redirect(request.referrer or url_for('tasks.view_tasks'))


# ─── Legal Pages ─────────────────────────────────────────

@auth_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')


@auth_bp.route('/terms')
def terms():
    return render_template('terms.html')
