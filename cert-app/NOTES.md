# Bug notes and fixes

## 1) Passwords were stored as plain base64, not a real hash

### What the bug was
The app used a simple `base64` encoding for `users.password_hash`. That is not a password hash and is reversible.

### How I found it
I reviewed the auth code in `app/auth.py` and saw the password storage function was base64 encoding the password directly. This is a serious security bug because it turns a stored password into a recoverable value.

### How I fixed it
I replaced the storage function with Werkzeug's `generate_password_hash()` and switched login verification to `check_password_hash()`. I also kept a tiny compatibility check for older saved rows so existing local data still works during the transition.

### What could go wrong if it stayed
If this remained, a stolen database would expose real user passwords immediately. Anyone with access to the database could log into accounts without brute forcing anything.

---

## 2) The issue form sent the wrong field name to the API

### What the bug was
In `frontend/app.js`, the form submission payload used `recipientName` instead of the contract's required `recipient_name` key. The backend only accepts `recipient_name`, so the browser could never create a certificate even when the form looked valid.

### How I found it
I followed the real user flow in the browser and checked the JavaScript issue form submission against the backend validation contract in `API_CONTRACT.md`. The mismatch was obvious: the frontend sent `recipientName`, but the validator expected `recipient_name`.

### How I fixed it
I changed the payload to use the exact contract keys and trimmed the form values before sending them. This makes the UI and API agree again for single-certificate issuance.

### What could go wrong if it stayed
The app would appear broken in the browser: users could fill in the form, click issue, and get validation errors or silent failures even though the form looked complete.

---

## 3) Signup could overwrite an existing user row

### What the bug was
The signup route used `INSERT OR REPLACE` when inserting a new user. That is dangerous because it can replace an existing row instead of failing cleanly.

### How I found it
This was a code review bug in `app/auth.py`. The application already checked for duplicate email addresses, but using `OR REPLACE` would still allow a destructive overwrite if the database state or a race condition was ever unexpected.

### How I fixed it
I changed the insert to a plain `INSERT INTO` and kept the duplicate guard in the normal signup flow. This keeps the insertion safe and predictable.

### What could go wrong if it stayed
A user could unexpectedly lose their account identity or historical data if a row was replaced by mistake. That is a data-loss bug and a bad pattern for a user table.

---

## 4) SMTP app passwords need to be usable later, so they are encrypted rather than hashed

### What the choice was
The email backend stores the Gmail app password in the database for later SMTP login attempts. A plain hash would make it impossible to use the password again for SMTP auth, so I did not store it as a password hash.

### How the backend handles it
The SMTP password is encrypted with a reversible server-side key derived from the app's own secret material before it is saved. The app decrypts it only at the moment it needs to log in to the SMTP server or send a message. The API never returns the stored value back to the browser.

### Why this approach
This keeps the password out of API responses and avoids plain-text storage, while still letting the app perform real SMTP login and delivery. For a local demo app, this is a practical balance between security and functionality.

### What could go wrong if it stayed
If the database were exposed and the server secret were also compromised, the encrypted app password could be recovered. In production, a stronger system would use environment-managed secrets and a dedicated KMS or encrypted secret store rather than a local secret in the app configuration.
