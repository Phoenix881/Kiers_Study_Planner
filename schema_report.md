# Database Schema Report: Kier's Study Planner v0.5

Public copy: personal academic figures, ownership identifiers and installation-specific record counts have been omitted. Browser/test examples below use synthetic data.

Verified 2026-10-04 against SQLAlchemy metadata, the Alembic migration chain, and read-only inspection of `data/study_companion.sqlite3`.

## Revision and Scope

- Current database revision and Alembic head: `e05b34f82a69`.
- Parent revision: `d94a23e71f58`.
- Migration: `alembic/versions/e05b34f82a69_beta_administration.py`.
- Full chain: `8884a9a3ad86 -> b72e91a40c26 -> c83f12d60e47 -> d94a23e71f58 -> e05b34f82a69`.
- 14 mapped application tables plus Alembic's `alembic_version`: 125 columns. SQLite also maintains the two-column internal `sqlite_sequence` table for non-reused user IDs.
- `StudentProfile` is also exposed as `AcademicProfile`; `Term` as `StudyPeriod`. These aliases do not create additional tables.
- `StudentProfile.entry_academic_year` is a synonym for physical column `admission_year`.
- No SQL curriculum-definition or curriculum-rule tables exist. Legacy JSON files under `app/curricula/` are archival/reference data. Live progress uses profile-owned targets and allocation tables.
- `alembic check` reports no new upgrade operations. `PRAGMA foreign_key_check` returns no violations.

## Text ER Diagram

```text
users (User account)
  1 -- * admin_audit_log.admin_user_id (nullable actor, ON DELETE SET NULL)
  1 -- * admin_audit_log.target_user_id (nullable target, ON DELETE SET NULL)
  1 -- * account_tokens (hashed verification / recovery tokens, ON DELETE CASCADE)
  1 -- 0..1 student_profiles (AcademicProfile / StudentProfile)
             | 1 -- * academic_years
             |           1 -- * terms (StudyPeriod / Term)
             |                  | 1 -- * plan_courses (normal attempts)
             |                  |          | * -- 0..1 courses (stable identity)
             |                  |          | * -- 0..1 course_versions
             |                  |          1 -- * plan_course_allocations -- *:1 requirement_groups
             |                  |
             |                  1 -- * exchange_courses
             |                             | * -- 0..1 courses (specific equivalent)
             |                             1 -- * exchange_course_allocations -- *:1 requirement_groups
             |
             | 1 -- * requirement_groups (student-defined category targets)
             |           1 -- * requirement_groups.children (nullable parent_id, RESTRICT)
             | 1 -- * level_requirements (student-defined minimum-level targets)
             1 -- * terms (direct profile FK retained)

courses 1 -- * course_versions (one version per known academic year)
student_profiles.curriculum_key .. legacy app/curricula/*.json (no FK, not live authority)
alembic_version (migration tracking only)
sqlite_sequence (SQLite-managed AUTOINCREMENT state, not ORM mapped)
```

A legacy unclaimed profile has no user. A term's academic-year FK is nullable in storage for compatibility, but every migrated term and every period created by the v0.2 UI has a year. Course-to-version consistency, period-to-profile consistency, and allocation ownership are enforced by application write paths, not composite database FKs.

## Column and Constraint Conventions

All columns are listed below. SQL types are the inspected SQLite declarations; ORM types preserve SQLAlchemy details such as timezone-aware DateTime. Python defaults and `onupdate` functions run through SQLAlchemy, not raw SQL. There are no database-generated timestamps. The only application-table SQL server defaults are `users.theme_preference = 'system'`, `users.auth_version = 0`, `users.is_admin = 0`, `users.is_disabled = 0`, and `requirement_groups.aggregation_mode = 'own_target'`.

`users.id` explicitly uses SQLite AUTOINCREMENT; other integer primary keys use implicit rowid allocation. SQLite does not enforce VARCHAR length or fixed Numeric scale by itself; form validation supplies bounds. The new disabled_reason and audit details also have explicit length CHECKs. Nullable fields accept SQL NULL. Boolean columns compile to BOOLEAN and are constrained to 0/1.

Named constraints below are the names in the migrated local database. Unnamed legacy checks were named during SQLite table-copy migration to preserve them. ORM-created test databases can have equivalent unnamed constraints. Unique constraints also create SQLite internal autoindexes; the explicit indexes section lists only application-declared indexes.

Relationship cascade `save-update, merge` is SQLAlchemy's default and does not delete related objects. `all, delete-orphan` expands to `delete, delete-orphan, expunge, merge, refresh-expire, save-update`. Database ON DELETE actions also apply to direct SQL when FK enforcement is enabled. No relationships specify a separate ON UPDATE action.

## `users` (User)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `email` | `VARCHAR(254)` | `String(length=254)` | No | No | None |
| `username` | `VARCHAR(80)` | `String(length=80)` | No | No | None |
| `password_hash` | `VARCHAR(255)` | `String(length=255)` | No | No | None |
| `created_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now` |
| `updated_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now`; onupdate: `utc_now` |
| `theme_preference` | `VARCHAR(10)` | `String(length=10)` | No | No | `'system'` |
| `email_verified_at` | `DATETIME` | `DateTime(timezone=True)` | Yes | No | None |
| `auth_version` | `INTEGER` | `Integer()` | No | No | `0` |
| `is_admin` | `BOOLEAN` | `Boolean()` | No | No | `False` |
| `is_disabled` | `BOOLEAN` | `Boolean()` | No | No | `False` |
| `disabled_at` | `DATETIME` | `DateTime(timezone=True)` | Yes | No | None |
| `disabled_reason` | `VARCHAR(500)` | `String(length=500)` | Yes | No | None |
| `last_login_at` | `DATETIME` | `DateTime(timezone=True)` | Yes | No | None |

Primary key: `id` (unnamed, explicit SQLite AUTOINCREMENT). SQL server defaults: `theme_preference = 'system'`, `auth_version = 0`, `is_admin = 0`, `is_disabled = 0`.

Foreign keys:

- None.

Unique constraints:

- `(email)`; unnamed.
- `(username)`; unnamed.

Check constraints:

- `theme_preference IN ('system', 'light', 'dark')`; name `ck_user_theme`.
- `auth_version >= 0`; name `ck_user_auth_version`.
- `is_admin IN (0, 1)`; name `ck_user_admin`.
- `is_disabled IN (0, 1)`; name `ck_user_disabled`.
- `disabled_reason IS NULL OR length(disabled_reason) <= 500`; name `ck_user_disabled_reason`.

Explicit indexes:

- None beyond PK/unique-constraint internal indexes.

SQLAlchemy relationships:

- `profile` -> `StudentProfile`: scalar one-to-one (uselist=False; ownership FK is unique); back_populates: `user`; cascade: `save-update, merge`; passive_deletes: `all`; order_by: none.
- `account_tokens` -> `AccountToken`: one-to-many collection; back_populates: `user`; cascade: `all, delete-orphan`; passive_deletes: `true`; order_by: none.

## `admin_audit_log` (AdminAuditLog)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `admin_user_id` | `INTEGER` | `Integer()` | Yes | No | None |
| `admin_username_snapshot` | `VARCHAR(80)` | `String(length=80)` | No | No | None |
| `target_user_id` | `INTEGER` | `Integer()` | Yes | No | None |
| `target_username_snapshot` | `VARCHAR(80)` | `String(length=80)` | No | No | None |
| `action` | `VARCHAR(30)` | `String(length=30)` | No | No | None |
| `details` | `VARCHAR(500)` | `String(length=500)` | Yes | No | None |
| `created_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now` |

Primary key: `id` (unnamed). SQL server defaults: none. Unique constraints: none.

Foreign keys:

- `(admin_user_id) -> users(id)`; ON DELETE `SET NULL`; unnamed.
- `(target_user_id) -> users(id)`; ON DELETE `SET NULL`; unnamed.

Check constraints:

- `action IN ('send_verification', 'send_password_reset', 'revoke_sessions', 'disable_user', 'enable_user', 'delete_user', 'grant_admin', 'revoke_admin')`; name `ck_admin_audit_action`.
- `details IS NULL OR length(details) <= 500`; name `ck_admin_audit_details`.

Explicit indexes:

- `ix_admin_audit_log_admin_user_id` on `(admin_user_id)`; nonunique.
- `ix_admin_audit_log_target_user_id` on `(target_user_id)`; nonunique.
- `ix_admin_audit_created_id` on `(created_at, id)`; nonunique.

SQLAlchemy relationships:

- `admin` -> `User`: many-to-one nullable scalar; explicit foreign_keys: `admin_user_id`; no back_populates; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `target` -> `User`: many-to-one nullable scalar; explicit foreign_keys: `target_user_id`; no back_populates; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.

No User-side audit collection exists. Database SET NULL preserves audit rows when either account is removed. Snapshots intentionally retain usernames after deletion. CLI role changes use a NULL actor and snapshot `operator CLI`. Web actions and their audit event commit in one transaction. Failed actions create no success event. Details are a fixed mail-request note or NULL in current write paths; passwords, token material, academic contents, invite codes and submitted disable reasons are never copied into audit rows. SQL cannot enforce this semantic privacy rule for arbitrary external writers.

## `account_tokens` (AccountToken)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `user_id` | `INTEGER` | `Integer()` | No | No | None |
| `purpose` | `VARCHAR(20)` | `String(length=20)` | No | No | None |
| `token_hash` | `VARCHAR(64)` | `String(length=64)` | No | No | None |
| `created_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now` |
| `expires_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | None |
| `consumed_at` | `DATETIME` | `DateTime(timezone=True)` | Yes | No | None |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(user_id) -> users(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- `(token_hash)`; unnamed.

Check constraints:

- `purpose IN ('verify_email', 'reset_password')`; name `ck_account_token_purpose`.

Explicit indexes:

- `ix_account_tokens_user_purpose` on `(user_id, purpose)`; nonunique.
- `ix_account_tokens_expires_at` on `(expires_at)`; nonunique.

SQLAlchemy relationships:

- `user` -> `User`: many-to-one scalar; back_populates: `account_tokens`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.

The ORM deletes orphaned tokens removed from User.account_tokens. Deleting a user with an unloaded token collection relies on the database CASCADE; loaded tokens can be deleted by the ORM. The existing profile RESTRICT FK still prevents deleting an account that owns a profile.

Neither hashing nor timestamp ordering is a database CHECK. SQLite also does not enforce the VARCHAR length. Only application token creation produces 64-character SHA-256 hex digests and valid expiry times. No raw-token column exists; direct SQL writers must preserve these invariants.

## `student_profiles` (StudentProfile)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `admission_year` | `VARCHAR(9)` | `String(length=9)` | No | No | None |
| `programme_name` | `VARCHAR(200)` | `String(length=200)` | No | No | None |
| `minor_name` | `VARCHAR(200)` | `String(length=200)` | Yes | No | None |
| `required_total_units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | `128` |
| `curriculum_key` | `VARCHAR(100)` | `String(length=100)` | Yes | No | None |
| `created_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now` |
| `updated_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now`; onupdate: `utc_now` |
| `user_id` | `INTEGER` | `Integer()` | Yes | No | None |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(user_id) -> users(id)`; ON DELETE `RESTRICT`; name `fk_profile_user`.

Unique constraints:

- `(user_id)`; name `uq_profile_user`.

Check constraints:

- `required_total_units > 0`; name `ck_student_profiles_2`.

Explicit indexes:

- None beyond PK/unique-constraint internal indexes.

SQLAlchemy relationships:

- `terms` -> `Term`: one-to-many, collection; back_populates: `profile`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `Term.sort_order`.
- `user` -> `User`: many-to-one, scalar; back_populates: `profile`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `academic_years` -> `AcademicYear`: one-to-many, collection; back_populates: `profile`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `AcademicYear.sort_order`.
- `requirement_groups` -> `RequirementGroup`: one-to-many, collection; back_populates: `profile`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `RequirementGroup.sort_order`.
- `level_requirements` -> `LevelRequirement`: one-to-many, collection; back_populates: `profile`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `LevelRequirement.sort_order`.

## `academic_years` (AcademicYear)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `profile_id` | `INTEGER` | `Integer()` | No | No | None |
| `academic_year` | `VARCHAR(9)` | `String(length=9)` | No | No | None |
| `label` | `VARCHAR(160)` | `String(length=160)` | No | No | None |
| `sort_order` | `INTEGER` | `Integer()` | No | No | None |
| `notes` | `TEXT` | `Text()` | Yes | No | None |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(profile_id) -> student_profiles(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- `(profile_id, sort_order)`; unnamed.

Check constraints:

- None.

Explicit indexes:

- None beyond PK/unique-constraint internal indexes.

SQLAlchemy relationships:

- `profile` -> `StudentProfile`: many-to-one, scalar; back_populates: `academic_years`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `periods` -> `Term`: one-to-many, collection; back_populates: `academic_year`; cascade: `save-update, merge`; passive_deletes: `all`; order_by: `Term.sort_order`.

## `terms` (Term)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `profile_id` | `INTEGER` | `Integer()` | No | No | None |
| `study_year` | `INTEGER` | `Integer()` | Yes | No | None |
| `term_type` | `VARCHAR(80)` | `String(length=80)` | No | No | `custom` |
| `sort_order` | `INTEGER` | `Integer()` | No | No | None |
| `is_exchange` | `BOOLEAN` | `Boolean()` | No | No | `False` |
| `host_university` | `VARCHAR(200)` | `String(length=200)` | Yes | No | None |
| `notes` | `TEXT` | `Text()` | Yes | No | None |
| `academic_year_id` | `INTEGER` | `Integer()` | Yes | No | None |
| `name` | `VARCHAR(160)` | `String(length=160)` | No | No | `Semester 1` |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(academic_year_id) -> academic_years(id)`; ON DELETE `RESTRICT`; name `fk_term_year`.
- `(profile_id) -> student_profiles(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- `(profile_id, sort_order)`; unnamed.

Check constraints:

- None.

Explicit indexes:

- `ix_terms_academic_year_id` on `(academic_year_id)`; nonunique.

SQLAlchemy relationships:

- `profile` -> `StudentProfile`: many-to-one, scalar; back_populates: `terms`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `academic_year` -> `AcademicYear`: many-to-one, scalar; back_populates: `periods`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `courses` -> `PlanCourse`: one-to-many, collection; back_populates: `term`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `PlanCourse.id`.
- `exchange_courses` -> `ExchangeCourse`: one-to-many, collection; back_populates: `term`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `ExchangeCourse.id`.

## `courses` (Course)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `code` | `VARCHAR(20)` | `String(length=20)` | No | No | None |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- None.

Unique constraints:

- None as table constraints; code uniqueness is enforced by the unique index below.

Check constraints:

- None.

Explicit indexes:

- `ix_courses_code` on `(code)`; unique.

SQLAlchemy relationships:

- `versions` -> `CourseVersion`: one-to-many, collection; back_populates: `course`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `CourseVersion.academic_year DESC`.

## `course_versions` (CourseVersion)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `course_id` | `INTEGER` | `Integer()` | No | No | None |
| `academic_year` | `VARCHAR(9)` | `String(length=9)` | Yes | No | None |
| `title` | `VARCHAR(240)` | `String(length=240)` | No | No | None |
| `units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | None |
| `level` | `INTEGER` | `Integer()` | Yes | No | None |
| `department` | `VARCHAR(160)` | `String(length=160)` | Yes | No | None |
| `prerequisite_text` | `TEXT` | `Text()` | Yes | No | None |
| `corequisite_text` | `TEXT` | `Text()` | Yes | No | None |
| `antirequisite_text` | `TEXT` | `Text()` | Yes | No | None |
| `description` | `TEXT` | `Text()` | Yes | No | None |
| `source_url` | `VARCHAR(500)` | `String(length=500)` | Yes | No | None |
| `outline_url` | `VARCHAR(500)` | `String(length=500)` | Yes | No | None |
| `last_checked_at` | `DATETIME` | `DateTime(timezone=True)` | Yes | No | None |
| `data_status` | `VARCHAR(30)` | `String(length=30)` | No | No | `demo_unverified` |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(course_id) -> courses(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- `(course_id, academic_year)`; unnamed.

Check constraints:

- `units >= 0`; unnamed.

Explicit indexes:

- None beyond PK/unique-constraint internal indexes.

SQLAlchemy relationships:

- `course` -> `Course`: many-to-one, scalar; back_populates: `versions`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.

## `plan_courses` (PlanCourse)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `term_id` | `INTEGER` | `Integer()` | No | No | None |
| `course_id` | `INTEGER` | `Integer()` | Yes | No | None |
| `course_code_snapshot` | `VARCHAR(20)` | `String(length=20)` | No | No | None |
| `course_title_snapshot` | `VARCHAR(240)` | `String(length=240)` | No | No | None |
| `units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | None |
| `requirement_group` | `VARCHAR(100)` | `String(length=100)` | No | No | `""` |
| `status` | `VARCHAR(20)` | `String(length=20)` | No | No | `planned` |
| `grade` | `VARCHAR(3)` | `String(length=3)` | Yes | No | None |
| `notes` | `TEXT` | `Text()` | Yes | No | None |
| `created_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now` |
| `updated_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now`; onupdate: `utc_now` |
| `course_version_id` | `INTEGER` | `Integer()` | Yes | No | None |
| `level_snapshot` | `INTEGER` | `Integer()` | Yes | No | None |
| `exceptional_repeat` | `BOOLEAN` | `Boolean()` | No | No | `False` |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(course_version_id) -> course_versions(id)`; ON DELETE `SET NULL`; name `fk_attempt_version`.
- `(course_id) -> courses(id)`; ON DELETE `SET NULL`; unnamed.
- `(term_id) -> terms(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- None.

Check constraints:

- `status IN ('planned', 'in_progress', 'completed', 'withdrawn')`; name `ck_plan_courses_3`.
- `units >= 0`; name `ck_plan_courses_4`.

Explicit indexes:

- `ix_plan_courses_term_id` on `(term_id)`; nonunique.

SQLAlchemy relationships:

- `term` -> `Term`: many-to-one, scalar; back_populates: `courses`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `course` -> `Course`: many-to-one, scalar; back_populates: none; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `course_version` -> `CourseVersion`: many-to-one, scalar; back_populates: none; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `allocations` -> `PlanCourseAllocation`: one-to-many, collection; back_populates: `course`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `PlanCourseAllocation.id`.

## `exchange_courses` (ExchangeCourse)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `term_id` | `INTEGER` | `Integer()` | No | No | None |
| `host_course_code` | `VARCHAR(80)` | `String(length=80)` | Yes | No | None |
| `host_course_title` | `VARCHAR(240)` | `String(length=240)` | No | No | None |
| `host_units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | Yes | No | None |
| `host_grade` | `VARCHAR(40)` | `String(length=40)` | Yes | No | None |
| `hkbu_equivalent_course_id` | `INTEGER` | `Integer()` | Yes | No | None |
| `hkbu_equivalent_code` | `VARCHAR(20)` | `String(length=20)` | Yes | No | None |
| `hkbu_equivalent_title` | `VARCHAR(240)` | `String(length=240)` | Yes | No | None |
| `transferred_units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | None |
| `requirement_group` | `VARCHAR(100)` | `String(length=100)` | No | No | `Other` |
| `transfer_status` | `VARCHAR(20)` | `String(length=20)` | No | No | `planned` |
| `notes` | `TEXT` | `Text()` | Yes | No | None |
| `level_snapshot` | `INTEGER` | `Integer()` | Yes | No | None |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(hkbu_equivalent_course_id) -> courses(id)`; ON DELETE `SET NULL`; unnamed.
- `(term_id) -> terms(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- None.

Check constraints:

- `transfer_status IN ('planned', 'pending_approval', 'approved')`; unnamed.
- `host_units IS NULL OR host_units >= 0`; unnamed.
- `transferred_units >= 0`; unnamed.

Explicit indexes:

- `ix_exchange_courses_term_id` on `(term_id)`; nonunique.

SQLAlchemy relationships:

- `term` -> `Term`: many-to-one, scalar; back_populates: `exchange_courses`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `equivalent_course` -> `Course`: many-to-one, scalar; back_populates: none; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `allocations` -> `ExchangeCourseAllocation`: one-to-many, collection; back_populates: `course`; cascade: `all, delete-orphan`; passive_deletes: `false`; order_by: `ExchangeCourseAllocation.id`.

## `requirement_groups` (RequirementGroup)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `profile_id` | `INTEGER` | `Integer()` | No | No | None |
| `name` | `VARCHAR(100)` | `String(length=100)` | No | No | None |
| `required_units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | `0` |
| `sort_order` | `INTEGER` | `Integer()` | No | No | `0` |
| `notes` | `TEXT` | `Text()` | Yes | No | None |
| `created_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now` |
| `updated_at` | `DATETIME` | `DateTime(timezone=True)` | No | No | `utc_now`; onupdate: `utc_now` |
| `parent_id` | `INTEGER` | `Integer()` | Yes | No | None |
| `aggregation_mode` | `VARCHAR(20)` | `String(length=20)` | No | No | `'own_target'` |

Primary key: `id` (unnamed). SQL server default: `aggregation_mode = 'own_target'`.

Foreign keys:

- `(profile_id) -> student_profiles(id)`; ON DELETE `CASCADE`; unnamed.
- `(parent_id) -> requirement_groups(id)`; ON DELETE `RESTRICT`; name `fk_requirement_parent`.

Unique constraints:

- None as table constraints; two partial unique indexes below replace the former profile-wide name constraint.

Check constraints:

- `required_units >= 0`; name `ck_requirement_units` (equivalent unnamed ORM check).
- `parent_id IS NULL OR parent_id != id`; name `ck_requirement_not_self`.
- `aggregation_mode IN ('own_target', 'sum_children')`; name `ck_requirement_aggregation`.

Explicit indexes:

- `ix_requirement_groups_profile_id` on `(profile_id)`; nonunique.
- `ix_requirement_groups_parent_id` on `(parent_id)`; nonunique.
- `uq_requirement_root_name` on `(profile_id, name)`; unique; SQLite predicate `parent_id IS NULL`.
- `uq_requirement_child_name` on `(profile_id, parent_id, name)`; unique; SQLite predicate `parent_id IS NOT NULL`.

These indexes enforce exact sibling names even for NULL-parent roots. Application validation additionally rejects case-insensitive sibling duplicates. Identical names under different parents are permitted.

SQLAlchemy relationships:

- `profile` -> `StudentProfile`: many-to-one, scalar; back_populates: `requirement_groups`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.

- `parent` -> `RequirementGroup`: many-to-one, scalar; back_populates: `children`; remote_side: `RequirementGroup.id`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `children` -> `RequirementGroup`: one-to-many, collection; back_populates: `parent`; cascade: `save-update, merge`; passive_deletes: `all`; order_by: `RequirementGroup.sort_order, RequirementGroup.id`. No delete or delete-orphan cascade on this relationship.

## `level_requirements` (LevelRequirement)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `profile_id` | `INTEGER` | `Integer()` | No | No | None |
| `label` | `VARCHAR(160)` | `String(length=160)` | No | No | None |
| `minimum_level` | `INTEGER` | `Integer()` | No | No | None |
| `required_units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | None |
| `sort_order` | `INTEGER` | `Integer()` | No | No | `0` |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(profile_id) -> student_profiles(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- None.

Check constraints:

- `minimum_level >= 1`; unnamed.
- `required_units >= 0`; unnamed.

Explicit indexes:

- `ix_level_requirements_profile_id` on `(profile_id)`; nonunique.

SQLAlchemy relationships:

- `profile` -> `StudentProfile`: many-to-one, scalar; back_populates: `level_requirements`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.

## `plan_course_allocations` (PlanCourseAllocation)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `plan_course_id` | `INTEGER` | `Integer()` | No | No | None |
| `requirement_group_id` | `INTEGER` | `Integer()` | No | No | None |
| `allocated_units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | None |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(plan_course_id) -> plan_courses(id)`; ON DELETE `CASCADE`; unnamed.
- `(requirement_group_id) -> requirement_groups(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- `(plan_course_id, requirement_group_id)`; unnamed.

Check constraints:

- `allocated_units >= 0`; unnamed.

Explicit indexes:

- `ix_plan_course_allocations_requirement_group_id` on `(requirement_group_id)`; nonunique.

SQLAlchemy relationships:

- `course` -> `PlanCourse`: many-to-one, scalar; back_populates: `allocations`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `group` -> `RequirementGroup`: many-to-one, scalar; back_populates: none; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.

## `exchange_course_allocations` (ExchangeCourseAllocation)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `id` | `INTEGER` | `Integer()` | No | Yes | None |
| `exchange_course_id` | `INTEGER` | `Integer()` | No | No | None |
| `requirement_group_id` | `INTEGER` | `Integer()` | No | No | None |
| `allocated_units` | `NUMERIC(8, 2)` | `Numeric(precision=8, scale=2)` | No | No | None |

Primary key: `id` (unnamed). SQL server defaults: none.

Foreign keys:

- `(exchange_course_id) -> exchange_courses(id)`; ON DELETE `CASCADE`; unnamed.
- `(requirement_group_id) -> requirement_groups(id)`; ON DELETE `CASCADE`; unnamed.

Unique constraints:

- `(exchange_course_id, requirement_group_id)`; unnamed.

Check constraints:

- `allocated_units >= 0`; unnamed.

Explicit indexes:

- `ix_exchange_course_allocations_requirement_group_id` on `(requirement_group_id)`; nonunique.

SQLAlchemy relationships:

- `course` -> `ExchangeCourse`: many-to-one, scalar; back_populates: `allocations`; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.
- `group` -> `RequirementGroup`: many-to-one, scalar; back_populates: none; cascade: `save-update, merge`; passive_deletes: `false`; order_by: none.

## `alembic_version`

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `version_num` | `VARCHAR(32)` | Not mapped | No | Yes | None |

Primary key: `version_num` (name: `alembic_version_pkc`). SQL server defaults: none.

Foreign keys:

- None.

Unique constraints:

- None.

Check constraints:

- None.

Explicit indexes:

- None beyond PK/unique-constraint internal indexes.

SQLAlchemy relationships:

- None.

## `sqlite_sequence` (SQLite Internal)

| Column | SQLite Type | SQLAlchemy Type | Nullable | PK | Python Default / Update |
| --- | --- | --- | --- | --- | --- |
| `name` | No declared type | Not mapped | Yes | No | None |
| `seq` | No declared type | Not mapped | Yes | No | None |

SQLite creates and maintains this internal table for `users.id` AUTOINCREMENT. No declared PK, FK, unique/check constraint, index, relationship or server default. It stores the user-ID high-water mark. It is not application data and must not be edited or reset during account deletion. No other current table uses AUTOINCREMENT.

## Storage Semantics and Cascades

- Direct user deletion remains blocked while a profile exists: its FK uses RESTRICT and `User.profile` uses `passive_deletes="all"`. v0.5 self/admin deletion uses the dedicated transactional service described below, not an ORM user cascade.
- Profile-owned years, terms, category targets, and level targets have database CASCADE FKs. The profile ORM collections use delete-orphan.
- An academic year uses RESTRICT from its periods. Its `periods` relationship does not delete-orphan and uses passive deletes. The UI explicitly deletes empty periods before an empty year; populated years/periods are blocked until records are moved or explicitly deleted.
- Deleting a term at the SQL/ORM layer cascades to its normal and exchange entries and their allocations. The public route prevents deletion of populated terms; this safeguard is application behavior, not a database check.
- Deleting a catalogue identity cascades to its versions, but sets linked attempt/equivalent identity FKs to NULL. Deleting a version sets `plan_courses.course_version_id` to NULL. Code/title/unit/level snapshots and allocations survive.
- Deleting a parent requirement is blocked by both the target route guard and its child FK's RESTRICT action. Children must be moved or explicitly removed first; removing a child from the ORM collection is not delete-orphan. Account deletion removes descendants before parents to satisfy this self-FK.
- Deleting a leaf requirement group cascades only to allocation rows. It does not delete course attempts or transfers. The course remains eligible for overall degree units and becomes unallocated where no allocations remain.
- Allocation parent relationships use ORM delete-orphan. Group relationships use only save-update/merge; there is no group-to-allocation ORM collection, so group deletion relies on database FK CASCADE.
- Application engines enable SQLite `PRAGMA foreign_keys=ON` and a 5,000 ms busy timeout on connection. External SQLite tools must enable their own FK enforcement.
- Alembic disables FK actions before its SQLite batch transaction, uses BEGIN IMMEDIATE, preserves row IDs during copies, validates FKs, and commits or rolls back the transaction. This prevents DROP TABLE during copies from cascading into existing records.

## Normalized Requirements and Application Validation

`requirement_groups` and `level_requirements` are the curriculum-related live tables. They are user-owned through the academic profile. No programme-name lookup supplies authoritative targets. Category targets are independent of `student_profiles.required_total_units`. Leaves use stored `required_units`; containers ignore their own stored target and recursively sum immediate children's calculated targets and progress. Every child must be completed for a container to be completed; empty containers remain missing. Repeated allocations across branches may overlap without inflating physical degree credits.

`parent_id` is optional, and `sort_order` now orders siblings. The application validates same-profile ancestry, cycles, sibling names and complete owned-ID reorder payloads. SQL prevents missing parents and direct self-parenting, but does not enforce multi-node acyclicity or same-profile parenting. External database writers must enforce these invariants themselves. Adding children to an unallocated leaf converts it to a container. Targets with allocations cannot become containers; course forms reject container allocations. Containers and leaves appear in a preordered tree with indentation capped visually, not in storage.

Allocation uniqueness and nonnegative units are enforced in SQL. The upper bound (one allocation cannot exceed its parent course's HKBU/transferred units), two-decimal precision, and same-profile ownership are validated in the shared course form handler. Cross-group allocation sums can exceed course units intentionally; overall units count normalized course codes once. Code-less exchange transfers remain separate physical records.

The physical `plan_courses.requirement_group` and `exchange_courses.requirement_group` columns are deprecated archival strings. Migration retained every original value; the live engine ignores them. New UI records use an empty string and normalized allocations. The ExchangeCourse model's default `Other` remains for compatibility with direct construction; it is not an automatic UI allocation.

`courses` contains only stable identity. Read-only convenience properties such as title and units read its latest version. Unknown academic years use NULL and retain demo/unverified status. SQL uniqueness on `(course_id, academic_year)` enforces known-year identity; SQLite permits multiple NULL-year versions at the constraint level. The importer only accepts explicit validated years, and the demo seeder does not add a duplicate unknown-year version.

`level_snapshot` retains known levels at creation/backfill. Normal entries use their snapshot, then a valid code-matching selected version, never the newest version. Manual entries have no version link. The separate offline level-backfill CLI may fill a missing snapshot from a matching selected version or an exact stable identity whose official versions have one unambiguous known level. It changes neither historical fields nor timestamps nor identity/version links. Conflicting or unavailable metadata remains unknown.

Exchange levels require a syntactically valid specific HKBU equivalent code: a saved level takes precedence, then an exact linked identity's unambiguous official level. Generic transfers remain unclassified even if a stale level exists in external data. Approved equivalents count toward earned and projected level units; pending/planned equivalents only toward projected units. Host grades never feed GPA.

`theme_preference` stores the authenticated user's selected System/Light/Dark mode. New accounts default to System; the v0.3 migration supplied that default, while v0.4 preserves each existing preference. The authenticated CSRF-protected preference endpoint changes only the signed-in account. Early document initialization applies the server preference, or unauthenticated localStorage preference, and System tracks browser color-scheme changes.

`terms.study_year` and `student_profiles.curriculum_key` remain archival compatibility fields. New custom periods need no study-year number. Flexible `term_type` values are unrestricted VARCHAR values. Global per-profile term sort_order establishes GPA chronology; academic_year.sort_order and period order are synchronized by timeline mutations.

## Migration Preservation and Remaining Risks

The fixed eleven-term structure has been replaced. The migration creates AcademicYear rows from old study_year offsets, retains every term primary key, and attaches each period without changing old normal/exchange term FKs. It copies all legacy catalogue fields into CourseVersion rows with the original course identities. It creates one matching allocation for every old normal/exchange record and preserves original free-text group names.

The earlier v0.1-to-v0.2 migration was checked against a private pre-upgrade backup. Every original column value and catalogue identity matched after migration. Personal record counts and academic figures are omitted from this public copy. Exchange preservation, S/W/F grades, repeat history, sparse term IDs, notes and custom group names were separately tested using a populated synthetic v0.1 database.

Data that would have been at risk under a destructive replacement:

1. Term IDs and the `plan_courses.term_id`/`exchange_courses.term_id` references, with CASCADE capable of deleting attempts and transfers.
2. Term exchange flags, host universities, notes, and chronological sort order.
3. Historical GPA/cGPA term attribution and export linkage.
4. Legacy category names and course allocations during free-text normalization.
5. Historical course metadata and snapshot values when introducing catalogue versions.
6. Existing profile ownership and the local plan when removing the single-profile constraint.

The migration mitigates these risks with ID preservation, explicit backfills, count/FK assertions, transaction rollback, backups, and regression tests. Reordering periods after migration intentionally changes chronological GPA boundaries. Direct SQL deletion still has the documented cascades; UI deletion guards do not protect external writes. A v0.1 downgrade cannot represent new users, fifth years, custom periods, versions, or multiple allocations, so downgrade raises before changing data.

Backups: `data/study_companion.v01-backup.sqlite3` and `data/study_companion.pre-v02-20261002.sqlite3`.

## Token Lifecycle and Security Invariants

- New User.email_verified_at is NULL. The migration marks every existing account verified using one current UTC timestamp, without modifying IDs, emails, usernames, hashes, theme or old timestamps. This grandfathers old accounts; it does not independently validate their historical addresses.
- issue_token uses secrets.token_urlsafe(32), stores only SHA-256(raw), scopes it to a user and purpose, and expires verification after 24 hours or reset after 30 minutes. Creating a replacement invalidates outstanding tokens of the same purpose in the same transaction.
- Normal links contain a 43-character URL-safe token; a database digest cannot be supplied as the raw URL token. Public responses never echo the raw token. A valid GET stores a purpose-bound digest in the signed HTTP-only session cookie and redirects to the query-free route; it does not consume the token or change the password/email state.
- Confirmation/reset uses POST with CSRF protection. Lookup rejects wrong purpose, malformed/unknown, expired and consumed tokens and disabled users. Consumption is a conditional SQL UPDATE requiring consumed_at IS NULL, expires_at > current UTC and a non-disabled owning account; rowcount must equal one. Token consumption, account mutation and invalidation commit together. SQLite stores datetime values without timezone offsets despite the timezone-aware ORM type; application values and SQL comparisons use UTC. In-memory synchronization is disabled for the atomic expiry predicate.
- Verification sets email_verified_at, consumes/invalidate verification links and clears the session. Login still requires credentials. Unverified accounts receive only a restricted pending-user session, not academic access.
- Recovery is email-only and sends only to verified, non-disabled accounts. Unknown/unverified/disabled addresses receive the same generic public response. Passwords follow the same 12-1024 character policy as registration and are hashed with Argon2id.
- Reset increments users.auth_version, invalidates all outstanding resets, clears the session and requires fresh login. Signed-in password changes require the current password, conditionally update the expected version, invalidate resets and refresh the current signed-in session. Every protected route compares its session version with the database value, so older sessions fail closed.
- Consumed_at also marks superseded/cancelled tokens, not exclusively tokens used successfully. Expired/consumed rows are retained until explicit CLI cleanup; no automatic token-pruning job exists. Cleanup selects expires_at older than the retention cutoff OR non-NULL consumed_at older than that cutoff; valid unused tokens never qualify. Default retention is 30 days and default execution is dry-run.
- Production cookies require HTTPS; all sessions remain signed, HTTP-only and SameSite=Strict. Tokens are not included in JSON export, analytics or logs. Application access logs redact token queries and database errors hide bound parameters. Development .eml files intentionally hold private bearer links outside static serving; SMTP credentials exist only in environment configuration.
- Rate limits are bounded in-process state, not SQL tables. Collapse state is user/profile-scoped localStorage, not SQL. No email-change fields, mail-queue tables, SMTP secrets or session table were added.

## Historical v0.4 Preservation Verification

Pre-upgrade revision: `c83f12d60e47`; release revision: `d94a23e71f58`. A private backup was created, migration was rehearsed on a copy, and the live database was checked against the backup before upgrading.

Every pre-existing column matched afterward, including account timestamps, ownership, course snapshots, allocations and credentials. Academic totals were unchanged. Existing users were grandfathered as verified without altering their prior identity fields. No target, level, catalogue or academic schema changed in v0.4. Personal values and installation-specific record counts are omitted from this public copy.

SQLite integrity and FK checks passed; Alembic metadata comparison reported no operations. Populated v0.1, v0.2 and v0.3 migration tests passed. Downgrade refuses to discard verification/revocation state; restoration requires a compatible private backup and matching application version.

Public earlier reports are linked from [the release archive](docs/releases/).

## v0.5 Account Lifecycle Invariants

- Migration defaults are deterministic: every existing account receives is_admin=false, is_disabled=false and NULL disabled_at/disabled_reason/last_login_at. No identity is inferred to be admin. Grant/revoke is an explicit CLI operation; it never creates an account. The CLI prevents last-admin revocation unless `--force`, increments auth_version on a role change, invalidates resets and writes one audit event. A SQLite immediate transaction serializes that CLI check/write. An unchanged role is a no-op.
- Every admin route requires a verified, enabled, authenticated admin with a matching auth_version. Account metadata and profile existence are the only admin-visible user data. Academic export remains scoped to the signed-in user's own profile; neither administrator privileges nor audit events expose another planner.
- Disable sets is_disabled, disabled_at, optional bounded reason, increments auth_version and invalidates outstanding verification/reset links. Existing sessions fail on their next protected request. Disabled accounts cannot log in, change password, access/export academic data or receive account mail. Correct credentials can receive an unavailable-account message; forgot-password remains generic. Re-enable clears disabled_at and disabled_reason and does not decrease auth_version. Revoke changes auth_version and reset-token consumption only, apart from normal updated_at maintenance. Passwords and academic data are untouched.
- last_login_at is set only on full verified, enabled login. A conditional SQL update checks the credential hash, auth_version, verification and enabled state before recording it. A concurrent reset/disable/revocation fails closed. Session creation uses the version actually authenticated, not a later version reloaded after commit. Password-change session refresh likewise uses its expected incremented version. Verification/reset visits, failed credentials and ordinary protected requests do not change last_login_at.
- Self-service deletion is POST/CSRF protected and requires current password plus exact `DELETE`. Admin deletion forbids self-targeting, uses a confirmation page, and requires exact target username or `DELETE`. Admin disable/revoke also forbid self-targeting. Self-service deletion has no last-admin guard; a new admin can be explicitly bootstrapped if the last operator deletes their account.
- The shared deletion service first claims the current account version using a conditional update, then obtains only profiles with that user_id. It rejects allocations from another profile into the owned target tree. In one transaction it deletes owned terms (cascading normal/exchange records and allocations), then academic years, target leaves iteratively deepest-first, level targets, profiles, account tokens and the account. There is no recursive Python traversal, no intermediate commit and no FK disabling. A malformed cycle, remaining RESTRICT dependency, cross-profile allocation or other database failure aborts/rolls back all changes. Tests include a 1,050-node chain and injected failure after deleting terms.
- The deletion service never issues catalogue deletes. Other users' records and unclaimed profiles remain. ON DELETE SET NULL preserves audit history for deleted actors and targets. Deletion clears the current cookie and old user IDs cannot be reused because of AUTOINCREMENT. Deletion does not erase historical backups, development mailbox files or browser-local preferences; these require a separate operational retention policy. No recovery/undo or JSON import is supplied.
- Readiness is application behavior, not a SQL table: `SELECT 1` plus an exact single Alembic-head match, with generic 200/503 JSON and no mail/network dependency. Registration gating is process configuration (`REGISTRATION_MODE`, optional secret `BETA_INVITE_CODE`), not a schema or invitation table. Admin/auth limits remain process-local, one-worker state. Backups use SQLite's backup API; verification runs integrity_check and foreign_key_check on the copy.

## v0.5 Preservation Verification

Pre-upgrade revision: `d94a23e71f58`; current revision: `e05b34f82a69`. A private backup was created and the migration rehearsed on a copy. Every old column in the 13 pre-existing application tables was compared, including credentials (not reproduced), account timestamps, ownership, snapshots, allocations and notes. Academic totals matched.

Account deletion was also rehearsed on that migrated copy. Only the selected owned graph was removed; unrelated profiles and shared catalogue survived with FKs enabled and valid. The copy was discarded. No live account was granted admin, disabled or deleted during delivery.

The old development process was stopped before live migration. Live data still matched the backup immediately before upgrading, and the same complete old-column and academic-total comparison passed afterward. Integrity and FK checks passed, and `alembic check` reported no new operations.

Existing identity fields, credentials, theme, verification and auth_version were unchanged. The migration defaults every existing account to non-admin and enabled, with NULL disabled_at/disabled_reason/last_login_at. Personal academic figures, ownership IDs and installation-specific table counts are intentionally omitted from this public copy.

A post-upgrade backup was verified through both backup CLIs, and token cleanup was preview-only with no changes. Public historical reports are available at [v0.4 delivery](docs/releases/v04-report.md) and [v0.4 schema](docs/releases/v04-schema-report.md). Downgrade refuses to discard account state/audit history; restoration requires a compatible private backup and matching application version.
