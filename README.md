# HiveFlow 🐝

> Personal task management, built for the upgrade to team collaboration.

A full-stack web app built with Flask — manage your daily tasks with a clean dark UI, set priorities and deadlines, search/filter, export to CSV, and optionally sync everything to Google Calendar. Currently a personal planner, actively being upgraded into a full group project management tool for student teams.

---

## What it does

At its core, it's a to-do app — but with enough features to actually be useful day-to-day:

- **Login / Register** — Each user has their own account with password hashing. You can also log in with your email or username. Forgot your password? There's an OTP-based reset flow that sends a 6-digit code to your email.
- **Task Management** — Add tasks with a title, priority (Low / Medium / High), a deadline date, and an optional time slot. You can edit tasks through a modal popup, or delete them one by one (or wipe everything with "Clear All").
- **Status Tracking** — Every task has a status: `Pending → Working → Completed`. You can cycle through these directly from the task list with a single click — no separate edit required.
- **Search & Filters** — There's a live search bar and dropdowns to filter tasks by status or priority. These work together so you can narrow things down quickly.
- **Export to CSV** — You can export your entire task list (or just the last 7 / 15 / 30 days, or a custom date range) as a `.csv` file. Handy for reviewing or sharing.
- **Google Calendar Sync** — If you connect your Google account via OAuth, any task you create with a deadline will automatically appear as a calendar event. Editing or deleting the task updates/removes the calendar event too.
- **Profile Management** — There's a side panel (slides in from the right) where you can update your name, email, and change your password. Current password is verified before any changes go through.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Backend | Flask 3.x (Python) |
| Database | SQLAlchemy + SQLite (local) / PostgreSQL (production) |
| Auth | Flask-Login + Werkzeug password hashing |
| Forms / CSRF | Flask-WTF |
| Google Integration | google-auth, google-api-python-client, google-auth-oauthlib |
| Email (OTP) | Python smtplib + Gmail SMTP |
| Deployment | Gunicorn + Procfile |

---

## Project Structure

```
Flask-ToDo_App/
├── app/
│   ├── __init__.py        # App factory — creates and wires everything together
│   ├── extensions.py      # SQLAlchemy, LoginManager, and CSRF instances
│   ├── models.py          # User and Task database models
│   ├── routes/
│   │   ├── auth.py        # Login, register, forgot/reset password, profile update
│   │   ├── tasks.py       # Add, edit, delete, toggle, clear, export CSV
│   │   └── google.py      # Google OAuth connect/disconnect/callback
│   ├── templates/         # Jinja2 HTML templates
│   └── static/            # CSS, JS, and any static assets
├── instance/              # SQLite database lives here (auto-created, not committed)
├── Procfile               # Gunicorn startup command for deployment
├── requirements.txt       # All Python dependencies, pinned
├── .env.example           # Template showing what env variables you need
└── run.py                 # Entry point — just runs the app
```

---

## Getting it Running Locally

### 1. Clone the repo

```bash
git clone <your-repo-url>
cd Flask-ToDo_App
```

### 2. Set up a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up your `.env` file

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Open `.env` and set:

```
SECRET_KEY=some-long-random-string-here
GOOGLE_CLIENT_ID=your-client-id-from-google-cloud
GOOGLE_CLIENT_SECRET=your-client-secret-from-google-cloud
```

For `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, you'll need to create an OAuth 2.0 Web Application credential in [Google Cloud Console](https://console.cloud.google.com). Make sure to add `http://127.0.0.1:5000/google/callback` as an authorized redirect URI.

If you don't want Google Calendar sync at all, you can skip the Google credentials — everything else works fine without them.

For the email OTP (forgot password), add these two as well if you want it to actually send emails:

```
MAIL_USERNAME=your-gmail@gmail.com
MAIL_PASSWORD=your-gmail-app-password
```

Without these, the OTP code gets shown in a flash message instead (which is fine for local dev/testing).

### 5. Run the app

```bash
python run.py
```

Go to `http://127.0.0.1:5000` — it'll auto-create the SQLite database on first run.

---

## Roadmap — Upgrading to HiveFlow Collab

The next version is being built to support student group projects:

- **Organizations** — create or join a team/class with an invite code
- **Projects** — multiple projects inside each org with a Kanban board view
- **Task Assignment** — assign tasks to specific team members
- **Discussions** — project-level threads + per-task comments
- **Notifications** — get notified when you're assigned a task or someone comments

---

## Deploying to Production (Render / Railway / Heroku)

This app is already set up for deployment:

1. Create a PostgreSQL database on your chosen platform.
2. Add all your environment variables (from `.env`) to the platform's settings, plus `DATABASE_URL` pointing to your Postgres instance.
3. Push your code — the platform will run `pip install -r requirements.txt` and start the app using the `Procfile` (which uses Gunicorn).

The app automatically switches between SQLite (local) and PostgreSQL (production) based on the `DATABASE_URL` env variable.

> **Note:** Make sure your Google OAuth redirect URI is updated to your production domain in Google Cloud Console when deploying.

---

## Environment Variables Reference

| Variable | Required | What it's for |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing and CSRF protection |
| `GOOGLE_CLIENT_ID` | Optional | Google Calendar OAuth |
| `GOOGLE_CLIENT_SECRET` | Optional | Google Calendar OAuth |
| `MAIL_USERNAME` | Optional | Gmail address to send OTP emails from |
| `MAIL_PASSWORD` | Optional | Gmail App Password (not your regular password) |
| `DATABASE_URL` | Production only | PostgreSQL connection string |

---

## A note on security

- Passwords are hashed with Werkzeug (bcrypt-style) — plain-text passwords are never stored.
- CSRF protection is enabled on all forms via Flask-WTF.
- The `.env` file is in `.gitignore` — never commit it.
- Google OAuth tokens are stored per-user in the database (not in the session or files).
- The forgot-password OTP expires after 10 minutes.

---

## License

MIT — do whatever you want with it.

---

<p align="center">
  Built with ☕ and Flask &nbsp;|&nbsp; <strong>HiveFlow</strong>
</p>
