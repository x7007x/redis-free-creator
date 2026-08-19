# Redis Free Account Creator

GitHub Actions workflow that creates a fresh Redis Cloud free account using a disposable mailbox from mail.tm and returns the login email, password, and free database connection URL.

## Files

| File | Purpose |
| --- | --- |
| `.github/workflows/create-redis.yml` | GitHub Actions workflow (manual dispatch or daily schedule) |
| `redis_full_cycle.py` | All-in-one script: temp mailbox, registration, activation, URL extraction |

## What the workflow does

1. Installs Python, Playwright, and Chromium with system deps
2. Warms up a PerimeterX session on cloud.redis.io (their anti-bot blocks cold sessions)
3. Runs `redis_full_cycle.py` which creates a mail.tm mailbox, registers a Redis account with fake data, waits for the activation email, activates the account, and extracts the free database `redis://` URL
4. Verifies the URL with a real PING/SET/GET
5. Uploads `redis_new_account.json` as an artifact and prints the credentials in the workflow summary

## Local usage

```bash
pip install playwright redis
playwright install chromium --with-deps
python3 redis_full_cycle.py test
```

Environment variables `PX_PROFILE_DIR` and `RESULT_FILE` control the browser profile and output file locations.
