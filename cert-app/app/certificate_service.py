from datetime import date

from .db import get_db
from .helpers import generate_cert_id, paginate, parse_date, row_to_dict, utc_now


def _normalize_search_term(value):
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _parse_page_number(raw_value, field_name, minimum=1):
    if raw_value is None:
        return minimum, None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None, {field_name: "Must be a whole number"}

    if value < minimum:
        return None, {field_name: f"Must be at least {minimum}"}

    return value, None


def parse_certificate_list_params(args):
    errors = {}

    page_value = args.get("page", "1")
    limit_value = args.get("limit", "10")
    search_value = _normalize_search_term(args.get("search"))
    status_value = args.get("status")

    page, page_error = _parse_page_number(page_value, "page", 1)
    if page_error:
        errors.update(page_error)

    limit, limit_error = _parse_page_number(limit_value, "limit", 1)
    if limit_error:
        errors.update(limit_error)
    elif limit > 50:
        errors["limit"] = "Must be between 1 and 50"

    if status_value is not None:
        clean_status = status_value.strip().lower()
        if clean_status not in {"active", "revoked"}:
            errors["status"] = "Must be either 'active' or 'revoked'"
        else:
            status_value = clean_status

    if errors:
        return {"page": 1, "limit": 10, "search": search_value, "status": None}, errors

    return {"page": page, "limit": limit, "search": search_value, "status": status_value}, errors


def validate_certificate_payload(data):
    errors = {}
    cleaned = {}

    recipient_name = data.get("recipient_name")
    if recipient_name is None or (isinstance(recipient_name, str) and not recipient_name.strip()):
        errors["recipient_name"] = "This field is required"
    elif not isinstance(recipient_name, str):
        errors["recipient_name"] = "Must be a string"
    else:
        value = recipient_name.strip()
        if not 2 <= len(value) <= 100:
            errors["recipient_name"] = "Must be between 2 and 100 characters"
        else:
            cleaned["recipient_name"] = value

    recipient_email = data.get("recipient_email")
    if recipient_email is None or (isinstance(recipient_email, str) and not recipient_email.strip()):
        errors["recipient_email"] = "This field is required"
    elif not isinstance(recipient_email, str):
        errors["recipient_email"] = "Must be a string"
    else:
        value = recipient_email.strip().lower()
        email_ok = "@" in value and value.count("@") == 1 and "." in value.split("@", 1)[1]
        if not email_ok:
            errors["recipient_email"] = "Must be a valid email address"
        else:
            cleaned["recipient_email"] = value

    course_name = data.get("course_name")
    if course_name is None or (isinstance(course_name, str) and not course_name.strip()):
        errors["course_name"] = "This field is required"
    elif not isinstance(course_name, str):
        errors["course_name"] = "Must be a string"
    else:
        value = course_name.strip()
        if not 2 <= len(value) <= 150:
            errors["course_name"] = "Must be between 2 and 150 characters"
        else:
            cleaned["course_name"] = value

    issue_date = data.get("issue_date")
    if issue_date is None or (isinstance(issue_date, str) and not issue_date.strip()):
        errors["issue_date"] = "This field is required"
    elif not isinstance(issue_date, str):
        errors["issue_date"] = "Must be a string"
    else:
        value = issue_date.strip()
        try:
            parsed = parse_date(value)
        except ValueError:
            errors["issue_date"] = "Must be in YYYY-MM-DD format"
        else:
            if parsed > date.today():
                errors["issue_date"] = "Must not be in the future"
            else:
                cleaned["issue_date"] = parsed.isoformat()

    return cleaned, errors


def certificate_exists_for_recipient_and_course(email, course_name):
    db = get_db()
    return db.execute(
        "SELECT 1 FROM certificates WHERE LOWER(recipient_email) = LOWER(?) AND LOWER(course_name) = LOWER(?) AND status = 'active'",
        (email, course_name),
    ).fetchone() is not None


def create_certificate_record(cleaned_data):
    db = get_db()
    now = utc_now()

    while True:
        cert_id = generate_cert_id()
        if db.execute("SELECT 1 FROM certificates WHERE cert_id = ?", (cert_id,)).fetchone() is None:
            break

    db.execute(
        "INSERT INTO certificates (cert_id, recipient_name, recipient_email, course_name, issue_date, status, revoked_at, created_at) VALUES (?, ?, ?, ?, ?, 'active', NULL, ?)",
        (
            cert_id,
            cleaned_data["recipient_name"],
            cleaned_data["recipient_email"],
            cleaned_data["course_name"],
            cleaned_data["issue_date"],
            now,
        ),
    )
    db.commit()

    cert_row = db.execute("SELECT * FROM certificates WHERE cert_id = ?", (cert_id,)).fetchone()
    return row_to_dict(cert_row)


def list_certificates_for_page(page, limit, search, status):
    db = get_db()
    where_clauses = []
    params = []

    if search:
        where_clauses.append("LOWER(recipient_name) LIKE LOWER(?)")
        params.append(f"%{search}%")

    if status:
        where_clauses.append("status = ?")
        params.append(status)

    sql = "SELECT * FROM certificates"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, (page - 1) * limit])

    rows = db.execute(sql, tuple(params)).fetchall()

    count_sql = "SELECT COUNT(*) AS total FROM certificates"
    if where_clauses:
        count_sql += " WHERE " + " AND ".join(where_clauses)
    total = db.execute(count_sql, tuple(params[:-2])).fetchone()["total"]

    data = [row_to_dict(row) for row in rows]
    pages = 0 if total == 0 else (total + limit - 1) // limit

    return {
        "data": data,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": pages,
        },
    }


def get_certificate_record(cert_id):
    db = get_db()
    row = db.execute("SELECT * FROM certificates WHERE cert_id = ?", (cert_id,)).fetchone()
    if row is None:
        return None
    return row_to_dict(row)


def verify_certificate_record(cert_id):
    row = get_db().execute("SELECT * FROM certificates WHERE cert_id = ?", (cert_id,)).fetchone()
    if row is None:
        return None

    return {
        "cert_id": row["cert_id"],
        "valid": row["status"] == "active",
        "status": row["status"],
        "recipient_name": row["recipient_name"],
        "course_name": row["course_name"],
        "issue_date": row["issue_date"],
        "revoked_at": row["revoked_at"],
    }


def revoke_certificate_record(cert_id):
    db = get_db()
    row = db.execute("SELECT * FROM certificates WHERE cert_id = ?", (cert_id,)).fetchone()
    if row is None:
        return None, "not_found"
    if row["status"] == "revoked":
        return None, "already_revoked"

    now = utc_now()
    db.execute(
        "UPDATE certificates SET status = 'revoked', revoked_at = ? WHERE cert_id = ?",
        (now, cert_id),
    )
    db.commit()

    updated = db.execute("SELECT * FROM certificates WHERE cert_id = ?", (cert_id,)).fetchone()
    return row_to_dict(updated), None
