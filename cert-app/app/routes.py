"""Routes for the certificate API."""
from flask import Blueprint, jsonify, request

from .auth import login_required
from .certificate_service import (
    certificate_exists_for_recipient_and_course,
    create_certificate_record,
    get_certificate_record,
    list_certificates_for_page,
    parse_certificate_list_params,
    revoke_certificate_record,
    verify_certificate_record,
)
from .helpers import error_response
from .validators import validate_certificate_payload

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


# 1. Create a certificate
@bp.post("/certificates")
@login_required
def create_certificate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("BAD_REQUEST", "Request body must be a JSON object", 400)

    cleaned, errors = validate_certificate_payload(data)
    if errors:
        return error_response("VALIDATION_ERROR", "Invalid input", 400, errors)

    email = cleaned["recipient_email"]
    course = cleaned["course_name"]
    if certificate_exists_for_recipient_and_course(email, course):
        return error_response(
            "CONFLICT",
            "A certificate for this recipient and course is already active",
            409,
        )

    cert = create_certificate_record(cleaned)
    return jsonify({"data": cert}), 201


# 2. List certificates
@bp.get("/certificates")
@login_required
def list_certificates():
    params, errors = parse_certificate_list_params(request.args)
    if errors:
        return error_response("VALIDATION_ERROR", "Invalid input", 400, errors)

    result = list_certificates_for_page(
        params["page"],
        params["limit"],
        params["search"],
        params["status"],
    )
    return jsonify(result)


# 3. Get one certificate
@bp.get("/certificates/<cert_id>")
@login_required
def get_certificate(cert_id):
    cert = get_certificate_record(cert_id)
    if cert is None:
        return error_response("NOT_FOUND", "Certificate not found", 404)
    return jsonify({"data": cert})


# 4. Verify a certificate (public, no login)
@bp.get("/verify/<cert_id>")
def verify_certificate(cert_id):
    cert = verify_certificate_record(cert_id)
    if cert is None:
        return error_response("NOT_FOUND", "Certificate not found", 404)
    return jsonify(cert)


# 5. Revoke a certificate
@bp.patch("/certificates/<cert_id>/revoke")
@login_required
def revoke_certificate(cert_id):
    cert, status = revoke_certificate_record(cert_id)
    if cert is None and status == "not_found":
        return error_response("NOT_FOUND", "Certificate not found", 404)
    if cert is None and status == "already_revoked":
        return error_response("CONFLICT", "Certificate is already revoked", 409)

    return jsonify({"data": cert})
