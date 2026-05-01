from app import create_app
import os
app = create_app()


if __name__ == "__main__":
    # Debug on by default for local dev — gives auto-reload on file change and
    # an interactive traceback. Disable only when FLASK_ENV=production.
    debug_mode = os.environ.get("FLASK_ENV") != "production"
    app.run(debug=debug_mode)