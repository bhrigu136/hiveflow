import os

os.environ.setdefault('TZ', 'UTC')

from app import create_app
app = create_app()


if __name__ == "__main__":
    # Explicitly read the environment. Default to 'production' so that a
    # missing env var never accidentally enables the Werkzeug debugger.
    # Set FLASK_ENV=development in your local .env to get auto-reload.
    flask_env = os.environ.get("FLASK_ENV", "production")
    debug_mode = flask_env == "development"
    app.run(debug=debug_mode)