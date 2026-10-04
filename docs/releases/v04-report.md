# Kier's Study Planner v0.4 Delivery Report

Public copy: personal academic figures, ownership identifiers and installation-specific record counts have been omitted. Browser/test examples below use synthetic data.

Verified 2026-10-04, Asia/Hong_Kong.

## Project State

The v0.4 email verification and recovery upgrade is implemented. At verification, health returned {"status":"ok","version":"0.4.0"} and sign-in returned HTTP 200.

The existing FastAPI / SQLAlchemy / Alembic / SQLite / Jinja2 / plain CSS / vanilla JavaScript architecture is preserved. No frontend framework, vendor SDK, public deployment, catalogue re-import, credential reset or academic-data rewrite was performed. The workspace is not a Git repository, so no commit was created.

Public copies of the previous reports, with private installation details omitted, are available as [v03-report.md](v03-report.md) and [v03-schema-report.md](v03-schema-report.md).

## Branding and Accounts

- SITE_NAME in app/config.py centralizes **Kier's Study Planner** across titles, header, footer, authentication pages and account email subjects. The footer retains the independence disclaimer. HKBU academic terms, Handbook/outline provenance and official source links remain.
- Accounts retain normalized unique email and username, Argon2id password hashes, theme and timestamps. Sign-in accepts username or email. Registration/recovery/change share the 12-1024 character password policy.
- Registration creates an unverified user and sends a verification message, then opens Check your email. Unverified credentials grant only a restricted pending-verification session; academic routes and export remain unavailable.
- Existing accounts are grandfathered as verified by migration. This preserves access without pretending that historical email ownership was independently checked.
- Verification links expire after 24 hours. GET validates and redirects to a query-free confirmation page without mutating database state; CSRF-protected POST verifies the email, consumes tokens and requires sign-in.
- Resend issues a replacement link and invalidates older verification links. There is no immediate email-change UI.
- Forgot-password accepts email only and shows the same public response for eligible, nonexistent and unverified addresses. Only verified accounts receive recovery links. Unverified users use credential sign-in and resend verification.
- Reset links expire after 30 minutes. A successful POST replaces the Argon2id hash, consumes/invalidate all resets, increments auth_version, clears the current session and requires fresh login. Existing signed-in sessions are revoked on their next protected request.
- Profile links to Change password. It requires the current password, applies the same policy, invalidates outstanding resets, increments auth_version, refreshes the current session and revokes other sessions.
- Password reset/change sends an account-security notification. Email never contains academic records, grades, marketing or newsletters.

## Token and Mail Security

The generic account_tokens table stores a SHA-256 digest, never the raw token. Tokens use secrets.token_urlsafe(32), are user/purpose-bound, and are consumed with an atomic conditional UPDATE checking both expiry and unused state. Consumption, account mutation and invalidation share a transaction. Other-purpose tokens cannot be used interchangeably.

Signed HTTP-only SameSite=Strict cookies hold session identity/version or restricted token-digest context. Production adds Secure. All mutations use CSRF. All protected routes enforce ownership, verification and the database session version. JSON export excludes credentials, tokens, verification timestamps and auth_version.

SMTP is vendor-neutral Python smtplib with certificate-validated STARTTLS, EHLO, optional authentication and a transport timeout. Local development uses private .eml files outside web serving: directory 0700, files 0600. Tests use a fake mailbox or mocked transport; browser checks use an isolated temporary mailbox. **No real email was sent and no SMTP provider/inbox deliverability was tested.**

Mail delivery runs as a post-response background task. This removes SMTP latency from the public recovery response, but does not promise constant-time database processing. Delivery failures log only a generic configuration/transport message, without exception text, recipients, credentials or token URLs. There is no durable queue or automatic retry.

App access logging strips verification/reset query strings. Pages use no-referrer and no-store; SQLAlchemy hides bound parameters in exception output. Reverse-proxy, custom application and infrastructure logging must independently avoid recording bearer URLs.

Production startup validates a persistent signing secret, public HTTPS base origin, SMTP host/port, sender, paired credentials and TLS. It does not test remote SMTP reachability. Links use APP_BASE_URL, not an untrusted request Host.

### Rate Limits

Bounded fixed-window process-local limiter with hashed keys, locking, expiry pruning, a 10,000-bucket capacity and fail-closed capacity handling. HTTP 429 includes Retry-After.

| Action | Per IP | Per normalized account/context | Window |
| --- | ---: | ---: | --- |
| Login | 120 | 10 per identifier | 10 minutes |
| Registration | 20 | 5 per email | 1 hour |
| Verification resend | 30 | 3 per email | 15 minutes |
| Reset request | 30 | 3 per email | 15 minutes |
| Reset or verification submission | 30 | 8 per signed digest | 15 minutes |
| Password change | 30 | 8 per account ID | 15 minutes |

Limits reset on process restart and are not shared across workers/hosts. Run one worker for this design; use a shared limiter before scaling. Campus/shared-IP users can reach IP limits. Configure proxy trust explicitly rather than trusting arbitrary forwarding headers.

## Targets and Progress

Targets retains its existing database values: own_target is now **Single target** and sum_children is **Group of targets**. No target schema or existing hierarchy was changed.

Default category rows show a drag handle, name, textual type, units, a group's direct child count, and an overflow menu. Edit opens a dialog; group units are derived and read-only. Move to group opens a hierarchy selector, excluding self/descendants. Move to top level, up/down and Delete remain available without dragging. Permanent indent/outdent and arrow clutter is removed. Minimum-level requirements remain separate editable cross-cutting targets.

Existing handle-only drag/drop still supports sibling ordering, nesting, cross-group moves and returning to the root. The server validates the complete owned tree atomically, rejecting foreign IDs, cycles, self-parenting, sibling collisions and invalid container allocations. Parent deletion remains blocked while children exist; leaf deletion removes allocations, not courses.

Groups collapse on Targets, Dashboard and Progress. Expansion state is persisted in localStorage, scoped by user, profile and view. Dashboard uses group chevrons, a smaller child marker for nested Single targets and no marker for standalone targets. Collapse does not alter calculations.

Course forms use **Counts toward / Target**, display paths in tree order and disable groups. Allocation overlap remains possible without inflating physical degree credit.

The overall bar separates **Earned** (green), **In progress** (blue), **Planned** (neutral) and **Remaining** (empty track), with numeric text labels in both themes. It reuses physical code deduplication with earned > in progress > planned precedence. Passing grades, S/DT and approved transfers are earned; pending/planned transfers are planned. Remaining never becomes negative, and only visual widths cap at 100%; real totals are retained.

Course Explorer's 50-row filtered pagination, academic-year versions, provenance, keyboard/mouse autocomplete, manual entry, historical snapshots, Light/Dark/System preferences, GPA/cGPA, exchange handling and JSON export all remain covered by regression checks.

## Database Migration

Current revision: **d94a23e71f58**, parent **c83f12d60e47**.

New schema:
- users.email_verified_at: nullable DateTime(timezone=True).
- users.auth_version: non-null Integer, Python/server default 0, CHECK >= 0.
- account_tokens: id PK; user_id FK users.id ON DELETE CASCADE; purpose VARCHAR(20) with verify_email/reset_password CHECK; unique token_hash VARCHAR(64); created_at, expires_at and nullable consumed_at timestamps.
- Nonunique indexes on (user_id, purpose) and expires_at.
- User.account_tokens uses all/delete-orphan with passive_deletes=True. AccountToken.user uses default save-update/merge. Existing profile ownership still prevents deleting a user with a profile.
- All other tables, constraints and relationships remain unchanged. [schema_report.md](v04-schema-report.md) documents every column, constraint, index and cascade.

The full original suite passed **156 tests before modification**. A private backup was made and the migration rehearsed on a copy before upgrading the live database.

Every original column was compared, including account timestamps, credentials, ownership, theme, target hierarchy, snapshots and allocations. The same old-column comparison passed before and after live migration, and academic totals were preserved. Personal values, ownership IDs and installation-specific row counts are omitted from this public copy.

Integrity and FK checks passed; Alembic metadata comparison reported no operations. Downgrade is intentionally refused to prevent loss of security state. Restoration requires a compatible private backup and matching application code.

## Executed Verification

| Check | Result |
| --- | --- |
| v0.3 baseline | 156 passed |
| Final automated tests | **196 passed** |
| Ruff lint | Passed |
| Ruff format check | Passed, 72 files |
| Alembic current | d94a23e71f58 (head) |
| Alembic check | No new upgrade operations |
| Dependency check | No broken requirements |
| Populated v0.1, v0.2 and v0.3 migrations | Passed |
| Real-database rehearsal and live old-column comparison | Passed |
| SQLite integrity / foreign keys | ok / no violations |
| Schema report against live database | All 14 tables and 112 columns match in physical order |
| Documentation links | All local links resolve |
| Isolated Chrome workflows | Passed |
| Viewports | 320, 390, 768, 1440, 1920 |
| Browser JS errors / unexpected failed responses | 0 / 0 |
| Local health / sign-in | 0.4.0 / HTTP 200 |

New tests cover hashed tokens, expiry, wrong purpose, single use, POST/CSRF, resend invalidation, all rate-limit operations, generic recovery responses, verified/unverified access, email/username login, reset/change policy, old-password rejection, old-session revocation, current-session retention, token constraints/cascade, private mailbox permissions, SMTP TLS call order, safe error logging, production configuration failures, migration preservation, physical progress-state semantics, visual capping, overlap/deduplication and new hierarchy move validation.

Browser checks register, follow the local test verification email, confirm by POST, sign in, sign out, request/use a recovery link, reject the old password, accept the new password and change it through settings. They also exercise compact menus, edit/move dialogs, native pointer drag/drop, top-level moves, collapse persistence, disabled group allocation options, page/history navigation, autocomplete, manual entries, all three themes, retained GPA/exchange/export workflows, and mobile menu/dialog bounds.

The intentional old-password browser rejection is HTTP 422 and expected. No unexpected failed response occurred. The final isolated plan has **12 earned, 3 in progress, 3 planned, 110 remaining, 18 projected and 3.50 cGPA**. All four visual segment widths were checked as nonzero. Tests did not modify live academic data.

Desktop/mobile screenshots were visually inspected during verification. They remain local verification artifacts excluded from Git.

## Run and Configure

Current development instance: **http://127.0.0.1:8001**. It is already running with the file mailbox backend, not a real SMTP provider.

Exact local run command from this workspace:

```bash
bin/alembic upgrade head
ENVIRONMENT=development APP_BASE_URL=http://127.0.0.1:8001 MAIL_BACKEND=file bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Use another free port and matching APP_BASE_URL if occupied. Development mail defaults to data/mailbox; override with MAIL_FILE_DIRECTORY. SECRET_KEY is optional locally; without a persistent value, restart invalidates sessions. The default DATABASE_URL points to the existing local SQLite file. No .env loader is present.

Hosted configuration after loading secrets, with example domains/paths replaced:

```bash
export ENVIRONMENT=production
export SECRET_KEY="${SECRET_KEY:?Load a persistent random secret of at least 32 characters}"
export APP_BASE_URL=https://planner.your-domain.example
export MAIL_BACKEND=smtp
export SMTP_HOST=smtp.your-provider.example
export SMTP_PORT=587
export SMTP_USERNAME="${SMTP_USERNAME:?Load SMTP username}"
export SMTP_PASSWORD="${SMTP_PASSWORD:?Load SMTP password}"
export SMTP_USE_TLS=true
export MAIL_FROM_ADDRESS=planner@your-domain.example
export MAIL_FROM_NAME="Kier's Study Planner"
export DATABASE_URL=sqlite:////absolute/persistent/path/study_companion.sqlite3
bin/alembic upgrade head
bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

This command assumes a configured HTTPS proxy and persistent volume; it is not a deployment. MAIL_FILE_DIRECTORY is development-only. SMTP credentials can both be omitted for a correctly authorized relay. Only SMTP with STARTTLS is implemented, not implicit-TLS port 465. Keep backups and all local mailbox files private.

Verification commands:

```bash
bin/pytest -q
bin/ruff check app scripts tests alembic
bin/ruff format --check app scripts tests alembic
bin/alembic check
bin/python -m pip check
bin/python -m scripts.browser_check
```

## Remaining Limits

This is an independent student planner, not an official HKBU audit/approval service. Targets and equivalencies are student-controlled; semester availability is not inferred and catalogue data may require refresh. Unknown levels remain conservative.

No email-change UI, OAuth/HKBU SSO, timetable integration, JSON restore, Excel/PDF export, marketing or general notification system was added. Recovery depends on configured mail delivery. There is no durable mail queue, scheduled token cleanup or distributed rate limiter. Public hosting requires HTTPS, persistent storage, backups, production secrets, trusted proxy configuration, sender-domain setup and a real delivery test.

External SQL writers must preserve same-profile ancestry, acyclicity and allocation bounds; application validation is not a database composite constraint. User/profile deletion is not exposed and existing RESTRICT safeguards remain. Native drag/drop is desktop-oriented; mobile/keyboard users have menu actions. Validation used macOS, Python 3.14 and installed Chrome; other browser/OS matrices and public SMTP were not tested.

Security implementation references: [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html) for single-use recovery, generic responses and session invalidation; [Python smtplib documentation](https://docs.python.org/3/library/smtplib.html) for SMTP/STARTTLS transport.

An additional optional HTTP probe of live Uvicorn query redaction was not executed: automatic tool approval could not complete because its usage quota was exhausted. Redaction is implemented and its automated LogRecord tests passed; the separate live-log probe remains unverified. Health/sign-in and the full isolated browser suite had already completed successfully. Operator approval/tool availability is needed before that optional probe can be retried.
