import re
from datetime import date

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 128


def _text(data, field, min_len, max_len, errors, cleaned):
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        errors[field] = "This field is required"
        return
    if not isinstance(value, str):
        errors[field] = "Must be a string"
        return
    value = value.strip()
    if not min_len <= len(value) <= max_len:
        errors[field] = f"Must be between {min_len} and {max_len} characters"
        return
    cleaned[field] = value


def _email(data, field, errors, cleaned):
    """Required, trimmed, and in a valid email format."""
    _text(data, field, 3, 254, errors, cleaned)
    if field in cleaned and not EMAIL_RE.match(cleaned[field]):
        errors[field] = "Must be a valid email address"
        del cleaned[field]


def validate_signup_payload(data):
    """Return (cleaned_data, errors) for the sign-up form."""
    errors, cleaned = {}, {}

    _text(data, "name", 2, 100, errors, cleaned)
    _email(data, "email", errors, cleaned)

    password = data.get("password")
    if password is None or password == "":
        errors["password"] = "This field is required"
    elif not isinstance(password, str):
        errors["password"] = "Must be a string"
    elif not PASSWORD_MIN_LEN <= len(password) <= PASSWORD_MAX_LEN:
        errors["password"] = (
            f"Must be between {PASSWORD_MIN_LEN} and {PASSWORD_MAX_LEN} characters"
        )
    else:
        # Not trimmed on purpose: spaces are allowed in passwords.
        cleaned["password"] = password

    return cleaned, errors


def validate_certificate_payload(data):
    """Validate certificate payload and return cleaned fields plus validation errors."""
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
        if not EMAIL_RE.match(value):
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
            parsed_date = date.fromisoformat(value)
        except ValueError:
            errors["issue_date"] = "Must be in YYYY-MM-DD format"
        else:
            if parsed_date > date.today():
                errors["issue_date"] = "Must not be in the future"
            else:
                cleaned["issue_date"] = value

    return cleaned, errors
