import os
import secrets
from datetime import timedelta

from flask import Flask, g, jsonify, redirect, request, session

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)


def create_app(test_config=None):
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder=FRONTEND_DIR,
        static_url_path="",
    )
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        DATABASE=os.environ.get(
            "DATABASE_PATH", os.path.join(app.instance_path, "certificates.db")
        ),
    )
    if test_config:
        app.config.update(test_config)

    from . import db

    db.init_app(app)

    @app.before_request
    def protect_mutating_requests():
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None

        # Test clients are explicitly exempted by TESTING; browser traffic is still protected.
        if app.config.get("TESTING"):
            return None

        csrf_token = session.get("csrf_token")
        submitted_token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not csrf_token or not submitted_token or not secrets.compare_digest(submitted_token, csrf_token):
            return (
                jsonify({"error": {"code": "CSRF_ERROR", "message": "Invalid or missing CSRF token"}}),
                403,
            )
        return None

    from .auth import auth_bp
    from .bulk_issues import bulk_bp
    from .email_settings import email_bp
    from .routes import bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(bp)
    app.register_blueprint(email_bp)
    app.register_blueprint(bulk_bp)

    # Pages. The app needs a login; the login and sign-up pages don't.
    @app.get("/")
    def index():
        if g.user is None:
            return redirect("/login")
        return app.send_static_file("index.html")

    @app.get("/login")
    def login_page():
        if g.user is not None:
            return redirect("/")
        return app.send_static_file("login.html")

    @app.get("/signup")
    def signup_page():
        if g.user is not None:
            return redirect("/")
        return app.send_static_file("signup.html")

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Resource not found"}}), 404

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return (
            jsonify({"error": {"code": "METHOD_NOT_ALLOWED", "message": "Method not allowed"}}),
            405,
        )

    @app.errorhandler(500)
    def server_error(_e):
        return (
            jsonify({"error": {"code": "SERVER_ERROR", "message": "Something went wrong"}}),
            500,
        )

    return app
