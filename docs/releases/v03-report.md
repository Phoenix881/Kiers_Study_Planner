# HKBU Study Companion v0.3 Delivery Report

Public copy: personal academic figures, ownership identifiers and installation-specific record counts have been omitted. Browser/test examples below use synthetic data.

Verified 2026-10-02, Asia/Hong_Kong.

## Project State

The next-upgrade specification is implemented as an incremental v0.3 release. The application is running at **http://127.0.0.1:8001** using the existing local database. Health returns `{"status":"ok","version":"0.3.0"}`; sign-in returns HTTP 200. The existing listener on port 8000 was not stopped.

FastAPI, SQLAlchemy 2, Alembic, SQLite, Jinja2, plain CSS, vanilla JavaScript and local Lucide icons remain in place. No frontend framework, build system, public deployment, external service, account reset or live catalogue re-import was added.

## Implemented Changes

### Levels and Historical Records

- Normal progress uses an existing level snapshot first, then the valid code-matching selected CourseVersion, otherwise unknown. It never silently substitutes the latest catalogue version.
- `scripts/backfill_levels.py` provides a read-only preview and explicit `--apply` mode. It uses local metadata only, prefers a valid selected version, and otherwise requires an exact normalized identity with an unambiguous known level across official versions.
- Conflicting official levels, absent metadata and unmapped transfers stay unknown. Code digits and titles are not used to guess a level.
- Only missing level snapshots are filled. Titles, units, grades, statuses, notes, periods, links, timestamps and allocations are preserved.
- Approved specific HKBU-equivalent transfers contribute earned level units; planned/pending equivalents contribute projected units. Generic transfers have no assumed level.
- Unknown classifications are summarized under Plan notes with affected codes/titles.

### Requirement Tree

- RequirementGroup adds nullable `parent_id` and `aggregation_mode`, with `own_target` and `sum_children`.
- Arbitrary nesting is supported. Sibling ordering is stable; visual indentation is capped at four levels without limiting stored depth.
- Containers derive target, earned and projected values recursively from their children. Completion requires every child to be complete; surplus in one child cannot conceal another child's shortfall. Empty containers remain missing.
- Overall physical credits retain the existing code deduplication and GPA rules. Intentional allocation overlap across requirement branches remains permitted.
- Targets has handle-only native drag/drop for sibling ordering, nesting, moving between parents and returning to top level. Up/down/indent/outdent buttons and a parent selector provide keyboard-accessible alternatives.
- The CSRF-protected reorder endpoint receives a complete owned tree snapshot as JSON in a form field and persists the change atomically. It rejects missing/duplicate/foreign IDs, invalid ancestry, cycles and sibling-name conflicts.
- SQLite partial unique indexes cover root and non-root sibling names; application validation is additionally case-insensitive. The same child name can appear under different parents.
- Container allocations are rejected in both forms and server validation. An allocated leaf cannot become a container until its allocations are moved. Adding children to an unallocated leaf converts it to a container.
- Parents with children cannot be deleted. Leaf deletion removes allocations, never course attempts or transfers.
- Expanded standard names remain suggestions only. Existing sibling names are suppressed; no curriculum or target is inferred.
- Dashboard and Progress preserve the existing metrics and overall bar, with ordered hierarchical rows and immediate client-side expand/collapse. Allocation menus show hierarchy paths and disable containers. Level targets remain separate.

### Catalogue and Course Entry

- Course Explorer uses SQL count/order/offset/limit pagination with 50 rows per page. All filters apply before counting; there is no 300-result ceiling.
- Total-result ranges, previous/next and page links preserve query, year, level and prefix. Browser history works; invalid page bounds clamp; empty results display zero.
- The native course-code datalist is replaced by an asynchronous accessible combobox. The authenticated endpoint is `/api/catalogue/search`; the previous search URL remains an alias.
- Ranking: exact normalized code, code prefix, code substring, title prefix, title substring; ties use code/version ID. Results are capped at 12.
- The combobox debounces 180 ms, aborts/ignores stale responses, supports pointer selection and keyboard Up/Down/Enter/Escape, exposes active-option semantics and closes outside.
- Selecting a course fills identity/version, code, title, units, level and provenance. Code/title edits clear stale hidden IDs; server validation rejects mismatched identities or versions.
- Manual entry remains independent of catalogue matching. The preferred catalogue year is the period's year when imported, otherwise the latest available official year. Historical versions remain selectable through Explorer.
- Existing source links/status/year/timestamps and the distinction between catalogue year and semester availability remain intact. Importer implementation and offline regression fixtures are preserved.

### Themes and Performance

- The top-right control offers System, Light and Dark. New/migrated accounts default to System.
- Signed-in preferences persist in the database through an authenticated CSRF-protected endpoint; the database preference is authoritative after login. Unauthenticated pages may use localStorage.
- Early head initialization applies the effective theme before content renders; System listens for browser/OS changes.
- Shared semantic CSS variables cover surfaces, text, controls, borders, focus, badges, progress, errors and autocomplete. Desktop/mobile layouts were visually inspected in dark and light.
- Requirement traversal uses preloaded profile records and iterative tree ordering. A query-count test verifies that adding 100 requirement nodes does not add a query per node.
- Catalogue pages and autocomplete retrieve bounded database result sets instead of rendering the entire catalogue.

## Database and Preservation

Release revision: **`c83f12d60e47`**, following `b72e91a40c26` and `8884a9a3ad86`.

The migration adds three columns across two tables, replaces profile-wide requirement-name uniqueness with partial sibling indexes, and adds parent/mode/theme constraints. Existing groups remain top-level own-target nodes. No hierarchy or target was invented, and the migration performs no network access.

A private backup was made first. The full upgrade and optional level repair were rehearsed on an isolated copy before the live upgrade. Every original row, primary key and non-level column value was compared and preserved. Integrity and FK checks passed. Downgrade refuses to discard hierarchy/theme information; restoration requires a compatible backup and application version.

Level repair filled only unambiguous missing snapshots, preserved already-known levels and historical fields, and made no additional changes on repeat preview. Unknown levels remained unknown. Profile GPA/credit totals were preserved; personal course lists, counts and progress figures are omitted from this public copy.

## Executed Verification

| Check | Result |
| --- | --- |
| Baseline tests | 122 passed |
| Final automated suite | **156 passed** |
| Ruff lint | Passed |
| Ruff formatting | Passed; 63 files |
| Alembic current | `c83f12d60e47 (head)` |
| Alembic schema comparison | No new operations |
| Dependency check | No broken requirements |
| SQLite integrity / FK checks | `ok` / no violations |
| Populated v0.1 and v0.2 migration regressions | Passed |
| Real-database rehearsal and live preservation comparison | Passed |
| Idempotent level repair | Passed |
| Isolated Chrome workflow checks | **30 workflow areas passed** |
| Browser widths | 320, 390, 768, 1440, 1920 |
| Browser JavaScript errors / failed responses | **0 / 0** |
| Local health / sign-in | v0.3.0 / HTTP 200 |

The new tests cover level precedence and repair ambiguity, preserved timestamps/snapshots, generic thresholds, repeat deduplication, passing/non-credit/planned grade states, approved/pending/planned mapped transfers, generic exclusions, hierarchy roll-ups and overlap, surplus protection, empty containers, sibling ordering, cycles/forged IDs/ownership/CSRF, deletion safeguards, pagination, ranked autocomplete, manual entry and stale versions, year preference, theme validation/persistence/isolation, and bounded tree-loading queries.

Browser checks exercise native drag/drop with real pointer movement, root moves, nesting, accessible alternatives, persistence after reload, collapse/expand, disabled container options, saving a hierarchy allocation, page 2 and Back/Forward, code/title autocomplete, keyboard/mouse selection, stale-link clearing, manual save, Light/Dark/System with simulated OS changes, navigation and logout/login persistence, and all retained planner/GPA/exchange/export workflows.

The isolated browser plan finishes with **12 earned units, 12 projected units and 3.50 cGPA**. A withdrawn manual test course allocated to a nested leaf does not inflate progress. Tests do not alter the user's live academic data.

Desktop/mobile screenshots were visually inspected during verification. They remain local verification artifacts excluded from Git.

## Known Limits

- This remains a local independent planning prototype, not an official HKBU audit or approval service. Targets and transfer approvals are student-controlled.
- Unresolved levels are intentionally unknown. Later official imports can be followed by another explicit repair preview/apply.
- Native drag/drop is primarily a desktop interaction; mobile and keyboard users have the accessible movement buttons and parent selector. Drag saves reload the Targets page; progress collapse/expand does not reload.
- Same-profile parenting, multi-node acyclicity, allocation bounds and container eligibility are application invariants. External SQL writers must preserve them; the database directly enforces FKs, direct self-parent rejection, modes and sibling uniqueness.
- Requirement-tree profile deletion is not exposed; the self-FK RESTRICT can block external deletion of populated trees until children are handled.
- Catalogue search is local and substring-based, without fuzzy matching or inferred semester availability. PDFs remain links only.
- System theme resolution requires JavaScript; an explicit preference-save failure is reported and the previous theme restored.
- Public hosting, email recovery, OAuth, timetable integration, automatic curricula, OCR and JSON restore remain outside scope. Missing `SECRET_KEY` causes sessions to expire on server restart.
- Verification used macOS, Python 3.14 and installed Chrome. Other browser/OS matrices were not run.
- The workspace is not a Git repository; no commit or deployment was made.

## Run Commands

Development address used for verification: **http://127.0.0.1:8001**.

```bash
bin/alembic upgrade head
bin/python scripts/backfill_levels.py --apply
bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

The first two commands are already applied and are safe to repeat. The server is already running; do not start a second listener on the same port.

Verification commands:

```bash
bin/pytest -q
bin/ruff check app scripts tests alembic
bin/ruff format --check app scripts tests alembic
bin/alembic check
bin/python -m pip check
bin/python -m scripts.browser_check
```

See [README.md](../../README.md) for operation and migration guidance, and [schema_report.md](v03-schema-report.md) for every implemented table, column, constraint, index, relationship, cascade and migration risk.
