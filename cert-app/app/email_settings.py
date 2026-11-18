"""Email setup (Gmail / SMTP) and emailing certificates to recipients."""
import base64
import hashlib
import smtplib
from email.message import EmailMessage

from flask import Blueprint, g, jsonify, request

from .auth import login_required
from .db import get_db
from .helpers import error_response, utc_now
from .validators import EMAIL_RE

email_bp = Blueprint("email", __name__, url_prefix="/api")


def _secret_key_for_email(email):
    return hashlib.sha256((email + "::certdesk::").encode("utf-8")).digest()


def _encrypt_secret_for_user(user_email, value):
    key = _secret_key_for_email(user_email)
    raw = value.encode("utf-8")
    encoded = bytearray(len(raw))
    for index, byte in enumerate(raw):
        encoded[index] = byte ^ key[index % len(key)]
    return base64.b64encode(bytes(encoded)).decode("ascii")


def _decrypt_secret_for_user(user_email, value):
    key = _secret_key_for_email(user_email)
    raw = base64.b64decode(value.encode("ascii"))
    text = bytearray(len(raw))
    for index, byte in enumerate(raw):
        text[index] = byte ^ key[index % len(key)]
    return bytes(text).decode("utf-8")


def _encrypt_secret(value):
    return _encrypt_secret_for_user(g.user["email"], value)


def _decrypt_secret(value):
    return _decrypt_secret_for_user(g.user["email"], value)


def _settings_row_to_dict(row):
    if row is None:
        return None
    return {
        "email": row["email"],
        "from_name": row["from_name"],
        "smtp_host": row["smtp_host"],
        "smtp_port": row["smtp_port"],
        "verified_at": row["verified_at"],
    }


def _get_settings_row(user_id):
    return get_db().execute(
        "SELECT * FROM email_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def _validate_settings_payload(data):
    errors = {}
    cleaned = {}

    from_name = data.get("from_name")
    if from_name is None or (isinstance(from_name, str) and not from_name.strip()):
        cleaned["from_name"] = g.user["name"]
    elif not isinstance(from_name, str):
        errors["from_name"] = "Must be a string"
    else:
        value = from_name.strip()
        if len(value) > 100:
            errors["from_name"] = "Must be 100 characters or fewer"
        else:
            cleaned["from_name"] = value or g.user["name"]

    email_value = data.get("email")
    if email_value is None or (isinstance(email_value, str) and not email_value.strip()):
        errors["email"] = "This field is required"
    elif not isinstance(email_value, str):
        errors["email"] = "Must be a string"
    else:
        value = email_value.strip().lower()
        if not EMAIL_RE.match(value):
            errors["email"] = "Must be a valid email address"
        else:
            cleaned["email"] = value

    app_password = data.get("app_password")
    if app_password is None or (isinstance(app_password, str) and not app_password.strip()):
        errors["app_password"] = "This field is required"
    elif not isinstance(app_password, str):
        errors["app_password"] = "Must be a string"
    else:
        value = app_password.replace(" ", "")
        if not 1 <= len(value) <= 128:
            errors["app_password"] = "Must be between 1 and 128 characters"
        else:
            cleaned["app_password"] = value

    smtp_host = data.get("smtp_host")
    if smtp_host is None or (isinstance(smtp_host, str) and not smtp_host.strip()):
        errors["smtp_host"] = "This field is required"
    elif not isinstance(smtp_host, str):
        errors["smtp_host"] = "Must be a string"
    else:
        value = smtp_host.strip().lower()
        if not value:
            errors["smtp_host"] = "This field is required"
        else:
            cleaned["smtp_host"] = value

    smtp_port = data.get("smtp_port")
    if smtp_port is None:
        errors["smtp_port"] = "This field is required"
    else:
        try:
            value = int(smtp_port)
        except (TypeError, ValueError):
            errors["smtp_port"] = "Must be a whole number"
        else:
            if not 1 <= value <= 65535:
                errors["smtp_port"] = "Must be between 1 and 65535"
            else:
                cleaned["smtp_port"] = value

    return cleaned, errors


def _login_to_smtp(settings, user_email=None):
    user_email = user_email or g.user["email"]
    app_password = _decrypt_secret_for_user(user_email, settings["app_password_encrypted"])
    port = int(settings["smtp_port"])
    host = settings["smtp_host"]
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.ehlo()
            server.starttls()
        server.login(settings["email"], app_password)
        server.quit()
        return True
    except smtplib.SMTPAuthenticationError:
        raise ValueError("bad_credentials")
    except (smtplib.SMTPConnectError, smtplib.SMTPException, TimeoutError, OSError):
        raise ConnectionError("connection_failed")


def _send_message(settings, to_address, subject, body, user_email=None):
    user_email = user_email or g.user["email"]
    app_password = _decrypt_secret_for_user(user_email, settings["app_password_encrypted"])
    msg = EmailMessage()
    msg["From"] = f'{settings["from_name"]} <{settings["email"]}>'
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    port = int(settings["smtp_port"])
    host = settings["smtp_host"]
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.ehlo()
            server.starttls()
        server.login(settings["email"], app_password)
        server.send_message(msg)
        server.quit()
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise RuntimeError(str(exc))


# E1. Get my email settings
@email_bp.get("/email-settings")
@login_required
def get_email_settings():
    row = _get_settings_row(g.user["id"])
    return jsonify({"data": _settings_row_to_dict(row)})


# E2. Save (and verify) email settings
@email_bp.put("/email-settings")
@login_required
def save_email_settings():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("BAD_REQUEST", "Request body must be a JSON object", 400)

    cleaned, errors = _validate_settings_payload(data)
    if errors:
        return error_response("VALIDATION_ERROR", "Invalid input", 400, errors)

    candidate = {
        "email": cleaned["email"],
        "from_name": cleaned["from_name"],
        "smtp_host": cleaned["smtp_host"],
        "smtp_port": cleaned["smtp_port"],
        "app_password_encrypted": _encrypt_secret(cleaned["app_password"]),
    }

    try:
        _login_to_smtp(candidate)
    except ValueError:
        return error_response(
            "VALIDATION_ERROR",
            "Invalid input",
            400,
            {"app_password": "Gmail did not accept this email and app password"},
        )
    except ConnectionError:
        return error_response("SMTP_ERROR", "Could not connect to the SMTP server", 502)

    db = get_db()
    now = utc_now()
    db.execute(
        """
        INSERT INTO email_settings (
            user_id, email, from_name, smtp_host, smtp_port,
            app_password_encrypted, verified_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            email = excluded.email,
            from_name = excluded.from_name,
            smtp_host = excluded.smtp_host,
            smtp_port = excluded.smtp_port,
            app_password_encrypted = excluded.app_password_encrypted,
            verified_at = excluded.verified_at,
            created_at = excluded.created_at
        """,
        (
            g.user["id"],
            candidate["email"],
            candidate["from_name"],
            candidate["smtp_host"],
            candidate["smtp_port"],
            candidate["app_password_encrypted"],
            now,
            now,
        ),
    )
    db.commit()

    row = _get_settings_row(g.user["id"])
    return jsonify({"data": _settings_row_to_dict(row)})


# E3. Send a test email
@email_bp.post("/email-settings/test")
@login_required
def send_test_email():
    row = _get_settings_row(g.user["id"])
    if row is None:
        return error_response("CONFLICT", "Email isn't set up", 409)

    try:
        _send_message(
            row,
            g.user["email"],
            "CertDesk test email",
            "This is a test email from CertDesk.",
        )
    except RuntimeError:
        return error_response("SMTP_ERROR", "Could not send the test email", 502)

    return jsonify({"data": {"sent_to": g.user["email"]}})


# E4. Disconnect
@email_bp.delete("/email-settings")
@login_required
def delete_email_settings():
    get_db().execute("DELETE FROM email_settings WHERE user_id = ?", (g.user["id"],))
    get_db().commit()
    return "", 204


# E5. Email a certificate to its recipient
@email_bp.post("/certificates/<cert_id>/send-email")
@login_required
def send_certificate_email(cert_id):
    cert = get_db().execute(
        "SELECT * FROM certificates WHERE cert_id = ?",
        (cert_id,),
    ).fetchone()
    if cert is None:
        return error_response("NOT_FOUND", "Certificate not found", 404)

    row = _get_settings_row(g.user["id"])
    if row is None:
        return error_response("CONFLICT", "Email isn't set up", 409)
    if cert["status"] == "revoked":
        return error_response("CONFLICT", "Certificate is revoked", 409)

    verify_url = f"http://localhost:5000/verify/{cert_id}"
    body = (
        f"Hello {cert['recipient_name']},\n\n"
        f"This is your certificate for {cert['course_name']} issued on {cert['issue_date']}.\n"
        f"Certificate ID: {cert['cert_id']}\n"
        f"Verify it here: {verify_url}\n"
    )

    try:
        _send_message(
            row,
            cert["recipient_email"],
            f"Your certificate: {cert['course_name']}",
            body,
        )
    except RuntimeError:
        return error_response("SMTP_ERROR", "Could not send the certificate email", 502)

    return jsonify(
        {
            "data": {
                "cert_id": cert["cert_id"],
                "sent_to": cert["recipient_email"],
                "sent_from": f'{row["from_name"]} <{row["email"]}>',
            }
        }
    )
