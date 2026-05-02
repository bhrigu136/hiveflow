# HiveFlow — Complete Project Walkthrough

## 1. What the Project Is (One-Line Pitch)

**HiveFlow is a Flask-based team collaboration and task management web app.** It started as a personal to-do list and grew into a full project-management tool with organizations, projects, Kanban boards, discussions (chat-like threads), notifications, and Google Calendar sync.

---

## 2. Tech Stack (What to Say to Interviewer)

| Layer | Tech |
|---|---|
| **Backend** | Flask 3.x (Python) |
| **Database** | SQLAlchemy ORM with SQLite (dev) / PostgreSQL (prod) |
| **Migrations** | Flask-Migrate (Alembic) |
| **Auth** | Flask-Login + Werkzeug password hashing |
| **Security** | Flask-WTF (CSRF), Flask-Limiter (rate limiting) |
| **Templating** | Jinja2 (server-side rendering) |
| **Frontend** | Plain HTML + CSS + vanilla JavaScript (no React) |
| **External APIs** | Google Calendar API (OAuth2), Gmail SMTP for OTP |
| **Deployment** | Gunicorn + Procfile (Render/Heroku ready) |

---

## 3. Architecture — How the App is Wired

The app uses the **App Factory pattern** in `app/__init__.py`:

```
create_app() →
    1. Loads SECRET_KEY (env-based)
    2. Configures DB (SQLite local / PostgreSQL prod)
    3. Initializes extensions (db, login_manager, csrf, migrate, limiter)
    4. Registers Blueprints (one per feature)
```

**Blueprints** (modular route groups) — each lives in `app/routes/`:

- `auth_bp` — login, register, password reset
- `tasks_bp` — personal tasks
- `google_bp` — Google Calendar OAuth
- `orgs_bp` — organizations (teams)
- `projects_bp` — projects + Kanban board
- `discussions_bp` — discussions + comments (the "chat" part)
- `notifications_bp` — notification bell

---

## 4. Database Models (`app/models.py`)

Eight tables connected via foreign keys:

```
User ──┬──► OrgMember ──► Organization ──► Project ──► Task
       │                                      │
       │                                      ├──► Discussion ──► DiscussionComment
       │                                      │
       │                                      └──► ActivityLog
       │
       └──► Notification
```

| Model | Purpose |
|---|---|
| `User` | Account, password hash, Google OAuth tokens, OTP reset code |
| `Organization` | A team — has a unique `invite_code` |
| `OrgMember` | Joins User ↔ Organization with a role (Admin/Member) |
| `Project` | Belongs to an Organization |
| `Task` | Personal (no project_id) OR project task (with assignee, status) |
| `Discussion` | A "chat thread" attached to a project — has title + content |
| `DiscussionComment` | A reply inside a discussion |
| `TaskComment` | Comments on individual tasks |
| `ActivityLog` | Audit feed: "Alice moved task X to Completed" |
| `Notification` | Per-user inbox: message + link + is_read flag |

---

## 5. The Discussion Chat — How It Works (DEEP DIVE)

This is the most important part for the interviewer. The discussion system is **NOT real-time WebSocket chat** — it's a **traditional request–response forum-style** system. Here's how a message gets transmitted from user A to user B.

### 5a. The Two Templates Involved

- `app/templates/discussions/list.html` — shows all discussion threads in a project
- `app/templates/discussions/view.html` — shows one discussion + its comments + a comment form

### 5b. Data Model for the Chat

```
Project (1) ──► (many) Discussion (1) ──► (many) DiscussionComment
```

Each `Discussion` is like a **chat room** with a title and an opening post.
Each `DiscussionComment` is like a **message** inside that room.

### 5c. The Full Message-Transmission Flow

**Step 1 — User opens the discussions page**

- URL: `/projects/<project_id>/discussions`
- Backend route: `list_discussions()` in `discussions.py`
- It first calls `check_project_access()` — verifies the user is a member of the project's organization (security check)
- Queries: `Discussion.query.filter_by(project_id=...).order_by(created_at.desc()).all()`
- Renders `list.html` showing all discussions as cards with comment counts

**Step 2 — User creates a new discussion (starts a chat thread)**

- Clicks "New Discussion" → opens a modal with a `<form method="POST">`
- Form has CSRF token + title + content fields
- Form submits to `/projects/<project_id>/discussions/create`
- Backend route `create_discussion()` does:
  1. Access check (must be org member)
  2. Validates title and content are non-empty
  3. Creates a `Discussion` row with `created_by=current_user.id`
  4. Calls `log_activity(...)` → adds an entry to `ActivityLog`
  5. **Loops through all org members** and calls `create_notification()` for everyone except the author
  6. `db.session.commit()` saves everything in ONE transaction
  7. Redirects to the discussion view page

**Step 3 — User views the discussion (opens the chat room)**

- URL: `/discussions/<discussion_id>`
- Route: `view_discussion()`
- Loads the discussion + all comments ordered by `created_at ASC` (oldest first, like a chat)
- Renders `view.html` which shows:
  - The original post (creator avatar, name, time, content)
  - All comments listed below
  - A textarea + "Post Comment" button at the bottom

**Step 4 — User posts a comment (sends a message)**

This is the core "send message" flow:

```
HTML form → POST /discussions/<id>/comment
       ↓
Flask receives request with CSRF token + content
       ↓
1. Verify project access
2. Strip + validate content (not empty)
3. Build a DiscussionComment(content, discussion_id, created_by=current_user.id)
4. db.session.add(comment)
5. log_activity("commented on discussion 'X'")
6. Loop org members → create_notification for everyone except sender
7. db.session.commit() — atomic write
8. redirect → view_discussion(id) — page reloads showing new comment
```

### 5d. How Messages Are "Transmitted" (Important for Interviewer)

> **There is no WebSocket, no Socket.IO, no polling.** Messages are transmitted via **synchronous HTTP POST requests** and the page **fully reloads** after each post (Post-Redirect-Get pattern).

When User B wants to see User A's new comment, they either:

1. Refresh the page, OR
2. Click the notification bell — they got a notification from `create_notification()` linking back to the discussion

### 5e. CSRF Protection on Every Message

Every form has `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. Flask-WTF's `CSRFProtect` extension validates this on every POST — preventing attackers from forcing a logged-in user to post messages from another site.

### 5f. Access Control

`check_project_access()` runs on EVERY discussion route. It checks the `OrgMember` table to verify the current user is in the project's organization. Without this, anyone could read any discussion by guessing IDs.

---

## 6. Notification System — How Users Get Alerted

Defined in `models.py` (`Notification` model) and `utils.py` (`create_notification` helper).

**Flow:**

1. When something happens (task assigned, comment posted, member joined), code calls `create_notification(user_id, message, link)`
2. This adds a `Notification` row (without committing — caller commits)
3. The bell icon in `base.html` reads `current_user.notifications.filter_by(is_read=False).count()` and shows the unread count badge
4. Clicking the bell opens a dropdown with the 10 most recent notifications
5. Clicking a notification hits `/notifications/read/<id>` which marks it read and **redirects to the linked page** (e.g., the discussion)
6. "Mark all read" hits `/notifications/read-all` and bulk-updates `is_read=True`

The bell is **rendered server-side on every page load** — so notifications appear after the next page navigation, not in real time.

---

## 7. Other Major Features (Quick Tour)

### Authentication (`auth.py`)

- Register/login with email or username
- Passwords hashed with Werkzeug (`generate_password_hash` / `check_password_hash`)
- **Forgot password = OTP flow**: generates 6-digit code, stores it with 10-min expiry, emails it via Gmail SMTP
- Rate-limited: login (10/min), register (5/min), forgot password (3/min)

### Personal Tasks (`tasks.py`)

- Add/edit/delete/toggle status (Pending → Working → Completed)
- Filter by status, priority, search query, deadline date
- Export to CSV (last 7/15/30 days or custom range) — uses Python's `csv` module + `io.StringIO`
- Google Calendar sync: creates/updates/deletes Calendar events when tasks have deadlines

### Organizations & Projects

- User creates an org → gets a unique `invite_code` (`secrets.token_urlsafe(6)`)
- Org slug auto-generated from name (regex strips non-alphanumeric)
- Other users join with the invite code → become Members; creator is Admin
- Inside an org → multiple Projects → each has a Kanban board (3 columns: Pending / Working / Completed)
- Tasks can be assigned to specific members
- **Authorization helper** `_authorize_task()` enforces:
  - Personal tasks: only owner can edit
  - Project tasks: Admins can do anything; Members can only toggle status of their assigned tasks

### Activity Feed (`_activity_feed.html`)

- `ActivityLog` table stores every meaningful event
- Helper `log_activity()` is called from every route that mutates data
- Displayed on org dashboard and project dashboard

### Google Calendar Integration

- OAuth2 flow stores `google_access_token` + `google_refresh_token` per user
- When a task with a deadline is created → builds a Google Calendar event with email + popup reminders
- Wrapped in try/except — calendar failure never breaks the app

---

## 8. Security Highlights (Big Interview Points)

1. **Password hashing** — never stored in plain text (Werkzeug)
2. **CSRF tokens** on every form (Flask-WTF)
3. **Rate limiting** on auth endpoints (Flask-Limiter)
4. **Session-based login** with Flask-Login
5. **Authorization checks on every route** — `check_project_access()`, `_authorize_task()`
6. **OTP expiry** for password reset (10 minutes)
7. **No information leakage** — "If an account exists, code was sent" message instead of confirming email existence
8. **SECRET_KEY required in production** — app refuses to start without it
9. **PostgreSQL connection pooling** with `pool_pre_ping` to handle dropped connections

---

## 9. Quick One-Sentence Summaries (Cheat Sheet for Interview)

- **"What does it do?"** → A team collaboration platform where users form organizations, manage projects on Kanban boards, discuss in threads, and assign tasks.
- **"How does the chat work?"** → It's a forum-style discussion system — users POST comments via HTML forms, the server saves them to the `DiscussionComment` table, and the page reloads to show new messages. Other users get notifications via the bell icon.
- **"How are messages transmitted?"** → Synchronous HTTP POST → server validates CSRF + access → inserts into DB → creates notifications for all org members → redirects with `Post-Redirect-Get` to refresh the page.
- **"Why no WebSockets?"** → It's a project-management tool, not a real-time chat — discussions are like GitHub issue threads, not Slack DMs. This keeps the architecture simple and stateless.
- **"Database design?"** → Normalized schema with foreign keys; cascading deletes; indexes on FK columns and timestamps for fast queries.

---

That's the whole picture. If the interviewer drills into any one piece, you can confidently explain the request flow, the SQLAlchemy query, the security check, or the rendered template.
