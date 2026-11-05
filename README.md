# TrustVault

A secure workspace to store confidential files with role-based access (admin / owner / viewer).

## Run locally
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      (then edit .env)
python app.py               -> http://127.0.0.1:8000
```

## Features
- Create account with name + email; a one-time password and the Drive folder link are emailed
- Sign-in notification email; first sign-in forces a new password (one-time password expires in 24 h)
- Roles: admin (manage users and all files), owner (upload, share, delete own files), viewer (only files shared with them, view-only unless download is granted)
- Files are encrypted (AES, Fernet) before being written to disk; stored under random names
- Rate limiting on login/register, security headers, upload size and type limits

## Honest limitations
- Encryption at rest with a key held by the app. This is not DRM like Hotstar: a viewer can still screenshot what is on screen.
- On free hosting, the SQLite database and stored files can reset when the app restarts.
- Rate limiting is in memory per worker.
- Google Drive upload of the encrypted files is not implemented; the Drive link is sent in the welcome email.
<!-- testing render deployment -->