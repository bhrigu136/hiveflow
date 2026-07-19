# HiveFlow 🐝

A task app I started for myself, then kept adding to until it could handle teams too.

🔗 **Live demo:** [hiveflow-nadp.onrender.com](https://hiveflow-nadp.onrender.com)

It started simple. I just wanted a clean place to write down what I had to do that day, set a deadline, and have it show up in my Google Calendar so I'd actually remember. Over time it grew. Friends said it'd be useful for group projects, so I added organizations, Kanban boards, comments, and notifications. Then meetings, a team wiki, file attachments, and AI-generated meeting notes. You can still use it as a private to-do list and ignore everything else, or invite people in and run a project with them.

> **Heads up:** the demo runs on Render's free tier, so the first request after a quiet period takes about 30 seconds while the server wakes up. After that it's quick.

---

## ⚠️ Known issue: fresh installs

**`flask db upgrade` does not currently work on a brand-new database.** The migration chain is missing `CREATE TABLE` statements for nine core tables, so the first migration fails against an empty database.

If you're setting up locally right now, see [Setting up locally](#setting-up-locally) for the workaround. A proper fix is the top item on the [roadmap](docs/internal/REFACTORING_ROADMAP.md).

> **TODO:** Remove this section once the schema baseline is repaired (roadmap task E1).

---

## What's in it

### For yourself

- **Accounts.** Sign in with email or username. Passwords are hashed with Werkzeug (scrypt). Forgot yours? You'll get a 6-digit code by email that's good for 10 minutes.
- **Profile page.** Upload a picture, change your name or email, swap your password (you have to type the old one first). A small dashboard at the top shows how many tasks you have, how many you've finished, what's due today, and how many teams you're in — plus a contribution heatmap of the last year.
- **Adding tasks.** One bar at the top of the tasks page. Type the title, tab into priority/date/time if you want, hit enter.
- **Status.** Every task cycles Pending → Working → Completed. One click on the arrow advances it.
- **Filtering.** Search box, status dropdown, priority dropdown, day-by-day arrows, a "Today" button, a date picker, and "Show All".
- **CSV export.** Last 7, 15, 30 days, all tasks, or a custom date range.
- **Google Calendar (optional).** Connect your Google account and any task with a deadline becomes a calendar event with email and popup reminders. Edit the task and the event updates; delete it and the event goes away.
- **Themes.** Light, dark, or follow your system setting.
- **Device security.** A "Your devices" page showing every browser signed into your account — where from, what device, when it was last active — and a button to sign any of them out remotely. You get an email when a new device signs in.

### For teams

- **Organizations.** Create one, share the invite code, people join. You can be in more than one.
- **Projects with a Kanban board.** Pending, In Progress, Completed — each column with its own accent colour and an empty state.
- **Assigning work.** Pick a member, assign a task. They can move it through the columns; admins handle edits and deletes.
- **Discussions.** Threads at the project level, plus comments on individual tasks. Updates arrive live over WebSockets when Pusher is configured, and fall back to polling when it isn't.
- **Notifications.** Bell icon with an unread count. Joining a team, being assigned a task, or getting a reply all fire one off.
- **File attachments.** Drag files into discussions or docs. They upload straight to Supabase Storage — the file bytes never pass through the app server.
- **Analytics.** Per-organization and per-project dashboards: status breakdown, overdue counts, an eight-week velocity chart, and per-member completion rates. Exportable as CSV.

### Meetings

- **Shared calendar.** Book a meeting with teammates, see everyone's meetings and task deadlines in one month/week/day view.
- **Video rooms.** Each meeting gets a private Jitsi room. No separate account needed.
- **Google Calendar sync.** Each attendee gets their own calendar event, created and removed with the booking.
- **AI meeting notes.** During a call, each participant's browser transcribes their own microphone locally (Web Speech API) and posts finalized snippets to the server, which stitches them into one speaker-labelled transcript. Afterwards you get a summary, a list of decisions, and extracted action items — and any action item can be turned into a real task with one click.
  - Summarization runs **fully offline by default** using a built-in extractive engine. No API key, no cost, no data leaving the server.
  - If you'd rather use an LLM, point `LLM_BASE_URL` at any OpenAI-compatible endpoint (Ollama locally, Groq, whatever) and set `SUMMARIZER_ENGINE=llm`.

### Team docs

- **A nested wiki.** Markdown pages that nest into a tree, per organization. Written in a rich editor, stored as Markdown, rendered to sanitized HTML on save.
- **Revision history.** Every save snapshots the previous version; the last 50 are kept.
- **Search.** Real full-text search on Postgres, with a simpler substring fallback on SQLite.

### Growth plans

- **A personal tracker.** Build a multi-week plan with daily logs, checkboxes, custom metrics, weekly targets, and goals. Track streaks and completion percentages.
- **Templates.** Ships with a 90-day career-prep template (DSA/SQL topics, job applications, interview records, a skills matrix) plus a blank plan.

> **Known limitation:** the blank plan is currently much thinner than the career one — it only enables the weekly and goals sections. Making plans fully user-definable for any kind of growth is planned work, not a finished feature. See [roadmap task C5](docs/internal/REFACTORING_ROADMAP.md).

---

## What it's built with

| Layer | Tool |
|---|---|
| Backend | Flask 3.1 |
| Database | SQLAlchemy 2.0 — SQLite locally, PostgreSQL in production |
| Migrations | Flask-Migrate (Alembic) |
| Auth | Flask-Login + Werkzeug password hashing |
| CSRF | Flask-WTF (`CSRFProtect` — no form classes; forms are hand-written HTML) |
| Rate limiting | Flask-Limiter |
| Real-time | Pusher (hosted WebSockets) |
| File storage | Supabase Storage, via presigned direct upload |
| Email | **Brevo HTTP API** — not SMTP. Most PaaS hosts block outbound SMTP, so mail goes over HTTPS |
| Google | google-auth, google-api-python-client, google-auth-oauthlib |
| Video | Jitsi Meet (embedded iframe) |
| Markdown | `markdown` for rendering, `nh3` for sanitization |
| Errors | Sentry (optional) |
| Frontend | Plain JavaScript + Alpine.js for local state. Lucide icons, Manrope font (Inter on auth pages), hand-written CSS |
| Hosting | Gunicorn behind a Procfile, on Render |

No frontend framework and no build step. I wanted to keep the page weight low and didn't need React for what this does.

---

## How the files are laid out

```
Flask-ToDo_App/
├── app/
│   ├── __init__.py             # App factory. Config, extensions, hooks, blueprints.
│   ├── extensions.py           # SQLAlchemy, LoginManager, CSRF, Migrate, Limiter, Pusher.
│   ├── models.py               # 17 models: User, Task, Project, Organization, OrgMember,
│   │                           # Discussion, DiscussionComment, TaskComment, Meeting,
│   │                           # MeetingAttendee, TranscriptSegment, Notification,
│   │                           # LoginSession, ActivityLog, FileAttachment,
│   │                           # Document, DocumentRevision.
│   ├── tracker_models.py       # 6 growth-plan models.
│   ├── utils.py                # create_notification() helper.
│   ├── security_utils.py       # Device sessions, IP/UA parsing, activity logging.
│   ├── docs_render.py          # Markdown → sanitized HTML. The XSS trust boundary.
│   ├── google_calendar.py      # Per-attendee meeting calendar events.
│   ├── routes/                 # 13 blueprints
│   │   ├── auth.py             # Login, register, password reset, profile, devices.
│   │   ├── tasks.py            # Personal + project tasks. CRUD, toggle, CSV export.
│   │   ├── google.py           # OAuth connect, callback, disconnect.
│   │   ├── orgs.py             # Create/join orgs, dashboard, analytics.
│   │   ├── projects.py         # Projects, Kanban board, analytics.
│   │   ├── discussions.py      # Threads, task comments, polling APIs.
│   │   ├── notifications.py    # Read / read-all.
│   │   ├── files.py            # Presigned upload + attachment registration.
│   │   ├── meetings.py         # Jitsi room entry.
│   │   ├── calendar.py         # Calendar view, booking, cancel.
│   │   ├── meeting_intel.py    # Transcripts, summarization, action items.
│   │   ├── docs.py             # Team wiki: tree, editor, revisions, search.
│   │   └── tracker.py          # Growth plans.
│   ├── services/analytics.py   # Cached analytics aggregates.
│   ├── summarizer/             # Pluggable meeting summarization.
│   │   ├── base.py             # Abstract engine interface.
│   │   ├── extractive.py       # Offline default. Pure stdlib, no API key.
│   │   ├── llm.py              # Optional OpenAI-compatible HTTP client.
│   │   └── common.py           # Shared transcript/name/date parsing.
│   ├── templates/              # 46 Jinja templates
│   │   ├── base.html           # The shell most pages extend.
│   │   ├── auth_base.html      # Split-screen shell for login/register/reset.
│   │   ├── components/ui.html  # Reusable macros (buttons, cards, modals…).
│   │   ├── tasks.html · profile.html · privacy.html · terms.html
│   │   ├── orgs/ · projects/ · discussions/ · calendar/
│   │   ├── docs/ · meeting_intel/ · security/ · tracker/
│   │   └── errors/             # 404 and 500.
│   └── static/
│       ├── css/tokens.css      # Design tokens (colours, spacing, radii).
│       ├── css/components.css  # Component layer.
│       ├── css/style.css       # The main stylesheet.
│       ├── css/authx.css       # The split-screen auth layout.
│       ├── css/tracker.css · calendar.css · docs.css
│       ├── js/script.js        # Flash dismiss, confirm/toast helpers, local time.
│       ├── js/meeting_intel.js # Web Speech capture during meetings.
│       └── uploads/profiles/   # Local avatar fallback when Supabase is unset.
├── migrations/                 # Alembic migration files.
├── docs/                       # Internal notes and engineering docs (gitignored).
├── Procfile                    # Tells Render how to start the app.
├── requirements.txt            # Pinned dependencies.
├── .env.example                # Template for your env file.
└── run.py                      # Entry point.
```

> **Note:** `app/static/css/auth.css` still exists but is no longer used — `authx.css` replaced it. It's queued for deletion.

---

## Setting up locally

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

```bash
cp .env.example .env
```

At minimum you need:

```
SECRET_KEY=any-long-random-string
```

Everything else is optional — the app degrades gracefully without it. No Pusher means discussions fall back to polling. No Supabase means profile pictures save locally. No Brevo means verification codes get flashed on screen instead of emailed, which is fine for local development.

### 5. Create the database

⚠️ **`flask db upgrade` will fail on an empty database** — see [Known issue](#️-known-issue-fresh-installs).

Until that's fixed, create the schema directly from the models:

```bash
python -c "from app import create_app; from app.extensions import db; \
app = create_app(); app.app_context().push(); db.create_all()"
```

Then tell Alembic the database is current so future migrations behave:

```bash
flask db stamp head
```

> **TODO:** Replace both steps with a plain `flask db upgrade` once roadmap task E1 lands.

### 6. Start it

```bash
python run.py
```

Open `http://127.0.0.1:5000`.

By default this creates `todo.db` in the project directory. Set `FLASK_ENV=development` in your `.env` if you want auto-reload — it defaults to production so a missing variable can never accidentally enable the debugger.

---

## Putting it on Render

The live demo runs at [hiveflow-nadp.onrender.com](https://hiveflow-nadp.onrender.com). For your own copy:

1. Spin up a PostgreSQL database on your platform.
2. Copy every variable from your `.env` into the platform's environment settings, and add `DATABASE_URL` pointing at that Postgres.
3. Set `FLASK_ENV=production`. **This matters** — without it, some development-only behaviour stays switched on, including reset codes being shown on screen.
4. Push. The platform reads `requirements.txt` and starts the app from the `Procfile` with Gunicorn.
5. Create the schema — same caveat as local setup. There is no automated release phase, so this is a manual step for now.

The app picks SQLite or Postgres automatically based on whether `DATABASE_URL` is set.

> **Easy to forget:** update your Google OAuth redirect URI to the production domain in Google Cloud Console, or the connect flow breaks.

**Free-tier caveats worth knowing:**
- The service spins down when idle, so the first request takes ~30 seconds.
- The filesystem is ephemeral. Anything written to `app/static/uploads/` is **lost on every deploy and restart** — so configure Supabase in production if you want profile pictures to survive.

---

## Environment variables

### Required

| Variable | What it does |
|---|---|
| `SECRET_KEY` | Signs sessions and CSRF tokens. **The app refuses to start in production without it.** |

### Database

| Variable | What it does |
|---|---|
| `DATABASE_URL` | Postgres connection string. Falls back to local SQLite (`todo.db`) when unset. `postgres://` URLs are rewritten to `postgresql://` automatically |

### Environment

| Variable | What it does |
|---|---|
| `FLASK_ENV` | `production` or `development`. **Defaults to `production`.** Set to `development` for auto-reload |

### Email — Brevo (optional)

| Variable | What it does |
|---|---|
| `BREVO_API_KEY` | Brevo API key. Free tier is 300 emails/day. Without it, codes are flashed on screen |
| `MAIL_SENDER` | Your verified sender address |

> **Note:** older log messages in the code mention `MAIL_USERNAME` and `MAIL_PASSWORD`. Those are stale — the app does not read them. Use the two variables above.

### Google Calendar (optional)

| Variable | What it does |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret |

Create credentials at [Google Cloud Console](https://console.cloud.google.com) as an OAuth 2.0 Web Application, with `http://127.0.0.1:5000/google/callback` as an authorized redirect URI locally.

### Real-time — Pusher (optional)

| Variable | What it does |
|---|---|
| `PUSHER_APP_ID` · `PUSHER_KEY` · `PUSHER_SECRET` | Credentials from [pusher.com](https://pusher.com) |
| `PUSHER_CLUSTER` | Defaults to `ap2` |

Without these, discussions fall back to polling.

### File storage — Supabase (optional)

| Variable | What it does |
|---|---|
| `SUPABASE_URL` · `SUPABASE_KEY` | Project URL and key |
| `SUPABASE_STORAGE_BUCKET` | Bucket name. Defaults to `project-assets` |

> **Note:** profile-picture uploads currently default to a *different* bucket (`HiveFlow-assets`) than file attachments. That's a known inconsistency, not intentional.

### Meeting summarization (optional)

| Variable | What it does |
|---|---|
| `SUMMARIZER_ENGINE` | `extractive` (default, offline, free) or `llm` |
| `LLM_BASE_URL` | OpenAI-compatible endpoint, e.g. `http://localhost:11434/v1` for Ollama |
| `LLM_MODEL` | Model name, e.g. `llama3.2:3b` |
| `LLM_API_KEY` | Optional — not needed for local Ollama |

If the LLM engine isn't configured, it falls back to the extractive one automatically.

### Monitoring (optional)

| Variable | What it does |
|---|---|
| `SENTRY_DSN` | Enables Sentry error tracking and 10% performance sampling. Silently skipped when unset |

---

## Security

What's in place:

- Passwords hashed with Werkzeug (scrypt). Plaintext never touches the database.
- CSRF protection on every state-changing request, application-wide, with no exemptions.
- Session cookies are `Secure`, `HttpOnly`, and `SameSite=Lax`, with a 7-day lifetime.
- Security headers on every response: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and HSTS outside debug.
- Uploads are capped at 5 MB and validated by both file extension **and** magic bytes — not extension alone.
- Wiki HTML is sanitized with `nh3` against an explicit allowlist of tags, attributes, and URL schemes.
- Device sessions can be revoked remotely, and revocation takes effect on that device's very next request.
- Reset codes expire after 10 minutes. Email verification tokens are 256-bit and expire after 24 hours.
- Rate limiting on registration, login, password reset, and org joining.
- `.env` is gitignored. Don't commit it.

Being honest about what isn't:

- **Google OAuth tokens are stored unencrypted** in the database.
- There's **no Content-Security-Policy** yet — the amount of inline JavaScript makes a useful one impractical until that's extracted.
- Rate limits are keyed on the proxy's IP rather than the client's, so behind Render they're effectively shared across all users.
- **There are no automated tests.** Nothing verifies any of the above on an ongoing basis.

All of this is tracked with severity ratings and fixes in [the engineering audit](docs/internal/ENGINEERING_AUDIT.md).

> **TODO:** Add a `SECURITY.md` with a vulnerability disclosure process (planned as part of the documentation set).

---

## Project documentation

Deeper engineering documentation lives in `docs/internal/` (gitignored — local only):

| Document | What's in it |
|---|---|
| `REPOSITORY_ANALYSIS.md` | Complete factual map of the codebase |
| `ENGINEERING_AUDIT.md` | 77 findings with severity, effort, and risk |
| `REFACTORING_ROADMAP.md` | Prioritized plan across ten phases |

> **TODO:** Decide whether these should be published with the repository or stay internal.

---

## Contributing

> **TODO:** Write `CONTRIBUTING.md`. It should cover branch naming, commit conventions, and the local setup path — which needs the schema fix (roadmap task E1) before it can be written honestly.

---

## License

> **TODO:** The previous README stated MIT, but **no `LICENSE` file exists in the repository**. Either add one or remove the claim. Until a license file is present, no license is actually granted.

---

<p align="center">
  Built with ☕ and Flask &nbsp;|&nbsp; <strong>HiveFlow</strong>
</p>
