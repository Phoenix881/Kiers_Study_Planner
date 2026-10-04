# Kier's Study Planner v0.5 Delivery Report

Public copy: personal academic figures, ownership identifiers and installation-specific record counts have been omitted. Browser/test examples below use synthetic data.

Verified 2026-10-04, Asia/Hong_Kong.

## Project State

The incremental hosted-beta upgrade is implemented, migrated and running at **http://127.0.0.1:8001**. The existing FastAPI/SQLAlchemy/Alembic/SQLite/Jinja2/CSS/vanilla-JavaScript stack is retained. No frontend build, cloud SDK, analytics, scheduler, Redis, PostgreSQL or durable mail queue was added. This is a locally verified release, not a public deployment or a 300-user load certification.

**244 automated tests passed**, plus the complete isolated Chrome regression suite. Live revision: **e05b34f82a69**, parent **d94a23e71f58**. Every pre-existing database column and every profile GPA/credit total was preserved. Admin bootstrap is an explicit operator choice, never a migration side effect.

Public copies of previous reports, with private installation details omitted: [v0.4 delivery](docs/releases/v04-report.md) and [v0.4 schema](docs/releases/v04-schema-report.md). The previous delivery's optional live access-log redaction probe was successfully retried before the upgrade; it also passes on the final v0.5 server.

## Implemented Scope

| Area | Behavior |
| --- | --- |
| User schema | is_admin/is_disabled BOOLEAN NOT NULL DEFAULT 0; nullable disabled_at, disabled_reason VARCHAR(500), last_login_at; boolean/reason-length checks |
| Identity safety | users.id AUTOINCREMENT prevents deleted IDs being reused by future accounts with stale signed cookies |
| Bootstrap | Exact normalized username/email CLI grant/revoke; no account creation; last-admin revocation requires --force; changed roles revoke sessions/resets |
| Authorization | Every admin route requires authenticated, verified, enabled, is_admin and valid auth_version; normal users have no Admin navigation |
| Overview | Account/profile-existence counts, outstanding token counts, application version/revision/readiness and ten recent accounts |
| User list/detail | Normalized username/email search, seven filters, 50-row server pagination; account metadata only |
| Admin mail | Existing token service/limits, CSRF POST and confirmation; no token display or admin-selected password |
| Session revocation | Increments auth_version, cancels reset links; preserves credentials, verification and planner data |
| Disable/re-enable | Disable sets time/reason, increments version and cancels verification/reset links; enable clears time/reason without reducing version |
| Login tracking | UTC timestamp only on full verified enabled login; conditional security-state check handles concurrent reset/disable/revoke |
| Self-deletion | Profile link, current password, exact DELETE, CSRF; transactional deletion, session clearing, neutral goodbye page |
| Admin deletion | Another account only, separate confirmation page, target identity shown, exact username or DELETE; shared deletion service |
| Audit | Nullable actor/target SET NULL FKs, username snapshots, bounded action/details, UTC time; admin-only paginated history survives deletion |
| Readiness | /health stays lightweight; /ready checks SELECT 1 and exact single Alembic head; generic 200 ready or 503 not_ready, version 0.5.0 |
| Backups | SQLite backup API, private timestamped files, integrity/FK checks, recognized-name-only optional retention; no automatic restore |
| Token cleanup | Dry-run by default, configurable 30-day retention, count-only output; valid unused tokens are retained |
| Registration | open/invite/closed; constant-time shared-code comparison; missing invite code fails startup; closed mode preserves login/recovery |
| Errors/logging | Branded 403/404/generic 500, generated request ID, query-free access logs, exception class/structural stack without secrets |

Console routes: `/admin`, `/admin/users`, `/admin/users/{id}`, `/admin/audit`, plus confirmation pages and POST actions under `/admin/users/{id}`. Self-deletion: `/account/delete`. No grades, courses, exchange details, targets, notes, academic progress or other-user exports are exposed to admins. No impersonation, web role-grant or SQL tool exists. The operator's own normal planner uses ordinary ownership checks.

Disabling blocks correct-password login and every subsequent protected request, password changes and account mail. Forgot-password remains generic and sends nothing for disabled accounts. Re-enabling requires fresh login. Admins cannot revoke, disable or delete themselves in the console. Ordinary self-deletion remains available; the last-admin guard applies to CLI role revocation, not self-deletion.

Audit snapshots intentionally retain usernames after deletion. Mail events record a request, not proof of inbox delivery. CLI role events use NULL actor and snapshot `operator CLI`. Failed actions do not log success. No credentials, token material, academic content, invite code or submitted disable reason is copied to audit details.

## Migration Preservation

The v0.4 baseline passed **196 tests in 20.61 seconds** before implementation. A consistent private backup was made before migration, and the upgrade was rehearsed on a copy.

Every pre-existing column was compared, including account timestamps, ownership, snapshots, target hierarchy, notes and allocations. Academic totals, integrity/FK checks and Alembic comparison passed. Existing verification, credentials, auth_version and themes were preserved. The migration creates no admin or disabled accounts automatically; the new nullable account fields start NULL.

The old development server was stopped before live migration. The live database still matched the backup immediately before upgrading, and the complete old-column and academic-total comparison passed afterward. Personal values, ownership IDs and installation row counts are not reproduced in this public report.

The backup utility also created and verified a post-upgrade copy. Integrated and independent verification passed. Live token cleanup was preview-only and made no changes.

### Deletion Rehearsal

On a migrated copy of the private backup, the service deleted the selected account and only its owned planner graph. Unrelated profiles retained their academic totals, and shared catalogue rows were unchanged. FKs remained enabled and valid. The temporary copy was discarded; live academic data was not deleted.

Tests cover no/empty profile, periods/years, normal/exchange entries, multiple allocations, nested targets, level requirements, tokens, other users, unclaimed profiles, shared catalogue and audit survival for deleted actors/targets. A **1,050-node target chain** is removed iteratively deepest-first to satisfy RESTRICT, without recursive Python traversal or disabling FKs. Injected mid-transaction failure restores all rows, version and audit state. Cross-profile normal/exchange allocations created by external SQL fail closed instead of cascading into another planner's data. Old signed cookies cannot become valid through user-ID reuse.

## Verification

| Check | Result |
| --- | --- |
| v0.4 baseline / final tests | 196 passed / **244 passed in 30.19 seconds** |
| Ruff lint / format | Passed / 90 files formatted |
| Dependency check | No broken requirements |
| Alembic current / check | e05b34f82a69 head / no new operations |
| Populated migration regressions | v0.1, v0.2, v0.3 and v0.4 upgrades pass |
| Copied/live preservation | All old columns, ownership and academic totals match |
| SQLite integrity / FKs | ok / no violations |
| Schema documentation | All 16 tables and 127 columns match in physical order/type/nullability/PK flags, including sqlite_sequence; every explicit index and CHECK covered |
| Backup tests | Live WAL source, source preservation, file permissions, verification, destination failures and retention boundaries pass |
| Token/gate/readiness tests | Dry/apply cleanup, registration modes/startup checks, DB failure and revision mismatch pass |
| Security tests | Admin/disabled/stale-session/CSRF guards, audit privacy, generic secret-free errors, request IDs and concurrent-login checks pass |
| Final Chrome suite | Passed, zero JavaScript errors or unexpected failed responses |
| Responsive widths | 320, 390, 768, 1440, 1920 |
| Final local HTTP checks | /health and /ready 0.5.0, login 200, unauthorized /admin redirects to login |
| Live access-log probe | Synthetic recovery query absent; query-free request line present |

Browser tests use a disposable database, fake file mailbox and local catalogue fixtures, never real SMTP or live planner mutation. They exercise CLI bootstrap, admin navigation, metadata privacy, overview/search/detail, verification/reset requests, revoke, disable/access loss/re-enable/login, audit actions and self-action restrictions. Self-deletion creates a planner, course, nested targets and allocation; wrong password/confirmation fail before valid deletion. Deleted accounts cannot log in, personal rows are gone, catalogue rows remain, and another user's stored export is unchanged, excluding only the generated export timestamp.

Retained browser coverage includes registration/verification/recovery/password change, GPA/repeats, exchange, JSON export, nested target drag/menu actions, collapse persistence, catalogue pagination/history, autocomplete/manual entry, all themes and four-state progress. The retained plan still has **12 earned, 3 in progress, 3 planned, 110 remaining, 18 projected and 3.50 cGPA**.

### Screenshots

Administration, account deletion and retained planner screenshots were visually inspected during verification. Document overflow and button-text bounds were checked at all five viewport widths. Screenshots remain local verification artifacts excluded from Git.

## Local Run and Operations

The final instance is already running at **http://127.0.0.1:8001**, one worker, file mailbox and open registration. Exact restart command after stopping that instance:

```bash
bin/alembic upgrade head
ENVIRONMENT=development APP_BASE_URL=http://127.0.0.1:8001 MAIL_BACKEND=file REGISTRATION_MODE=open bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

Use another free port and matching APP_BASE_URL if occupied. Without a persistent SECRET_KEY, development restarts invalidate sessions. Mail defaults to private `data/mailbox`; never web-serve or publish these files.

Choose an existing verified account, replace YOUR_USERNAME, then explicitly grant admin and sign in again:

```bash
bin/python scripts/set_admin.py YOUR_USERNAME --grant
bin/python scripts/set_admin.py YOUR_USERNAME --revoke
bin/python scripts/backup_db.py --output-dir /srv/backups --verify --keep 14
bin/python scripts/verify_backup.py /srv/backups/kiers-study-planner-YYYYMMDDTHHMMSSffffffZ.sqlite3
bin/python scripts/cleanup_account_tokens.py --older-than-days 30
bin/python scripts/cleanup_account_tokens.py --older-than-days 30 --apply
```

Commands honor DATABASE_URL. Backup paths/filename above are placeholders; use a private operator-controlled directory. Retention verifies the new copy before pruning only matching regular non-symlink files. No restore is automated. Token cleanup is default dry-run, removes expiry/consumption older than retention, and never prints token contents.

### Before Hosting

After loading secrets from the deployment secret store, replace example hosts/paths and configure a trusted HTTPS reverse proxy:

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
export REGISTRATION_MODE=closed
bin/python scripts/backup_db.py --output-dir /srv/backups --verify
bin/alembic upgrade head
bin/alembic check
bin/python scripts/set_admin.py YOUR_USERNAME --grant
bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

Register/verify the chosen operator before closing registration, or provision locally before production startup. For invite mode, load BETA_INVITE_CODE as a secret, set REGISTRATION_MODE=invite and restart; a missing code fails validation. Closed mode affects registration only. Configure proxy trust, upstream query redaction and no auth/admin body logging; verify `/ready`, test real sender/inbox delivery, arrange private off-host backup retention and rehearse restore into an isolated environment before opening registration. No deployment or external scheduler was configured here.

## Remaining Limits

- One worker and one SQLite-backed instance are assumed. Rate limits reset on restart. Multiple workers/hosts need shared limiting and a suitable database strategy; capacity/load was not certified.
- Mocked SMTP and configuration are tested, but provider reachability, sender DNS, inbox deliverability, public TLS/proxy configuration and hosting remain operator work. There is no durable queue or automatic mail retry; resend after limits permit.
- Deletion is irreversible in-app. Audit username snapshots intentionally survive. Historical backups, development mail and browser-local state are not scrubbed by deletion; manage these under a separate retention policy. The last admin can self-delete and would need explicit replacement bootstrap.
- External SQL writers can bypass cross-column ownership/tree/allocation invariants. Detected corruption fails closed for operator repair. FK disabling is confined to the existing validated Alembic table-copy migration mechanism, never account deletion.
- /ready checks connectivity and revision, not disk capacity, SMTP, every table's health or backup freshness. Safe error logs omit exception text/source/locals, so some diagnosis requires controlled reproduction.
- No email-change UI, OAuth/HKBU SSO, JSON restore, PDF/Excel export, marketing, general notifications, analytics, curriculum administration or impersonation. Existing independent-planner/academic-verification limitations remain.
- Verification used macOS, Python 3.14 and installed Chrome. Other browser/OS matrices were not tested. Admin roles require explicit bootstrap.

See [schema_report.md](schema_report.md) and [README.md](README.md) for the exact schema and full operating reference. Backup implementation follows the [SQLite Online Backup API](https://www.sqlite.org/backup.html) and [Python sqlite3 backup interface](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
