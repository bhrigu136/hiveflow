# HiveFlow 🐝

A task app I started for myself, then kept adding to until it could handle teams too.

🔗 **Live demo:** [hiveflow-nadp.onrender.com](https://hiveflow-nadp.onrender.com)

It started simple. I just wanted a clean place to write down what I had to do that day, set a deadline, and have it show up in my Google Calendar so I'd actually remember. Over time it grew. Friends said it'd be useful for group projects, so I added organizations, Kanban boards, comments, and notifications. You can still use it as a private to-do list and ignore everything else, or invite people in and run a project with them.

> Heads up: the demo runs on Render's free tier, so the first request after a quiet period takes about 30 seconds while the server wakes up. After that it's quick.

---

## What's in it

### For yourself

- **Accounts.** Sign in with email or username. Passwords are hashed (Werkzeug). Forgot it? You'll get a 6-digit code by email that's good for 10 minutes.
- **Profile page.** Upload a picture, change your name or email, swap your password (you have to type the old one first). There's a small dashboard at the top showing how many tasks you have, how many you've finished, what's due today, and how many teams you're in.
- **Adding tasks.** There's a single bar at the top of the tasks page. Type the title, tab into priority/date/time if you want, hit enter. That's it.
- **Status.** Every task cycles through Pending → Working → Completed. One click on the arrow advances it. No need to open an edit screen for that.
- **Greeting + stats.** When you load the page you get "Good morning, [your name]" or afternoon/evening depending on the clock, plus four cards showing total / pending / in-progress / completed with little progress bars.
- **Filtering.** Search box, status dropdown, priority dropdown. Plus arrows to walk day-by-day, a "Today" button, a date picker, and "Show All" if you want to see everything at once.
- **CSV export.** Last 7, 15, 30 days, all tasks, or pick your own date range.
- **Google Calendar (optional).** If you connect your Google account, any task with a deadline shows up as a calendar event with email and popup reminders. Edit the task and the event updates. Delete it and the event goes away.

### For teams

- **Organizations.** Create one, share the invite code, and people can join. You can be in more than one (e.g. your class and your side project).
- **Projects with a Kanban board.** Three columns: Pending, In Progress, Completed. Each column has its own colour accent and a friendly empty state when there's nothing in it.
- **Assigning work.** Pick a member, assign a task. They can move it through the columns. Admins handle edits and deletes.
- **Talking about things.** Discussion threads at the project level, plus comments attached to individual tasks.
- **Notifications.** Bell icon in the nav with an unread count. Clicking it shows recent notifications; you can mark them read one at a time or all at once. Anyone joining your team, assigning you a task, or replying to your discussion fires one off automatically.

---

## What it's built with

| Layer | Tool |
|---|---|
| Backend | Flask 3.x |
| Database | SQLAlchemy. SQLite locally, Postgres in production |
| Migrations | Flask-Migrate (Alembic under the hood) |
| Auth | Flask-Login + Werkzeug for password hashing |
| Forms / CSRF | Flask-WTF |
| Google | google-auth, google-api-python-client, google-auth-oauthlib |
| Email | smtplib + Gmail SMTP |
| Frontend | Plain JavaScript, Lucide for icons, Inter for the font, hand-written CSS |
| Hosting | Gunicorn behind a Procfile |

No frontend framework. I wanted to keep the page weight low and didn't need React for what this does.

---

## How the files are laid out

```
Flask-ToDo_App/
├── app/
│   ├── __init__.py             # App factory. Wires the extensions and blueprints.
│   ├── extensions.py           # SQLAlchemy, LoginManager, CSRF, Migrate.
│   ├── models.py               # User, Task, Project, Organization, OrgMember,
│   │                           # Discussion, DiscussionComment, TaskComment,
│   │                           # Notification.
│   ├── utils.py                # create_notification() helper.
│   ├── routes/
│   │   ├── auth.py             # Login, register, forgot/reset password, profile.
│   │   ├── tasks.py            # Personal tasks. Add/edit/delete/toggle/clear/export.
│   │   ├── google.py           # OAuth connect, callback, disconnect.
│   │   ├── orgs.py             # Create/join orgs and manage members.
│   │   ├── projects.py         # Projects, the Kanban board, assigning tasks.
│   │   ├── discussions.py      # Threads and per-task comments.
│   │   └── notifications.py    # The bell dropdown and read/unread state.
│   ├── templates/
│   │   ├── base.html           # The shell every page extends.
│   │   ├── tasks.html          # Welcome banner, stats, omnibar, task list.
│   │   ├── login / register / forgot_password / reset_password.html
│   │   ├── profile.html        # The account dashboard page.
│   │   ├── orgs/               # list, create, dashboard.
│   │   ├── projects/           # create, dashboard (Kanban), _task_card partial.
│   │   ├── discussions/        # list, view.
│   │   └── errors/             # 404 and 500 pages.
│   └── static/
│       ├── css/style.css       # The main stylesheet.
│       ├── css/auth.css        # The split-screen login/register layout.
│       ├── js/script.js        # Flash auto-dismiss, button ripple, timezone fixes.
│       └── uploads/profiles/   # Where uploaded avatars go.
├── migrations/                 # Alembic migration files.
├── instance/                   # The local SQLite file lives here. Not committed.
├── docs/                       # Random notes I've kept while building.
├── Procfile                    # Tells Render/Heroku how to start the app.
├── requirements.txt            # Pinned dependencies.
├── .env.example                # Template for your env file.
└── run.py                      # Just runs the app.
```

---

## Running it on your machine

### 1. Clone

```bash
git clone <your-repo-url>
cd Flask-ToDo_App
```

### 2. Make a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install everything

```bash
pip install -r requirements.txt
```

### 4. Set up `.env`

Copy the example over and fill it in:

```bash
cp .env.example .env
```

At minimum you need:

```
SECRET_KEY=any-long-random-string
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
```

The Google bits are only needed if you want calendar sync. To get them, head to [Google Cloud Console](https://console.cloud.google.com), create an OAuth 2.0 Web Application credential, and add `http://127.0.0.1:5000/google/callback` as an authorized redirect URI. Skip them entirely if you don't care about calendar sync. The rest of the app still works.

If you also want the forgot-password emails to actually go out, add:

```
MAIL_USERNAME=your-gmail@gmail.com
MAIL_PASSWORD=your-gmail-app-password
```

(That has to be an [App Password](https://myaccount.google.com/apppasswords), not your actual Gmail password.) If you don't set these, the OTP code just gets flashed on screen, which is fine while you're testing locally.

### 5. Run migrations

```bash
flask db upgrade
```

### 6. Start it

```bash
python run.py
```

Open `http://127.0.0.1:5000` in your browser.

---

## Putting it on Render

The live demo is hosted at [hiveflow-nadp.onrender.com](https://hiveflow-nadp.onrender.com). If you want your own copy somewhere:

1. Spin up a PostgreSQL database on whichever platform you're using.
2. Copy every variable from your `.env` into the platform's environment settings. Add a `DATABASE_URL` pointing at the Postgres you just made.
3. Push the code. The platform reads `requirements.txt`, then starts the app from the `Procfile` using Gunicorn.
4. Run `flask db upgrade` once after the first deploy so the schema is in place.

The app picks SQLite or Postgres automatically based on whether `DATABASE_URL` is set, so there's nothing to switch in the code.

> One thing that's easy to forget: update your Google OAuth redirect URI to the production domain in Google Cloud Console. Otherwise the connect flow breaks.

---

## Env variables, in one place

| Variable | Required? | What it does |
|---|---|---|
| `SECRET_KEY` | Yes | Signs sessions and CSRF tokens |
| `GOOGLE_CLIENT_ID` | Optional | For Google Calendar sync |
| `GOOGLE_CLIENT_SECRET` | Optional | For Google Calendar sync |
| `MAIL_USERNAME` | Optional | Gmail address that sends OTP emails |
| `MAIL_PASSWORD` | Optional | Gmail App Password (not your normal one) |
| `DATABASE_URL` | Production only | Postgres connection string |

---

## Security stuff

- Passwords go through Werkzeug's hashing. Plaintext never touches the database.
- Every form has CSRF protection through Flask-WTF. Every POST template includes a `csrf_token` hidden input.
- Google OAuth tokens are stored per user in the DB, not in the session or in a file on disk.
- Profile pictures are limited by file extension and saved under `app/static/uploads/profiles/`.
- The forgot-password OTP expires after 10 minutes.
- `.env` is in `.gitignore`. Don't ever commit it. Seriously.

---

## License

MIT. Use it however you want.

---

<p align="center">
  Built with ☕ and Flask &nbsp;|&nbsp; <strong>HiveFlow</strong>
</p>
