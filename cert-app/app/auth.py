"""Sign-up, login and session handling."""
import base64
import functools
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .helpers import error_response, utc_now
from .validators import validate_signup_payload

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
SESSION_TIMEOUT = timedelta(minutes=30)


def hash_password(password):
    """Return a safe password hash for storage."""
    return generate_password_hash(password)


def verify_password(password, stored_hash):
    """Check a password against the stored hash, including older base64 values."""
    if check_password_hash(stored_hash, password):
        return True
    legacy_hash = base64.b64encode(password.encode("utf-8")).decode("ascii")
    return stored_hash == legacy_hash


def user_to_dict(row):
    """Public shape of a user. Never includes the password."""
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


def _unauthorized(message="Please log in first"):
    return error_response("UNAUTHORIZED", message, 401)


def _start_session(user):
    db = get_db()
    nonce = secrets.token_urlsafe(32)
    db.execute("UPDATE users SET session_nonce = ? WHERE id = ?", (nonce, user["id"]))
    db.commit()

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["session_nonce"] = nonce
    session["last_seen"] = utc_now()
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)


@auth_bp.before_app_request
def load_logged_in_user():
    """Put the logged-in user (or None) on g.user for every request."""
    user_id = session.get("user_id")
    g.user = None

    if user_id is None:
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)
        return

    last_seen = session.get("last_seen")
    try:
        last_seen_at = datetime.fromisoformat(last_seen)
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
        expired = datetime.now(timezone.utc) - last_seen_at > SESSION_TIMEOUT
    except (TypeError, ValueError):
        expired = True

    if expired:
        session.clear()
        session["csrf_token"] = secrets.token_urlsafe(32)
        return

    user = get_db().execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    expected_nonce = session.get("session_nonce")
    if user is None or not user["session_nonce"] or not secrets.compare_digest(
        expected_nonce or "", user["session_nonce"]
    ):
        session.clear()
        session["csrf_token"] = secrets.token_urlsafe(32)
        return

    session["last_seen"] = utc_now()
    g.user = user


def login_required(view):
    """Only let logged-in users call this endpoint."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return _unauthorized()
        return view(*args, **kwargs)

    return wrapped


@auth_bp.get("/csrf-token")
def csrf_token():
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"data": {"csrf_token": session["csrf_token"]}})


# Sign up
@auth_bp.post("/signup")
def signup():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("BAD_REQUEST", "Request body must be a JSON object", 400)

    cleaned, errors = validate_signup_payload(data)
    if errors:
        return error_response("VALIDATION_ERROR", "Invalid input", 400, errors)

    db = get_db()
    existing = db.execute(
        "SELECT 1 FROM users WHERE email = ?", (cleaned["email"],)
    ).fetchone()
    if existing:
        return error_response("CONFLICT", "An account with that email already exists", 409)

    email = cleaned["email"].lower()
    db.execute(
        "INSERT INTO users (name, email, password_hash, session_nonce, created_at) VALUES (?, ?, ?, ?, ?)",
        (cleaned["name"], email, hash_password(cleaned["password"]), None, utc_now()),
    )
    db.commit()

    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    _start_session(user)
    return jsonify({"data": user_to_dict(user)}), 201


# Log in
@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("BAD_REQUEST", "Request body must be a JSON object", 400)

    email = data.get("email")
    password = data.get("password")
    errors = {}
    if not isinstance(email, str) or not email.strip():
        errors["email"] = "This field is required"
    if not isinstance(password, str) or not password:
        errors["password"] = "This field is required"
    if errors:
        return error_response("VALIDATION_ERROR", "Invalid input", 400, errors)

    email = email.strip().lower()
    user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        return _unauthorized("Invalid email or password")

    _start_session(user)
    return jsonify({"data": user_to_dict(user)})


# Log out
@auth_bp.post("/logout")
@login_required
def logout():
    db = get_db()
    db.execute("UPDATE users SET session_nonce = NULL WHERE id = ?", (g.user["id"],))
    db.commit()
    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(32)
    return "", 204


# Who am I?
@auth_bp.get("/me")
def me():
    if g.user is None:
        return _unauthorized()
    return jsonify({"data": user_to_dict(g.user)})
