# HiveFlow — Complete Project Walkthrough (Interview-Ready)

Here is everything happening in your project, explained simply so you can defend it in an interview.

---

## 1. What the project is (one-liner pitch)

> **HiveFlow** is a Flask-based team task-management web app — like a mini Trello + Slack — where users can manage personal tasks, create organizations, invite teammates, run projects with Kanban boards, hold project discussions, comment on tasks, get real-time-like notifications, and sync deadlines to Google Calendar.

**Tech stack:** Flask 3.1, Flask-SQLAlchemy 3.1, Flask-Login, Flask-Migrate (Alembic), Flask-WTF (CSRF), Flask-Limiter (rate limiting), SQLite (dev) / PostgreSQL (prod), Google Calendar API, Jinja2 templates, vanilla JS + custom CSS, Gunicorn for deployment.

---

## 2. Application architecture — the big picture

```
run.py  →  create_app()  →  registers 7 Blueprints
                                    │
        ┌───────────┬────────┬──────┼───────┬───────────┬──────────────┐
        auth      tasks   google  orgs   projects  discussions  notifications
```

[run.py](run.py) just imports the factory `create_app()` from [app/__init__.py](app/__init__.py).

### The factory pattern — [app/__init__.py](app/__init__.py)

This is a **best-practice Flask pattern**. Instead of one giant file, the app is built inside a function:

1. Loads `.env` secrets via `python-dotenv`.
2. Reads `SECRET_KEY` (crashes in production if missing — secure).
3. Reads `DATABASE_URL` — uses **SQLite locally, PostgreSQL in production**.
4. Adds a Postgres connection pool (`pool_size=5`, `pool_recycle=300`, `pool_pre_ping=True`) — this prevents stale connections under concurrent load.
5. Initializes 5 Flask extensions: `db`, `migrate`, `login_manager`, `csrf`, `limiter` — all defined in [app/extensions.py](app/extensions.py).
6. Registers all 7 blueprints (modular routes).

> **Interview note:** Using the factory pattern + blueprints means each feature lives in its own file, and the app is easy to test (you can create multiple app instances with different configs).

---

## 3. The Database — how multi-user data stays separate

### Tables (10 models in [app/models.py](app/models.py))

| Table | Purpose |
|---|---|
| **User** | Account + password hash + Google tokens + reset OTP |
| **Task** | Personal or project task |
| **Organization** | A team / company workspace |
| **OrgMember** | Join table — links users to orgs with a role (Admin/Member) |
| **Project** | Belongs to an Organization |
| **Discussion** | A discussion thread inside a project |
| **DiscussionComment** | Reply on a discussion |
| **TaskComment** | Comment on a task card |
| **ActivityLog** | Audit trail per organization/project |
| **Notification** | Per-user notification feed |

### The "data isolation" story — how each user only sees their data

This is what the interviewer cares about. The answer is **foreign keys + filtered queries + access checks at every route**.

**Three levels of separation:**

**(A) Personal data (just yours)**
Every `Task` has a `user_id` column ([models.py:55](app/models.py#L55)). When you visit `/`, the route runs:
```python
Task.query.filter_by(user_id=current_user.id).filter(Task.project_id.is_(None))
```
([tasks.py:40](app/routes/tasks.py#L40)) — so you only ever see tasks where `user_id == your id` AND it's not part of a project. Other users' rows are in the same table but invisible because the SQL `WHERE` clause excludes them.

**(B) Team data (shared with org members)**
A user is in an org only if a row exists in `OrgMember` linking their `user_id` to an `org_id`. Every org-related route does this check first:
```python
membership = OrgMember.query.filter_by(org_id=org.id, user_id=current_user.id).first()
if not membership:
    flash('Permission denied.', 'danger'); return redirect(...)
```
([projects.py:53](app/routes/projects.py#L53), [orgs.py:114](app/routes/orgs.py#L114)).

If the row doesn't exist, you're kicked out — even if you guess the URL.

**(C) Role-based (Admin vs Member)**
[tasks.py:190](app/routes/tasks.py#L190) `_authorize_task()` is the central guard for editing/deleting/toggling tasks:
- **Personal task** → only the owner (`task.user_id == current_user.id`).
- **Project task** → must be in the org. **Admins** can edit/delete anything; regular **Members** can only **toggle status** on tasks **assigned to them**.

> **One sentence answer for the interviewer:** *"Every table that holds user data has a foreign key to `user.id`, and every route filters by `current_user.id` or verifies an `OrgMember` row before touching the data — so multi-tenant isolation happens at the SQL level on every single request."*

### How the DB itself works

- **ORM:** SQLAlchemy lets you write Python classes (`User`, `Task`) and SQLAlchemy generates the SQL.
- **Migrations:** Flask-Migrate (Alembic) tracks schema changes — `flask db migrate` creates a version file, `flask db upgrade` applies it. Files live in [migrations/](migrations/).
- **Naming convention** in [extensions.py:9-15](app/extensions.py#L9-L15) gives consistent constraint names so migrations work the same on SQLite and PostgreSQL.
- **Indexes** are added on hot columns (`user_id`, `project_id`, `org_id`, `status`, `priority`, `created_at`) to keep queries fast.
- **Cascade deletes** — when an Organization is deleted, `cascade='all, delete-orphan'` automatically removes its projects, members, and activities. Same for projects → tasks/discussions.

---

## 4. Authentication — how login works

[app/routes/auth.py](app/routes/auth.py)

1. **Register** → user submits name/email/password → password is hashed with `werkzeug.security.generate_password_hash` (PBKDF2 with salt). **Plain text passwords are never stored.** A unique username is auto-generated from the email prefix.
2. **Login** → form posts email/username + password. The view fetches the user, calls `user.check_password(password)` which uses `check_password_hash` (constant-time compare to prevent timing attacks). On success → `login_user(user)` from Flask-Login sets a signed session cookie.
3. **`@login_required`** decorator on every protected route checks for that cookie. If missing, redirect to `/auth/login`.
4. **`current_user`** — Flask-Login auto-loads the user object on every request via the `@login_manager.user_loader` in [models.py:6-8](app/models.py#L6-L8).
5. **Forgot password** → generates a 6-digit OTP, stores it with a 10-minute expiry, emails it via Gmail SMTP (HTML email built in [auth.py:43-61](app/routes/auth.py#L43-L61)). User enters OTP + new password → OTP is verified + expired check → password updated, OTP cleared.
6. **Rate limiting** — Flask-Limiter caps `/register` at 5/min, `/login` at 10/min, `/forgot-password` at 3/min — prevents brute force.
7. **CSRF protection** — every form has `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` and Flask-WTF rejects POSTs without it.

---

## 5. The Discussion Chat — how messages work

This is **not real-time WebSockets** — it's a classic **HTTP request/response forum model**, similar to early Reddit or Stack Overflow. Be honest about this in the interview; it's a common, scalable pattern.

### Data model
Two tables:
- `Discussion` — the thread (title + content + project_id + creator)
- `DiscussionComment` — replies (content + discussion_id + creator)

A `Project` has many `Discussion`s. A `Discussion` has many `DiscussionComment`s. Both are just **foreign keys**.

### The full flow — what happens when a user posts a message

User is on the discussion page → fills the textarea → clicks "Post Comment".

**Step 1 — Browser sends HTTP POST**
The form in [discussions/view.html:52-60](app/templates/discussions/view.html#L52-L60) submits to `/discussions/<id>/comment` with the comment content + CSRF token.

**Step 2 — Server receives it** ([discussions.py:74-104](app/routes/discussions.py#L74-L104))
```python
@discussions_bp.route('/discussions/<int:discussion_id>/comment', methods=['POST'])
@login_required
def add_discussion_comment(discussion_id):
    discussion = Discussion.query.get_or_404(discussion_id)   # fetch or 404
    if not check_project_access(discussion.project):          # is user in the org?
        flash("Access denied.", 'danger')
        return redirect(...)

    content = request.form.get('content', '').strip()         # validate
    if not content:
        flash("Comment cannot be empty."); return redirect(...)

    comment = DiscussionComment(                              # create row
        content=content,
        discussion_id=discussion.id,
        created_by=current_user.id
    )
    db.session.add(comment)                                   # stage insert
    log_activity(...)                                         # audit log
    for member in OrgMember.query.filter_by(org_id=...).all():  # notify others
        if member.user_id != current_user.id:
            create_notification(member.user_id, "...", url)
    db.session.commit()                                       # ONE atomic DB write
    return redirect(...)                                      # PRG pattern
```

**Step 3 — Atomic commit**
The comment + activity log + N notifications are all written in **one transaction**. If anything fails, nothing is saved.

**Step 4 — Redirect (Post-Redirect-Get pattern)**
After the POST succeeds, the server sends a `302 Redirect` back to the discussion page. The browser does a fresh GET → hits [discussions.py:63-72](app/routes/discussions.py#L63-L72), which re-runs:
```python
comments = DiscussionComment.query.filter_by(discussion_id=...).order_by(created_at.asc()).all()
```
and renders [discussions/view.html](app/templates/discussions/view.html) where Jinja loops `{% for comment in comments %}` and prints each one.

**Step 5 — Other users see it**
Other org members see the new comment **the next time they refresh** (or they get a `Notification` in their bell dropdown — see section 6). It's not pushed in real-time. To upgrade this to true chat you'd plug in Flask-SocketIO, but the current model handles concurrent users fine because every request hits the DB fresh.

> **Interview note:** "Why no WebSockets?" → "We chose simplicity. Discussions are forum-style, not chat — users don't expect <1-second updates. The PRG pattern is robust, cacheable, scales horizontally, and survives page reloads. Adding SocketIO would be a future enhancement if traffic justifies it."

### Access control on discussions
`check_project_access()` ([discussions.py:9-12](app/routes/discussions.py#L9-L12)) — re-runs `OrgMember.query.filter_by(org_id=project.org_id, user_id=current_user.id).first()` on every single request. **Stateless authorization** — no trust in session data, the DB is always the source of truth.

---

## 6. Notifications — how the bell badge works

[app/routes/notifications.py](app/routes/notifications.py) + [app/models.py:171](app/models.py#L171)

**Trigger:** Whenever something happens (someone joins your org, comments on your task, assigns you a task, starts a discussion), the route calls `create_notification(user_id, message, link)` from [utils.py:17-25](app/utils.py#L17-L25). This stages a `Notification` row.

**Storage:** Each `Notification` row has `user_id` (target), `message`, `link`, `is_read`, `created_at`.

**Display:** [base.html:43-80](app/templates/base.html#L43-L80) — on every page render, Jinja queries:
```jinja
{% set unread_count = current_user.notifications.filter_by(is_read=False).count() %}
```
If > 0, it shows a red badge. The dropdown lists the 10 most recent notifications from `current_user.get_recent_notifications(10)`.

**Mark as read:** Clicking a notification GETs `/notifications/read/<id>` → sets `is_read=True` → redirects to the link. "Mark all read" POSTs `/notifications/read-all` → bulk update.

> **Interview note:** "Why is this safe?" → "Every read/update query filters by `user_id=current_user.id`, so user A can't mark user B's notifications as read even by guessing IDs."

---

## 7. Organizations & Projects — multi-tenant teamwork

### Creating an org ([orgs.py:32-70](app/routes/orgs.py#L32))
1. User submits name + description.
2. Server generates a **URL slug** (`generate_slug()` — lowercase, hyphenated, dedupes with counter).
3. Generates a random **invite code** with `secrets.token_urlsafe(6)` — cryptographically secure.
4. Inserts `Organization` row. `db.session.flush()` gets the new ID **without committing**.
5. Inserts an `OrgMember` row (creator = Admin).
6. Logs activity.
7. **One commit** for all three operations — atomic.

### Joining an org ([orgs.py:72-106](app/routes/orgs.py#L72))
- User pastes the invite code → server looks up `Organization` by `invite_code` → checks for duplicate membership → adds new `OrgMember` (Member role) → creates a notification for the org creator → commits.
- Rate-limited (5/min) so people can't brute-force invite codes.

### Project Kanban dashboard ([projects.py:46-82](app/routes/projects.py#L46))
Server fetches all tasks where `project_id == X`, splits into 3 lists by status:
```python
pending_tasks   = [t for t in tasks if t.status == 'Pending']
working_tasks   = [t for t in tasks if t.status == 'Working']
completed_tasks = [t for t in tasks if t.status == 'Completed']
```
Renders three columns. Status changes via `/toggle/<id>` cycle: Pending → Working → Completed → Pending.

---

## 8. Activity Log — audit trail

[app/utils.py:4-15](app/utils.py#L4-L15) `log_activity(org_id, user_id, action, project_id=None)` — called from inside almost every mutation route.

It stages an `ActivityLog` row but **does not commit** — the caller commits with the actual data change, so the activity log and the data change are in **the same transaction**. If the data change rolls back, the activity log rolls back too.

Org dashboard shows the last 15 activities ([orgs.py:121](app/routes/orgs.py#L121)). Project dashboard shows last 15 for that project ([projects.py:70](app/routes/projects.py#L70)).

---

## 9. Tasks — the core feature

[app/routes/tasks.py](app/routes/tasks.py)

- **Personal tasks** live with `user_id` set and `project_id = NULL`.
- **Project tasks** have `project_id` set and visibility tied to org membership.
- Fields: `title`, `status`, `priority`, `deadline` (date), `time_slot` (time), `created_at`, `assigned_to`, `created_by`, `google_event_id`.

### Filters & search ([tasks.py:27-67](app/routes/tasks.py#L27))
URL query params drive filters: `?status=Pending&priority=High&q=report&date=2026-05-10`. Each filter chains a `query.filter(...)` on the SQLAlchemy query. The `Task.title.ilike('%report%')` does case-insensitive substring search.

### CSV Export ([tasks.py:441-503](app/routes/tasks.py#L441))
Builds a CSV in memory using `io.StringIO` + Python's `csv` module, returns it as a downloadable file with `Content-Disposition: attachment`. Supports range filters: last 7/15/30 days or custom date range.

### Google Calendar sync ([tasks.py:135-183](app/routes/tasks.py#L135), [google.py](app/routes/google.py))
- User clicks "Connect Google Calendar" → OAuth 2.0 flow.
- Tokens (access + refresh + expiry) are stored on the `User` row.
- When a task with a deadline is created/edited/deleted, the server uses those tokens to call the Google Calendar API and create/update/delete the event with a 30-minute time slot + email + popup reminders.
- All Google calls are wrapped in `try/except` — **if Google fails, the local task still saves**. Calendar is a best-effort enhancement, not a blocker.

---

## 10. Security — what's defending the app

| Threat | Defense |
|---|---|
| Password theft | PBKDF2 hashing via Werkzeug |
| Session hijack | Flask-Login signed cookies + `SECRET_KEY` |
| CSRF | Flask-WTF — every POST form has a `csrf_token` |
| Brute-force login | Flask-Limiter (10/min on login, 3/min on forgot) |
| URL guessing (IDOR) | Every route filters by `current_user.id` or checks `OrgMember` |
| SQL injection | SQLAlchemy ORM uses parameterized queries (no raw SQL) |
| Email enumeration | Forgot-password says "if an account exists, we sent code" — never confirms |
| OTP replay | Reset code single-use + 10-min expiry, cleared after use |
| OAuth scope drift | `OAUTHLIB_RELAX_TOKEN_SCOPE` only set in dev |
| Plain HTTP secrets in prod | App crashes if `SECRET_KEY` missing in production |

---

## 11. Frontend — how the UI is delivered

- **Server-rendered HTML** via Jinja2 templates extending [base.html](app/templates/base.html).
- No SPA framework — keeps it simple.
- [app/static/js/script.js](app/static/js/script.js) handles small interactions (sidebar toggles, notification dropdown).
- Custom CSS in [app/static/css/style.css](app/static/css/style.css) — glass-morphism design, dark theme.
- **Lucide icons** loaded from CDN.
- **Inter font** from Google Fonts.

---

## 12. Deployment

- `Procfile` for Heroku/Render — `web: gunicorn run:app`.
- `DATABASE_URL` env variable swaps SQLite → PostgreSQL automatically.
- Postgres connection pool tuned for concurrent users.
- `FLASK_ENV=production` enforces secret keys and disables OAuth-insecure-transport.

---

## How to summarize the project in 30 seconds for an interviewer

> "HiveFlow is a multi-tenant team task manager built with Flask 3 using the application-factory pattern and seven blueprints. Users sign up, manage personal tasks, create organizations, invite teammates by code, organize projects with Kanban boards, hold threaded discussions, comment on tasks, and receive notifications. Data isolation is enforced at the SQL layer — every query filters by `current_user.id` or verifies an `OrgMember` row before reading or writing. The discussion chat uses a classic Post-Redirect-Get HTTP model with atomic transactions that bundle the message, an activity log, and notifications into a single commit. Tasks with deadlines sync to Google Calendar via OAuth 2.0, with all calendar calls wrapped in try/except so a Google outage never blocks the user. Security covers PBKDF2 password hashing, CSRF tokens on every form, Flask-Limiter rate limits, and email-enumeration-safe password reset with 6-digit OTPs that expire in 10 minutes. SQLite for development, PostgreSQL with connection pooling for production, Alembic migrations for schema evolution."

That's the whole project — every feature, every flow, every defensive choice — in one mental map.
