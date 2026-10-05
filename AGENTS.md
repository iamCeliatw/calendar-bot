# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This is a **LINE Messaging Bot** for Google Calendar integration (繁體中文 interface). Users manage Google Calendar events via the LINE messaging app. There are two services:

| Service | Command | Port | Description |
|---|---|---|---|
| Webhook Server (Flask) | `python webhook_app.py` | 5000 | LINE webhook handler — receives messages, event creation wizard, calendar queries |
| Scheduled Notifier | `python main.py` | N/A | Daily push notifications (use `python main.py test` for one-shot) |

### Running the Webhook Server

1. Copy `.env.example` to `.env` and fill in LINE/Google credentials.
2. Run `python webhook_app.py` (Flask dev server on port 5000).
3. Health check: `curl http://localhost:5000/health` → `ok`
4. Callback probe: `GET /callback` returns a human-readable message; `POST /callback` requires valid LINE signature.

For production-like testing: `gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 8 webhook_app:app`

### External Dependencies

- **LINE Messaging API**: Requires `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_CHANNEL_SECRET` env vars. Without real credentials, the server starts but webhook signature verification will reject all POSTs (expected).
- **Google Calendar API**: Requires `token.json` (OAuth2 refresh token). Without it, any calendar operation raises `RuntimeError`. The `credentials.json` file is needed only for initial OAuth flow.

### Lint / Test / Build

- No formal test suite or linter is configured in this repo.
- Compile-check all files: `for f in *.py; do python3 -m py_compile "$f"; done`
- The `event_parser.py` module can be tested in isolation without external services.
- No build step required — this is a pure Python project.

### Gotchas

- `webhook_app.py` will `raise SystemExit` if `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, or `LINE_USER_IDS` are missing/empty when run via `__main__`. Ensure `.env` has these values.
- Session state is in-memory (10-minute TTL) — not persisted across restarts.
- Reminder list (`reminder_store.py`) lives in Firestore collection `reminders`; needs GCP credentials and the `roles/datastore.user` role on the Cloud Run service account.
- The `calendar_service.py` module blocks browser OAuth in CI/cloud environments (detects `K_SERVICE`, `GITHUB_ACTIONS`, `CI` env vars). Set `ALLOW_BROWSER_OAUTH=false` explicitly if needed.
