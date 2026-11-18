import secrets
from datetime import datetime, timezone

from flask import jsonify

DATE_FORMAT = "%Y-%m-%d"
MAX_LIMIT = 50

CERT_FIELDS = (
    "cert_id",
    "recipient_name",
    "recipient_email",
    "course_name",
    "issue_date",
    "status",
    "revoked_at",
    "created_at",
)


def utc_now():
    """Current UTC time as an ISO 8601 string, e.g. '2026-03-25T10:15:00+00:00'."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def generate_cert_id():
    """Return a new public certificate ID like 'CERT-9F3A21BC'."""
    return "CERT-" + secrets.token_hex(4).upper()


def parse_date(value):
    """Parse a 'YYYY-MM-DD' string into a date. Raises ValueError if invalid."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def paginate(page, limit):
    """Convert a 1-based page number and page size into (offset, limit) for SQL."""
    offset = (page - 1) * limit
    return offset, limit


def row_to_dict(row):
    """Convert a sqlite3.Row from the certificates table into the API shape."""
    return {field: row[field] for field in CERT_FIELDS}


def error_response(code, message, status, details=None):
    """Build the standard error response described in API_CONTRACT.md."""
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status
