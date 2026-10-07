# Bulk Certificate Generator

A backend API that accepts a list of recipients in a single request, generates a PDF certificate for each valid recipient from one predefined template, tracks progress, and lets the client retrieve the results.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy + SQLite, fpdf2, pytest.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

The API is at http://127.0.0.1:8000 and interactive docs are at http://127.0.0.1:8000/docs.
Tables are created on startup. The SQLite database and generated PDFs are stored under `./data/`.

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/certificates.db` | Any SQLAlchemy URL |
| `CERT_STORAGE_DIR` | `./data/certificates` | Where PDFs are written |
| `MAX_RECIPIENTS_PER_JOB` | `1000` | Upper bound per request |

## Test

```bash
pytest
```

The tests cover job creation, input validation, certificate generation, job status/progress, failure of a single certificate, and retrieval.

## API

### Submit a job

`POST /api/jobs` returns `202 Accepted` immediately. Generation continues in the background.

```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Python Bootcamp 2026",
    "recipients": [
      {"name": "Asha Rao", "email": "asha@example.com", "course": "Python 101", "issue_date": "2026-10-01"},
      {"name": "Ben Carter", "email": "ben@example.com"},
      {"name": "Broken Row", "email": "not-an-email"}
    ]
  }'
```

```json
{
  "id": "3f9c0b6e5d2a4e0f9a1b7c8d2e4f6a10",
  "title": "Python Bootcamp 2026",
  "status": "PENDING",
  "total": 3, "generated": 0, "failed": 0, "pending": 3,
  "created_at": "2026-10-07T10:15:00Z",
  "completed_at": null
}
```

Recipient fields: `name` (required), `email` (required, valid address), `course` (optional, falls back to `title`), `issue_date` (optional, defaults to today).

### Check status and progress

`GET /api/jobs/{job_id}`

```json
{
  "id": "3f9c0b6e5d2a4e0f9a1b7c8d2e4f6a10",
  "title": "Python Bootcamp 2026",
  "status": "COMPLETED_WITH_ERRORS",
  "total": 3, "generated": 2, "failed": 1, "pending": 0,
  "certificates": [
    {"id": "a1...", "position": 0, "status": "GENERATED", "error": null,
     "download_url": "/api/jobs/3f9c.../certificates/a1...", "recipient": {"name": "Asha Rao", "...": "..."}},
    {"id": "b2...", "position": 2, "status": "FAILED",
     "error": "Invalid recipient: email: value is not a valid email address: ...",
     "download_url": null, "recipient": {"name": "Broken Row", "email": "not-an-email"}}
  ]
}
```

Job statuses: `PENDING` → `PROCESSING` → `COMPLETED` (all succeeded), `COMPLETED_WITH_ERRORS` (some failed), or `FAILED` (all failed, or the job crashed).
Each certificate is `PENDING`, `GENERATED` or `FAILED`. `position` is the recipient's index in the original request, so failures can be mapped back to input rows.

### Retrieve certificates

- One certificate: `GET /api/jobs/{job_id}/certificates/{certificate_id}` returns the PDF. It returns `409` if that certificate failed or isn't ready.
- All generated certificates: `GET /api/jobs/{job_id}/download` returns a ZIP of every generated PDF. It returns `409` if none exist yet.

```bash
curl -o all.zip http://127.0.0.1:8000/api/jobs/<job_id>/download
```

## Design decisions

**Background processing instead of synchronous.** Rendering hundreds of PDFs inside one HTTP request would hold the connection open and risk client/proxy timeouts, so `POST` persists the job, returns `202`, and generation runs as a FastAPI `BackgroundTask`. Clients poll `GET /api/jobs/{id}`. I chose `BackgroundTasks` over Celery/RQ because it needs no broker or extra process and keeps setup to one command. The cost is that an in-flight job is lost if the server restarts, and work stays on a single process. The processing code is isolated in `app/processor.py:process_job(job_id, session_factory)`, so moving it to a real queue worker is a small change.

**Two layers of validation.** Request-level problems (empty list, missing `title`, more than `MAX_RECIPIENTS_PER_JOB`) reject the whole request with `422`, because nothing sensible can be done with it. Recipient-level problems (blank name, bad email) are *not* rejected up front. Every row is stored, and invalid ones are marked `FAILED` with a readable reason, so one typo in a 500-row list doesn't force the client to resubmit everything.

**Failure isolation.** Each certificate is validated, rendered and committed on its own, and any exception while rendering is caught and recorded against that certificate only. Committing per certificate also makes progress visible while the job runs.

**Storage.** The database holds job and certificate metadata plus the original recipient payload. PDFs are written to disk and referenced by path, which keeps the database small. SQLite keeps setup simple, and the code uses plain SQLAlchemy so switching to Postgres is a `DATABASE_URL` change.

**One template.** `app/certificate.py` draws a single A4-landscape template with fpdf2, which is pure Python with no system dependencies.

## Known limitations

- Built-in PDF fonts are Latin-1 only, so names with other scripts (e.g. Chinese) fail for that certificate with a clear error rather than rendering. Supporting them means bundling a Unicode TTF font.
- Background tasks are in-process: jobs that are mid-flight when the server stops stay in `PROCESSING`. A startup sweep or a real queue would fix this.
- No authentication or rate limiting.
- The status endpoint returns every certificate, which is fine at the default 1000-row cap but would need pagination beyond it.

## Project layout

```
app/
  main.py         FastAPI app and startup
  routers.py      HTTP endpoints
  processor.py    Background job: validate, render, record per-certificate outcome
  certificate.py  PDF template rendering
  models.py       SQLAlchemy models and status enums
  schemas.py      Pydantic request/response models and recipient rules
  database.py     Engine and session setup
  config.py       Environment-based settings
tests/            pytest suite
```
