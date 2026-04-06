# Personal Task Management Pro (with Google Calendar Sync)

A production-ready multi-user task management application built using Flask. 
It supports secure authentication, CSRF protection, task prioritization, deadlines, search and filtering, and integrates directly with Google Calendar via OAuth 2.0 to sync task deadlines as calendar events.

## Key Features
- **User Authentication:** Secure registration & login, password hashing, and data isolation.
- **Task Management:** Full CRUD capabilities with inline editing, priority badges, and search/filters.
- **Google Calendar Sync:** OAuth 2.0 integration to auto-sync, update, and remove deadlines directly in user's Google Calendar.
- **Security First:** Includes CSRF form protection via Flask-WTF, secure HTTP-only configurations, and env-var secrets management.
- **Production Ready:** Pre-configured for PostgreSQL, Gunicorn, and seamless deployment to Render, Heroku, or Railway.

## 🗂 Project Structure
```text
.
├── app/                  # Application Factory
│   ├── routes/           # Blueprints for auth, tasks, google
│   ├── templates/        # Jinja2 templates
│   ├── static/           # CSS, JS, and Assets
│   ├── extensions.py     # Database, LoginManager, CSRF setups
│   └── models.py         # SQLAlchemy Database Models
├── instance/             # Local SQLite database goes here
├── procfile              # Gunicorn deployment config
├── requirements.txt      # Pinned dependency listing
├── .env.example          # Template for environment variables
└── run.py                # App entry point
```

## ⚙️ Installation & Setup

### 1. Clone Repository
```bash
git clone <your-new-repo-url>
cd <your-repo-folder>
```

### 2. Create Virtual Environment
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the example environment file:
```bash
cp .env.example .env
```
Inside `.env`, define your variables:
1. `SECRET_KEY`: Set to a strong random string.
2. `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`: Obtain these by creating an OAuth Web Application credential inside the [Google Cloud Console](https://console.cloud.google.com).

*Note: Ensure `.env` is never committed to GitHub directly!*

### 5. Run the App
```bash
python run.py
```
Open `http://127.0.0.1:5000`

## 🌍 Deployment (Render / Heroku / Railway)
This app is ready to drop into modern PaaS providers. It includes a `Procfile` for Gunicorn.
1. Create a PostgreSQL database on your host.
2. Provide your host with the Environment Variables from your `.env` (including `DATABASE_URL` for PostgreSQL).
3. Deploy your code! The host will automatically run `pip install`, connect the database via environment variable routing, and launch via Gunicorn.
