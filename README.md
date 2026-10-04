# Kier's Study Planner

Kier's Study Planner is a web application for planning university studies and tracking academic progress. It uses Hong Kong Baptist University (HKBU) course information and grading conventions to bring course planning, GPA calculations, degree targets and exchange records into one place.

Students can record completed courses, plan future semesters and see how their credits count toward targets they define themselves. The planner keeps earned credits separate from work in progress and future plans.

The project is currently in **beta, version 0.5**. It is an independent project and is not operated by or affiliated with HKBU. Students should check academic decisions against official university records and advice.

## What It Does

- **Plan a study timeline.** Organize courses by academic year and study period. Add summer terms, exchange periods, placement years or additional years as needed.
- **Track courses and grades.** Record planned, in-progress, completed and withdrawn courses, including repeat attempts. View semester GPA and cumulative GPA.
- **Define degree targets.** Set an overall credit target, create nested groups of requirements and assign courses to individual targets. Add minimum-level credit targets when needed.
- **Manage exchange records.** Keep host courses, grades, HKBU equivalents and transfer approval status alongside the study plan. Approved transfer credits contribute to progress without entering GPA calculations.
- **Explore course information.** Search a locally imported HKBU Handbook catalogue by code or title and filter by academic year, level or prefix. Add catalogue courses to a plan or enter courses manually.
- **Keep a personal account.** Use email verification, password recovery and account settings. Export a plan as JSON or permanently delete an account and its planner data.

The interface supports Light, Dark and System themes and works on desktop and mobile screens.

## How Progress Is Calculated

Degree requirements are entered by the student. A programme name does not automatically load or determine graduation requirements. The default overall target is 128 units and can be changed.

A course can count toward more than one target, while overall degree credits count it once under the planner's course-code rules. Groups combine their children's targets, and completing one branch does not compensate for an unfinished sibling. Unknown course levels are excluded from level-based targets rather than guessed from course codes.

Semester GPA includes eligible graded attempts within that period. Cumulative GPA uses the highest numeric grade for each normalized course code through the selected period. Exchange host grades do not affect GPA. The calculation rules and their tests are documented in the [schema and behavior report](schema_report.md) and [release report](report.md).

## Run Locally

Requirements: **Python 3.12 or newer**. Run these commands from the repository directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -c constraints-tested.txt -e ".[dev]"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Open **http://127.0.0.1:8001**.

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell or `.venv\Scripts\activate.bat` in Command Prompt instead of the `source` command.

The default development configuration uses SQLite and records email as local files. If port 8001 is occupied, choose another port and set `APP_BASE_URL` to the matching address before starting the server.

### Create a Plan

1. Register an account. Open the verification email recorded under `data/mailbox/`, follow its link and confirm verification. These `.eml` files can be opened in a text editor or mail client.
2. Sign in and enter your admission year, programme and overall unit target. A new plan starts with four academic years, each containing two semesters; the timeline can then be edited.
3. Create your study targets and add courses or exchange records. The dashboard and progress view update from those records.

The database, mail files and backups are excluded from Git. A fresh clone starts without personal plans or an imported catalogue; manual course entry is available immediately after account setup.

### Populate the Catalogue

Import a specific academic year's public HKBU Handbook data:

```bash
python -m scripts.import_hkbu_courses 2026-2027
```

Add `--dry-run` to preview the import without saving it. Importing requires internet access; ordinary planning and catalogue searches use the local database. Imported versions retain their academic year, and later imports do not rewrite the code, title or units already saved in a student's plan.

For a small set of clearly marked, unverified example courses instead:

```bash
python -m scripts.seed_demo --catalogue-only
```

## Configuration

Set configuration through environment variables. The application does not automatically load `.env` files.

| Variable | Purpose | Development default |
| --- | --- | --- |
| `DATABASE_URL` | Database connection used by the app and migrations | SQLite at `data/study_companion.sqlite3` |
| `ENVIRONMENT` | `development` or `production` | `development` |
| `APP_BASE_URL` | Application address used in account emails | `http://127.0.0.1:8001` |
| `SECRET_KEY` | Persistent signing secret for sessions | Temporary key generated on startup |
| `MAIL_BACKEND` | `file` for local mail or `smtp` for delivery | `file` |
| `MAIL_FILE_DIRECTORY` | Directory for local email files | `data/mailbox` |
| `REGISTRATION_MODE` | `open`, `invite` or `closed` registration | `open` |
| `BETA_INVITE_CODE` | Shared registration code required in invite mode | Unset |

Without a persistent `SECRET_KEY`, restarting the development server signs users out. Closed registration still allows existing users to sign in and recover passwords.

Production requires HTTPS, a persistent signing secret, persistent database storage and SMTP with STARTTLS. SMTP settings include `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM_ADDRESS` and `MAIL_FROM_NAME`. Detailed setup and operating instructions are in the [release report](report.md#before-hosting).

## Administration and Privacy

Each account owns its own planner. Passwords are hashed with Argon2id, account links are single-use, and form changes use CSRF protection.

The private admin console provides account search, verification and recovery email requests, session revocation, disabling and re-enabling accounts, account deletion and an audit log. Admin pages show account metadata and whether a planner exists; they do not provide access to another student's courses, grades, notes or targets.

No account becomes an admin automatically. Grant an existing verified account the role explicitly, replacing `YOUR_USERNAME` with its username or email:

```bash
python -m scripts.set_admin YOUR_USERNAME --grant
```

Sign in again to access `/admin`. The same command supports `--revoke`; revoking the last admin requires `--force`.

Account deletion requires confirmation and removes the owned planner records while retaining shared catalogue data and other users' plans. Audit username snapshots and historical backups can remain after deletion; operators must manage their retention separately.

### Operator Tools

```bash
python -m scripts.backup_db --output-dir data/backups --verify
python -m scripts.verify_backup path/to/backup.sqlite3
python -m scripts.cleanup_account_tokens --older-than-days 30
```

Backups use SQLite's backup API. Token cleanup previews eligible records by default; add `--apply` to remove them. `/health` reports application status, and `/ready` checks database access and the migration revision.

Hosted beta operation currently assumes **one Uvicorn worker** because rate limiting is process-local. Back up existing data and stop writers before applying migrations. See the [release report](report.md) for deployment configuration, maintenance commands and migration verification.

## Development

The application uses FastAPI, SQLAlchemy 2, Alembic and SQLite on the backend, with Jinja2 templates, plain CSS, vanilla JavaScript and local Lucide icons. No Node.js or frontend build step is required.

| Directory | Contents |
| --- | --- |
| `app/models/` | Accounts, catalogue, timeline and planner data models |
| `app/services/` | GPA, credits, progress, account lifecycle and supporting logic |
| `app/routers/` | Application routes |
| `app/templates/` and `app/static/` | Pages, styles, scripts and icons |
| `alembic/` | Database migrations |
| `scripts/` | Catalogue import, administration and maintenance commands |
| `tests/` | Automated tests and local fixtures |

Run the checks with the development dependencies installed:

```bash
python -m pytest -q
python -m ruff check app scripts tests alembic
python -m ruff format --check app scripts tests alembic
python -m alembic check
```

The browser regression suite uses installed Chrome and a temporary database and mailbox:

```bash
python -m scripts.browser_check
```

Tests use local fixtures and fake or mocked email. The v0.5 delivery passed 244 automated tests and browser checks at five desktop and mobile widths; execution details are in [report.md](report.md).

## Current Limits

The planner does not automatically decide graduation eligibility, approve transfer equivalents or infer semester availability. It does not connect to HKBU student accounts or course registration. JSON export is available; JSON import, PDF and Excel export are not implemented.

The project is in beta. Public hosting and real email delivery require operator setup, and multi-worker deployment needs changes to rate limiting and the database strategy.

## Further Documentation

- [Release report](report.md): implemented scope, verification results and operating instructions.
- [Schema report](schema_report.md): database tables, relationships, constraints and calculation behavior.
- [Earlier release reports](docs/releases/): historical upgrade and verification records.
