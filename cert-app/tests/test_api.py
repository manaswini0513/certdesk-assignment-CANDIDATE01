"""Starter tests. Some of these fail on purpose until you finish the task.

Add your own tests (at least 5) in this file or in new test files.
"""
from datetime import date

from app.auth import hash_password
from app.helpers import paginate, parse_date


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_parse_date_reads_year_month_day():
    assert parse_date("2026-03-25") == date(2026, 3, 25)


def test_paginate_first_page_starts_at_zero():
    assert paginate(1, 10) == (0, 10)


def test_create_certificate(client, valid_payload):
    res = client.post("/api/certificates", json=valid_payload)
    assert res.status_code == 201
    cert = res.get_json()["data"]
    assert cert["cert_id"].startswith("CERT-")
    assert cert["status"] == "active"


def test_create_certificate_with_empty_body_fails(client):
    res = client.post("/api/certificates", json={})
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_unknown_certificate_returns_404(client):
    res = client.get("/api/certificates/CERT-00000000")
    assert res.status_code == 404
    assert res.get_json()["error"]["code"] == "NOT_FOUND"


def test_signup_logs_you_in(anon_client):
    res = anon_client.post(
        "/api/auth/signup",
        json={"name": "Ada Lovelace", "email": "ada@example.com", "password": "analytical-engine"},
    )
    assert res.status_code == 201
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["data"]["email"] == "ada@example.com"


def test_login_with_wrong_password_fails(client):
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "not-the-password"},
    )
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_hash_password_is_not_plain_text_or_base64():
    value = hash_password("super-secret")
    assert value != "super-secret"
    assert value != "c3VwZXItc2VjcmV0"
    assert value.startswith("scrypt") or value.startswith("pbkdf2")


def test_email_settings_save_and_get(client, monkeypatch):
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.timeout = timeout

        def ehlo(self):
            return None

        def starttls(self):
            return None

        def login(self, username, password):
            assert username == "academy@gmail.com"
            assert password == "abcd1234efgh5678"

        def quit(self):
            return None

    monkeypatch.setattr("app.email_settings.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.email_settings.smtplib.SMTP_SSL", FakeSMTP)

    res = client.put(
        "/api/email-settings",
        json={
            "from_name": "CertDesk Academy",
            "email": "academy@gmail.com",
            "app_password": "abcd 1234 efgh 5678",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
        },
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()["data"]
    assert body["email"] == "academy@gmail.com"
    assert "app_password" not in body
    assert body["from_name"] == "CertDesk Academy"

    res = client.get("/api/email-settings")
    assert res.status_code == 200
    assert res.get_json()["data"]["email"] == "academy@gmail.com"


def test_email_settings_invalid_password_returns_field_error(client, monkeypatch):
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            raise RuntimeError("boom")

    def fake_login(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad password")

    monkeypatch.setattr("app.email_settings.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.email_settings.smtplib.SMTP_SSL", FakeSMTP)

    import smtplib

    class FakeServer:
        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            return None

        def starttls(self):
            return None

        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad password")

        def quit(self):
            return None

    monkeypatch.setattr("app.email_settings.smtplib.SMTP", lambda *args, **kwargs: FakeServer())

    res = client.put(
        "/api/email-settings",
        json={
            "from_name": "CertDesk Academy",
            "email": "academy@gmail.com",
            "app_password": "wrong-pass",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
        },
    )
    assert res.status_code == 400
    assert res.get_json()["error"]["details"]["app_password"] == "Gmail did not accept this email and app password"


def test_send_certificate_email_uses_saved_settings(client, monkeypatch, valid_payload):
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.timeout = timeout

        def ehlo(self):
            return None

        def starttls(self):
            return None

        def login(self, username, password):
            assert username == "academy@gmail.com"
            assert password == "abcd1234efgh5678"

        def send_message(self, message):
            assert message["To"] == "test.user@example.com"

        def quit(self):
            return None

    monkeypatch.setattr("app.email_settings.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.email_settings.smtplib.SMTP_SSL", FakeSMTP)

    client.put(
        "/api/email-settings",
        json={
            "from_name": "CertDesk Academy",
            "email": "academy@gmail.com",
            "app_password": "abcd 1234 efgh 5678",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
        },
    )

    cert = client.post("/api/certificates", json=valid_payload)
    cert_id = cert.get_json()["data"]["cert_id"]
    res = client.post(f"/api/certificates/{cert_id}/send-email")
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["data"]["sent_to"] == "test.user@example.com"


def test_bulk_issue_upload_preview_and_approve(client):
    import io
    import time

    csv_data = (
        "recipient_name,recipient_email,course_name,issue_date\n"
        "Priya Nair,priya.nair@example.com,Python Fundamentals,2026-03-25\n"
        "Rohan Mehta,rohan.mehta@example.com,Python Fundamentals,2026-03-25\n"
        "Bad Row,bad-email,Python Fundamentals,2026-03-25\n"
    )

    res = client.post(
        "/api/bulk-issues",
        data={"file": (io.BytesIO(csv_data.encode("utf-8")), "students.csv")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    payload = res.get_json()
    assert payload["summary"]["ready"] == 2
    assert payload["summary"]["errors"] == 1
    assert payload["rows"][0]["row_number"] == 1
    assert payload["rows"][0]["status"] == "ready"
    assert payload["rows"][2]["status"] == "error"

    job_id = payload["job_id"]
    res = client.post(f"/api/bulk-issues/{job_id}/approve")
    assert res.status_code == 202, res.get_data(as_text=True)

    for _ in range(50):
        poll = client.get(f"/api/bulk-issues/{job_id}")
        if poll.get_json()["job"]["status"] == "completed":
            break
        time.sleep(0.05)

    job = client.get(f"/api/bulk-issues/{job_id}").get_json()["job"]
    assert job["status"] == "completed"
    assert job["summary"]["issued"] == 2
    assert job["summary"]["failed"] == 0
    assert len(job["rows"]) == 3
    assert job["rows"][0]["status"] == "issued"
    assert job["rows"][0]["cert_id"].startswith("CERT-")


def test_csrf_token_endpoint(client):
    res = client.get("/api/auth/csrf-token")
    assert res.status_code == 200
    token = res.get_json()["data"]["csrf_token"]
    assert isinstance(token, str)
    assert len(token) >= 32


def test_session_expires_after_idle_timeout(client):
    from datetime import datetime, timedelta, timezone

    with client.session_transaction() as session:
        session["last_seen"] = (
            datetime.now(timezone.utc) - timedelta(minutes=31)
        ).isoformat()

    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_logout_invalidates_replayed_session(client):
    before = client.get("/api/auth/me")
    assert before.status_code == 200

    res = client.post("/api/auth/logout")
    assert res.status_code == 204

    replay = client.get("/api/auth/me")
    assert replay.status_code == 401
