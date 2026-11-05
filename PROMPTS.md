# PROMPTS.md - where the AI was wrong

| What the AI produced | What was wrong | What I changed |
|---|---|---|
| Register accepted `role` from the request | Anyone could make themselves admin | Role is always `viewer`; first admin comes from ADMIN_EMAIL |
| Share route had no ownership check | A viewer could grant themselves access | Only the file owner or an admin may share |
| `must_change` only checked on the frontend | One-time password could be used forever | Server blocks every route until a new password is set |
| Sign-in mail time hard-coded / server time | Hosting server runs in UTC, not IST | Time is computed in IST explicitly |
| Rate limit counted successful logins | Shared college Wi-Fi could lock students out | Only failed logins count |
| Said "encrypted like Hotstar" | Hotstar uses DRM; this is app-held encryption | README states the real limits |
