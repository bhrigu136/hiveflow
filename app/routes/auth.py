import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.extensions import db, limiter

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ─── Helpers ─────────────────────────────────────────────

def generate_otp():
    """Generate a 6-digit OTP code."""
    return str(random.randint(100000, 999999))


def send_reset_email(to_email, code, username):
    """Send password reset code via SMTP (Gmail).

    Returns 'sent' on success, 'unconfigured' if no SMTP creds, 'failed' on error.
    """
    smtp_email = os.environ.get('MAIL_USERNAME')
    smtp_password = os.environ.get('MAIL_PASSWORD')

    if not smtp_email or not smtp_password:
        return 'unconfigured'

    # Gmail App Passwords are shown with spaces ("abcd efgh ijkl mnop") —
    # strip them so a copy-pasted value still works.
    smtp_password = smtp_password.replace(' ', '')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Personal planner — Password Reset Code'
    msg['From'] = smtp_email
    msg['To'] = to_email

    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <h2 style="color: #1a1a2e; margin: 0;">Personal planner</h2>
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

    msg.attach(MIMEText(html, 'html'))

    try:
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ctx, timeout=15) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        return 'sent'
    except Exception as e:
        import traceback
        print(f"[MAIL ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        return 'failed'


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

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
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
        db.session.add(user)
        db.session.commit()

        flash('Account created successfully! Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


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
            login_user(user)
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
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

        if email_status == 'sent':
            flash('A reset code has been sent to your email.', 'success')
        elif email_status == 'failed':
            # SMTP is configured but sending raised — show on screen so the
            # user isn't blocked, but make it obvious something went wrong.
            flash(f'Email failed to send (check server logs). Reset code: {code}', 'warning')
        else:
            # No SMTP configured — pure dev mode
            flash(f'Reset code (dev mode): {code}', 'info')

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

        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
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
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'danger')
            return redirect(request.referrer or url_for('tasks.view_tasks'))
        
        current_user.set_password(new_password)
        flash('Profile and password updated successfully.', 'success')
    else:
        flash('Profile updated successfully.', 'success')

    db.session.commit()
    return redirect(request.referrer or url_for('tasks.view_tasks'))
