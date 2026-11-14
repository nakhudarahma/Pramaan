# Pramaan Backend

Pramaan answers college notice questions from a reviewed, version-aware fact
ledger. It never lets an unapproved extraction answer a fee, date or eligibility
question, and it abstains when sources conflict or are out of scope.

## Quick start

Run these commands from `C:\Pramaan\Backend`:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env: set JWT_SECRET and ADMIN_*; Gemini/Supabase are optional locally
python -m scripts.migrate
python -m scripts.create_admin
python -m scripts.seed_demo
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for Swagger UI or
`http://127.0.0.1:8000/health` for the health probe.

Demo credentials created by `scripts.seed_demo`:

- Student: `student@example.edu` / `Student123!`
- Admin: the `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`

Change the demo password before exposing the service. The seed script refuses to
run in `ENVIRONMENT=production` without `--force`.

## Tests

```powershell
python -m pytest -q
```

The suite uses a temporary SQLite database, local storage and no Gemini key. It
covers auth, upload/extraction, admin review, conflicts, supersession, calendar,
static citations, unanswered questions, scope rules, lifecycle guards and PDF
signature validation. PDF fixtures require `fpdf2` (included in
`requirements.txt`).

## Configuration

All settings are read from environment variables or `.env`; see `.env.example`.
Important values:

- `DATABASE_URL`: SQLite locally; PostgreSQL in production.
- `JWT_SECRET`: strong random value required in production.
- `STORAGE_BACKEND`: `local` or `supabase`.
- `GEMINI_API_KEY`: optional. Without it, extraction uses a conservative
  heuristic and static answers use a source excerpt.
- `PGVECTOR_ENABLED`: enables the PostgreSQL pgvector column when the extension
  and Python package are available.
- `AUTO_CREATE_TABLES`: convenient locally; use `python -m scripts.migrate` for
  controlled deployments.

## Main API

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `PATCH /api/auth/me/profile` |
| Student | `POST /api/ask`, `GET /api/dashboard`, `GET /api/deadlines`, `GET /api/changes`, `GET /api/notices`, `GET /api/notices/{id}`, `GET /api/notices/{id}/file`, `GET /api/calendar`, `GET /api/calendar/ics` |
| Admin notices | `POST /api/admin/notices`, `GET /api/admin/notices`, `GET /api/admin/notices/{id}`, `PATCH /api/admin/notices/{id}`, `POST /api/admin/notices/{id}/publish`, `POST /api/admin/notices/{id}/archive` |
| Admin review | `GET /api/admin/facts`, `GET /api/admin/facts/{id}`, `PATCH /api/admin/facts/{id}`, `POST /api/admin/facts/{id}/approve`, `POST /api/admin/facts/{id}/reject`, `POST /api/admin/facts/{id}/expire` |
| Admin conflicts | `GET /api/admin/conflicts`, `POST /api/admin/conflicts/{id}/resolve` |
| Admin operations | `GET /api/admin/dashboard`, `GET /api/admin/alerts`, `GET /api/admin/documents`, `GET /api/admin/documents/{id}`, `GET /api/admin/unanswered`, `POST /api/admin/unanswered/{id}/resolve`, `GET /api/admin/audit-logs` |
| Health | `GET /health`, `GET /health/ready`, plus `/api/health` aliases |

Admin routes require a database user with role `admin`. Registration only creates
students.

## Answer behaviour

1. The intent router classifies the question as a volatile structured fact or a
   static policy question.
2. Volatile questions search only `active`, in-scope facts. Duplicate and
   supersession conflicts are resolved before approval.
3. Static questions retrieve only chunks from published notices, then generate a
   grounded answer or return a deterministic excerpt when Gemini is unavailable.
4. Numbers and dates are verified against the cited source. A failed check
   produces an abstention rather than an invented answer.
5. An unanswered question is logged for admin follow-up.

Possible states: `verified`, `static_grounded`, `disputed`, `outdated`,
`unavailable`, `clarification`, `error`.

## Fact lifecycle

`candidate -> active -> superseded | expired | disputed | rejected`

Only one active fact may exist for a given `fact_key` and scope. That invariant
is enforced by a unique `active_scope_key`, not just application checks. Every
edit and lifecycle change creates an immutable `FactVersion` snapshot.

Conflict precedence:

`NEW -> DUPLICATE -> SCOPE_OVERLAP -> SUPERSEDES -> DISPUTED`

## Project layout

```
app/
  api/            FastAPI routes, dependencies, pagination
  core/           security, permissions, errors, logging, rate limiting
  integrations/   Gemini, Supabase and storage adapters
  models/         SQLAlchemy models
  repositories/   focused database queries
  schemas/        Pydantic request/response models
  services/       ingestion, extraction, ledger, retrieval, verification
  utils/          date, text and validation helpers
migrations/       migration notes
scripts/          migrate, create_admin, seed_demo
tests/            unit and integration tests
docs/             evaluation and delivery notes
```

## Operational notes and limits

- Scanned/image PDFs need OCR. OCR is represented by an interface but no OCR
  engine is bundled, so image-only PDFs are flagged for review.
- The local heuristic extractor is intentionally conservative and should be
  reviewed by an administrator. Gemini extraction is optional and requires a
  live key.
- Static retrieval has a lexical fallback for local tests. Embeddings are not
  required for the demo, but production quality improves when Gemini embeddings
  or pgvector are configured.
- Rate limiting is in-process and should be replaced with a shared store when
  running multiple workers.
- No live Supabase or Gemini integration is verified without credentials. Test
  those paths in a staging environment before production.
- PyMuPDF is optional and may be unavailable under restrictive Windows
  application-control policies; `pdfplumber` is the portable fallback.

## Useful commands

```powershell
# Promote/create the configured admin (idempotent)
python -m scripts.create_admin

# Seed the demo student, notice, facts and chunks (idempotent)
python -m scripts.seed_demo

# Prepare the schema without dropping data
python -m scripts.migrate

# Run tests with coverage
python -m pytest --cov=app --cov-report=term-missing
```
