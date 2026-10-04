# Legacy Curriculum Snapshots

These files and their evaluator are retained for v0.1 compatibility and regression tests. They do not drive v0.2 profile setup or live progress. The student defines current targets in `requirement_groups` and `level_requirements`, with normalized course allocations.

Each JSON file has a stable key, version, admission year, source URLs, and structured rules. The supplied 2024/25 snapshot is deliberately labelled **demo**: group thresholds and required courses are illustrative, not official programme requirements.

Supported rule types: `TOTAL_UNITS`, `GROUP_UNITS`, `REQUIRED_COURSE`, `MIN_LEVEL_UNITS`. Rule input is validated by Pydantic; unknown rule types and duplicate IDs fail validation instead of silently passing. New rule types belong in the schema and the service evaluator, not templates.

The legacy evaluator lets profile total units override a snapshot total and rejects mismatched admission cohorts. There is no curriculum selector in the v0.2 UI, and migration does not adopt these demo thresholds.

Manual courses have unknown levels. Level rules use locally stored catalogue levels only, never guesses from the course code. Imported snapshots should retain verified source URLs, academic year, and last-checked metadata. Do not label guessed targets as official.
