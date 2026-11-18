import csv
import io
import threading
import uuid
from typing import Dict, List, Tuple

from flask import Blueprint, Response, current_app, g, jsonify, request

from .auth import login_required
from .certificate_service import certificate_exists_for_recipient_and_course, create_certificate_record
from .db import get_db
from .email_settings import _get_settings_row, _send_message
from .helpers import error_response, utc_now
from .validators import validate_certificate_payload

bulk_bp = Blueprint("bulk_issues", __name__, url_prefix="/api")

REQUIRED_COLUMNS = ("recipient_name", "recipient_email", "course_name", "issue_date")


def _preview_row_for_payload(row_number, payload, error_message=None):
    return {
        "row_number": row_number,
        "recipient_name": payload.get("recipient_name"),
        "recipient_email": payload.get("recipient_email"),
        "course_name": payload.get("course_name"),
        "issue_date": payload.get("issue_date"),
        "status": "error" if error_message else "ready",
        "error": error_message,
    }


def _clean_csv_row(raw_row):
    cleaned = {}
    for key, value in (raw_row or {}).items():
        if key is None:
            continue
        if isinstance(value, str):
            cleaned[str(key).strip()] = value.strip()
        else:
            cleaned[str(key).strip()] = str(value).strip()
    return cleaned


def _parse_csv_file(file_storage):
    if file_storage is None:
        raise ValueError("A CSV file is required")

    file_bytes = file_storage.read()
    if not file_bytes:
        raise ValueError("The uploaded CSV file is empty")
    if len(file_bytes) > 1_048_576:
        raise ValueError("File is too large. The maximum size is 1 MB")

    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The file must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV header row is missing")

    field_map = {str(name).strip().lower(): name for name in reader.fieldnames if name is not None}
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in field_map]
    if missing_columns:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing_columns)}")

    preview_rows = []
    seen_pairs = set()
    row_index = 0
    for raw_row in reader:
        if raw_row is None:
            continue
        if all((value is None or str(value).strip() == "") for value in raw_row.values()):
            continue

        row_index += 1
        cleaned_row = _clean_csv_row(raw_row)
        payload = {}
        for field in REQUIRED_COLUMNS:
            header_name = field_map.get(field)
            payload[field] = cleaned_row.get(header_name, "") if header_name else ""

        cleaned, errors = validate_certificate_payload(payload)
        duplicate_key = None
        if not errors:
            email = cleaned["recipient_email"].lower()
            course = cleaned["course_name"].lower()
            duplicate_key = (email, course)
            if duplicate_key in seen_pairs:
                errors["recipient_email"] = "A duplicate certificate for this recipient and course appears earlier in the file"
                errors["course_name"] = "A duplicate certificate for this recipient and course appears earlier in the file"
            else:
                seen_pairs.add(duplicate_key)

        if not errors and certificate_exists_for_recipient_and_course(cleaned["recipient_email"], cleaned["course_name"]):
            errors["recipient_email"] = "A certificate for this recipient and course is already active"
            errors["course_name"] = "A certificate for this recipient and course is already active"

        if errors:
            detail = "; ".join(sorted(set(errors.values())))
            preview_rows.append(_preview_row_for_payload(row_index, cleaned if cleaned else payload, detail))
            continue

        preview_rows.append(_preview_row_for_payload(row_index, cleaned, None))

    if not preview_rows:
        raise ValueError("No valid data rows were found in this CSV file")
    if len(preview_rows) > 500:
        raise ValueError("This file has too many rows. Maximum is 500 rows.")

    ready = sum(1 for row in preview_rows if row["status"] == "ready")
    errors = sum(1 for row in preview_rows if row["status"] == "error")
    return preview_rows, {"total": len(preview_rows), "ready": ready, "errors": errors, "issued": 0, "failed": 0}


def _job_to_dict(job_row, rows):
    summary = {
        "total": job_row["total_rows"],
        "ready": job_row["ready_rows"],
        "errors": job_row["error_rows"],
        "issued": job_row["issued_rows"],
        "failed": job_row["failed_rows"],
    }
    return {
        "job_id": job_row["job_id"],
        "filename": job_row["filename"],
        "status": job_row["status"],
        "summary": summary,
        "created_at": job_row["created_at"],
        "started_at": job_row["started_at"],
        "completed_at": job_row["completed_at"],
        "rows": rows,
    }


def _get_job_for_user(job_id):
    db = get_db()
    job_row = db.execute(
        "SELECT * FROM bulk_jobs WHERE job_id = ? AND user_id = ?",
        (job_id, g.user["id"]),
    ).fetchone()
    if job_row is None:
        return None
    rows = db.execute(
        "SELECT * FROM bulk_job_rows WHERE job_id = ? ORDER BY row_number",
        (job_row["id"],),
    ).fetchall()
    row_data = []
    for row in rows:
        row_data.append(
            {
                "row_number": row["row_number"],
                "recipient_name": row["recipient_name"],
                "recipient_email": row["recipient_email"],
                "course_name": row["course_name"],
                "issue_date": row["issue_date"],
                "status": row["status"],
                "error": row["error_message"],
                "cert_id": row["cert_id"],
            }
        )
    return _job_to_dict(job_row, row_data)


def _bulk_email_body(cert):
    return (
        f"Hello {cert['recipient_name']},\n\n"
        f"This is your certificate for {cert['course_name']} issued on {cert['issue_date']}.\n"
        f"Certificate ID: {cert['cert_id']}\n"
        f"Verify it here: http://localhost:5000/verify/{cert['cert_id']}\n"
    )


def _send_bulk_email(user_email, settings, cert):
    if not settings:
        return
    try:
        _send_message(
            settings,
            cert["recipient_email"],
            f"Your certificate: {cert['course_name']}",
            _bulk_email_body(cert),
            user_email=user_email,
        )
    except RuntimeError:
        return False
    return True


def _process_bulk_job(app, job_id):
    with app.app_context():
        db = get_db()
        job_row = db.execute("SELECT * FROM bulk_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if job_row is None:
            return

        user_row = db.execute("SELECT * FROM users WHERE id = ?", (job_row["user_id"],)).fetchone()
        email_row = _get_settings_row(job_row["user_id"])

        db.execute(
            "UPDATE bulk_jobs SET status = 'processing', started_at = ? WHERE job_id = ?",
            (utc_now(), job_id),
        )
        db.commit()

        ready_rows = db.execute(
            "SELECT * FROM bulk_job_rows WHERE job_id = ? AND status = 'ready' ORDER BY row_number",
            (job_row["id"],),
        ).fetchall()

        for row in ready_rows:
            payload = {
                "recipient_name": row["recipient_name"],
                "recipient_email": row["recipient_email"],
                "course_name": row["course_name"],
                "issue_date": row["issue_date"],
            }
            status = "issued"
            error_message = None
            cert_id = None
            try:
                if certificate_exists_for_recipient_and_course(payload["recipient_email"], payload["course_name"]):
                    raise ValueError("A certificate for this recipient and course is already active")
                cert = create_certificate_record(payload)
                cert_id = cert["cert_id"]
                if email_row is not None:
                    _send_bulk_email(user_row["email"], email_row, cert)
            except Exception as exc:  # pragma: no cover - runtime-specific
                status = "failed"
                error_message = str(exc)

            db.execute(
                "UPDATE bulk_job_rows SET status = ?, cert_id = ?, error_message = ? WHERE id = ?",
                (status, cert_id, error_message, row["id"]),
            )
            db.commit()

        issued_count = db.execute(
            "SELECT COUNT(*) AS count FROM bulk_job_rows WHERE job_id = ? AND status = 'issued'",
            (job_row["id"],),
        ).fetchone()["count"]
        failed_count = db.execute(
            "SELECT COUNT(*) AS count FROM bulk_job_rows WHERE job_id = ? AND status = 'failed'",
            (job_row["id"],),
        ).fetchone()["count"]
        error_count = db.execute(
            "SELECT COUNT(*) AS count FROM bulk_job_rows WHERE job_id = ? AND status = 'error'",
            (job_row["id"],),
        ).fetchone()["count"]

        db.execute(
            "UPDATE bulk_jobs SET "
            "status = 'completed', "
            "issued_rows = ?, "
            "failed_rows = ?, "
            "error_rows = ?, "
            "completed_at = ? "
            "WHERE id = ?",
            (issued_count, failed_count, error_count, utc_now(), job_row["id"]),
        )
        db.commit()


@bulk_bp.post("/bulk-issues")
@login_required
def upload_bulk_issue():
    file_storage = request.files.get("file")
    if file_storage is None:
        return error_response("BAD_REQUEST", "CSV file is required", 400)

    try:
        preview_rows, summary = _parse_csv_file(file_storage)
    except ValueError as exc:
        return error_response("VALIDATION_ERROR", str(exc), 400)

    db = get_db()
    now = utc_now()
    job_id = f"BULK-{uuid.uuid4().hex[:12].upper()}"
    db.execute(
        "INSERT INTO bulk_jobs (job_id, user_id, filename, status, total_rows, ready_rows, error_rows, issued_rows, failed_rows, created_at) VALUES (?, ?, ?, 'pending', ?, ?, ?, 0, 0, ?)",
        (job_id, g.user["id"], file_storage.filename or "bulk.csv", summary["total"], summary["ready"], summary["errors"], now),
    )
    job_row = db.execute("SELECT * FROM bulk_jobs WHERE job_id = ?", (job_id,)).fetchone()

    for row in preview_rows:
        db.execute(
            "INSERT INTO bulk_job_rows (job_id, row_number, recipient_name, recipient_email, course_name, issue_date, status, error_message, cert_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_row["id"],
                row["row_number"],
                row.get("recipient_name"),
                row.get("recipient_email"),
                row.get("course_name"),
                row.get("issue_date"),
                row["status"],
                row.get("error"),
                None,
                now,
            ),
        )
    db.commit()

    return jsonify({
        "job_id": job_id,
        "status": "pending",
        "summary": summary,
        "rows": preview_rows,
    })


@bulk_bp.post("/bulk-issues/<job_id>/approve")
@login_required
def approve_bulk_issue(job_id):
    db = get_db()
    job_row = db.execute(
        "SELECT * FROM bulk_jobs WHERE job_id = ? AND user_id = ?",
        (job_id, g.user["id"]),
    ).fetchone()
    if job_row is None:
        return error_response("NOT_FOUND", "Bulk issue job not found", 404)
    if job_row["status"] in {"processing", "completed", "failed"}:
        return error_response("CONFLICT", "This bulk upload has already been approved or completed", 409)
    if job_row["ready_rows"] == 0:
        return error_response("CONFLICT", "There are no valid rows ready to issue", 409)

    db.execute(
        "UPDATE bulk_jobs SET status = 'pending', approved_at = ? WHERE job_id = ?",
        (utc_now(), job_id),
    )
    db.commit()

    thread = threading.Thread(
        target=_process_bulk_job,
        args=(current_app._get_current_object(), job_id),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "status": "processing"}), 202


@bulk_bp.get("/bulk-issues/<job_id>")
@login_required
def get_bulk_issue(job_id):
    job = _get_job_for_user(job_id)
    if job is None:
        return error_response("NOT_FOUND", "Bulk issue job not found", 404)
    return jsonify({"job": job})


@bulk_bp.get("/bulk-issues/<job_id>/results.csv")
@login_required
def download_bulk_issue_results(job_id):
    db = get_db()
    job_row = db.execute(
        "SELECT * FROM bulk_jobs WHERE job_id = ? AND user_id = ?",
        (job_id, g.user["id"]),
    ).fetchone()
    if job_row is None:
        return error_response("NOT_FOUND", "Bulk issue job not found", 404)

    rows = db.execute(
        "SELECT * FROM bulk_job_rows WHERE job_id = ? ORDER BY row_number",
        (job_row["id"],),
    ).fetchall()

    csv_buffer = io.StringIO()
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=["row_number", "recipient_name", "recipient_email", "course_name", "issue_date", "status", "cert_id", "error"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "row_number": row["row_number"],
                "recipient_name": row["recipient_name"] or "",
                "recipient_email": row["recipient_email"] or "",
                "course_name": row["course_name"] or "",
                "issue_date": row["issue_date"] or "",
                "status": row["status"],
                "cert_id": row["cert_id"] or "",
                "error": row["error_message"] or "",
            }
        )

    output = csv_buffer.getvalue().encode("utf-8")
    filename = (job_row["filename"] or "bulk-results.csv").rsplit(".", 1)[0] + "-results.csv"
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
