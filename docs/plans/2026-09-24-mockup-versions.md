# Mockup versions + compact sidebar — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan chunk-by-chunk. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan style (owner's standing rule, overrides the skill default):** this plan carries decisions, interfaces, exact names, boundary values and test assertions. It does **not** carry function bodies. Any code block below is a **sketch to adapt**, never verbatim-correct — let the tests and the tooling arbitrate. Chunks are sized by coherent deliverable (5 chunks), one review per chunk + one whole-branch review.

**Goal:** Fold iterations of a mockup into one design with a version history, give agents a cheap way to add versions, and give the sidebar its height back — shipped as 1.5.0.

**Architecture:** `mockups` rows become *designs*; a new `mockup_versions` table holds content, and `mockup_aliases` keeps folded ids resolving. `app/db.py` remains the only module that writes SQL; a new `app/versioning.py` owns the title rule, file writes and multi-step version operations. The UI stays a single vanilla-JS template (`gallery.html`) + `style.css`.

**Tech stack:** Python 3.12, FastAPI, FastMCP 3.x, aiosqlite (SQLite, WAL), vanilla JS, pytest + pytest-asyncio + httpx.

**Spec:** `docs/specs/2026-09-24-mockup-versions-design.md` (approved 2026-09-24). Read it before any chunk; section numbers below (§n) refer to it.

## Global constraints

- `./data` on this host is **live production data**. Never run a dev server or a test against it. UI checks run on a throwaway copy of `app/` in the scratchpad with its own `data/` (pattern used in session 4; record the uvicorn **child** PID, not a wrapper's).
- Tests: `.venv/bin/python -m pytest -q` (one-shot, ~8 s today). Always with a Bash timeout. No watch modes.
- The live DB may be **read** for dry-runs only via a **copy** (`sqlite3` backup or file copy of `mockups.db` + `-wal`) in the scratchpad. `python -m app.fold --apply` against live runs only after the owner approves the dry-run group list.
- Version numbers are never reused (`MAX(number)+1`). "Latest" = highest `number`, not latest time.
- Every `/view` response keeps `X-Content-Type-Options: nosniff`, and `Content-Security-Policy: sandbox allow-scripts` for html/svg.
- Version links use a path segment `/view/{id}/v/{n}` — never a query string (slipwave portal proofs refuse query strings).
- SQLite: `PRAGMA foreign_keys=ON` must be set on the connection for `ON DELETE CASCADE` to work (it is off by default).
- `ALTER TABLE … ADD COLUMN … NOT NULL` needs a `DEFAULT` in SQLite; add with a default, then backfill.
- No `Co-Authored-By` trailers in commits.
- Match existing style: small async functions, keyword-only args (`*,`), `ValueError` for domain errors translated to `ToolError` / JSON errors at the edges.

## Review focus

Inputs the spec implies but a task's happy-path tests would not exercise. Each has a test in the owning chunk (marked **RF-n** there).

1. **RF-1 Deleting the latest version** — mirror columns (`file_path`, `content_type`, `description`), `latest_at` and `version_count` must fall back to the new highest version; the design title does not change. (Chunk 1)
2. **RF-2 Content-type change across versions** (html v1 → png v2) — each version keeps its own extension and MIME; `/view/{id}` serves png, `/view/{id}/v/1` still serves html with the sandbox CSP. (Chunks 1, 2)
3. **RF-3 Split of an aliased version, then re-use** — split restores the alias id as a normal design **and deletes the alias row**; a later `parent=<that id>` targets the new standalone design, not the old one. (Chunk 1)
4. **RF-4 `set_created_at` on an older version to a time after the latest** — ordering of versions and "latest" stay by `number`; `latest_at` only follows the highest-numbered version. (Chunk 2)
5. **RF-5 Gallery deep link with an alias id** (`/?mockup=<alias>`) — opens the design at the pinned version (pill shows `v{n} of {count}`), not the latest. (Chunk 5)

## File structure

| file | responsibility | chunks |
|---|---|---|
| `app/db.py` | schema, migrations, all SQL (designs, versions, aliases) | 1 |
| `app/versioning.py` **(new)** | `base_title`, `comparison_key`, and orchestration: create/add/split/delete/resolve (files + db calls) | 1 |
| `app/storage.py` | `write_mockup_file` gains a version-aware path helper | 1 |
| `app/mcp_server.py` | tools + instructions (parent, fold, versions, split, delete version) | 2 |
| `app/routes/api.py` | upload `parent`/`fold`, versions endpoints, projects order | 2 |
| `app/routes/gallery.py` | `/view/{id}`, `/view/{id}/v/{n}`, alias resolution | 2 |
| `app/fold.py` **(new)** | `python -m app.fold --dry-run/--apply` | 3 |
| `app/templates/gallery.html`, `app/static/style.css` | sidebar, brand, collapsed bar (chunk 4); version UI (chunk 5) | 4, 5 |
| `README.md`, `CHANGELOG.md` | fold command, upload fields, `update_mockup` change | 3 |
| `tests/test_versioning.py` **(new)**, `tests/test_fold.py` **(new)**, existing `tests/test_*.py` | | 1–3 |

---

## Task 1 — Data layer: schema, migration, versioning core

**Rigor:** schema migration on production data — this chunk's review is mandatory and must include the migration-on-a-v1.4-shaped-DB test being **seen to fail first**.

**Files:** modify `app/db.py`, `app/storage.py`; create `app/versioning.py`, `tests/test_versioning.py`; extend `tests/test_db.py`.

**Interfaces produced (later chunks rely on these exact names):**

`app/versioning.py`
- `base_title(title: str) -> str` — §5 rule.
- `comparison_key(title: str) -> str` — `base_title(title).casefold()` with runs of whitespace collapsed to one space, stripped.
- `@dataclass VersionRef: mockup_id: str; number: int; folded: bool`
- `async create_design(db, *, project: str, title: str, description: str | None, content_type: str, content: str, tags: list[str]) -> VersionRef` — new design + v1 (`folded=False`).
- `async add_version(db, mockup_id: str, *, title: str, description: str | None, content_type: str, content: str, folded: bool = False) -> VersionRef` — writes file, then db; on db failure deletes the new file. If the design goes from 1 → 2 versions, sets design `title = base_title(v1.title)`.
- `async find_fold_target(db, *, project_slug: str, title: str) -> str | None` — the single design id in that project whose `comparison_key(design.title)` equals `comparison_key(title)`; `None` on zero or ≥ 2 matches.
- `async split_version(db, mockup_id: str, number: int) -> str` — new design id (the alias id if an alias pointed at this version, else a new uuid4); moves the version row (as the new design's v1, same file, same created_at, same title/description), deletes that alias row, recomputes the source design's mirrors. Refuses if it is the design's only version (`ValueError`).
- `async delete_version(db, mockup_id: str, number: int) -> None` — deletes file + row, recomputes mirrors; `ValueError("Cannot delete the only version; delete the mockup instead")` on the last one.
- `async delete_design(db, mockup_id: str) -> None` — deletes every version's file, then the design (cascade removes versions + aliases).
- `async resolve(db, id: str, number: int | None = None) -> tuple[str, int] | None` — design id → `(id, number or latest)`; alias id → `(target, alias.number)` (an explicit `number` is ignored for aliases); unknown → `None`; unknown `number` → `None`.

`app/db.py` (SQL only; called by `versioning.py`, and read functions by routes/tools)
- `insert_mockup(...)` — **same signature as today**; now inserts the design **and its v1** in one transaction, sets `latest_at = created_at`, `version_count = 1`. (Keeps every existing test that seeds via `insert_mockup` valid.)
- `insert_version(db, *, mockup_id, number, title, description, content_type, file_path, created_at)`
- `next_version_number(db, mockup_id) -> int` — `COALESCE(MAX(number), 0) + 1`.
- `get_versions(db, mockup_id) -> list[dict]` — newest (highest number) first.
- `get_version(db, mockup_id, number) -> dict | None`
- `get_alias(db, alias_id) -> dict | None`; `insert_alias(db, *, alias_id, mockup_id, number)`; `delete_alias(db, alias_id)`
- `delete_version_row(db, mockup_id, number)`
- `refresh_design_mirror(db, mockup_id)` — sets `description`, `content_type`, `file_path`, `latest_at` from the highest-numbered version, `version_count = COUNT(*)`, `updated_at = now`.
- `list_mockups(...)` — `sort="newest"` → `latest_at DESC`; `oldest` → `created_at ASC` (unchanged); `favorites` → `favorite DESC, latest_at DESC`. `q` also matches `EXISTS (SELECT 1 FROM mockup_versions v WHERE v.mockup_id = mockups.id AND v.title LIKE ?)`. Rows include `version_count`, `latest_at`.
- `list_projects(db)` — `ORDER BY MAX(latest_at) DESC`, `count` = designs.
- Multi-statement writes use one transaction (`BEGIN IMMEDIATE` … `COMMIT`, rollback on exception). The app uses a single connection, so this also serialises `next_version_number`.

`app/storage.py`
- `version_rel_path(project_slug, mockup_id, number, content_type) -> str` = `f"{project_slug}/{mockup_id}/v{number}.{content_type}"`.
- `write_mockup_file(project_slug, mockup_id, content_type, content, *, rel_path: str | None = None) -> str` — when `rel_path` is given, writes there (creating parent dirs); otherwise the existing `{slug}/{id}.{ext}` path (v1 of new designs keeps today's layout, so v1 paths look the same before and after the release).

**Migration (in `init_db`, after `_migrate_favorite_column`)** — new `_migrate_versions(db)`:
1. `PRAGMA foreign_keys=ON` (set in `init_db` right after connect).
2. `CREATE TABLE IF NOT EXISTS mockup_versions (...)`, `mockup_aliases (...)` per §3.2/§3.3, FKs `ON DELETE CASCADE`.
3. If `latest_at` absent: `ALTER TABLE mockups ADD COLUMN latest_at TEXT NOT NULL DEFAULT ''`; if `version_count` absent: `… INTEGER NOT NULL DEFAULT 1`. Index `idx_mockups_latest_at`.
4. Backfill (sketch): `INSERT INTO mockup_versions (mockup_id, number, title, description, content_type, file_path, created_at) SELECT id, 1, title, description, content_type, file_path, created_at FROM mockups m WHERE NOT EXISTS (SELECT 1 FROM mockup_versions v WHERE v.mockup_id = m.id)`; then `UPDATE mockups SET latest_at = created_at WHERE latest_at = ''`.
5. Titles are **not** rewritten.

**Steps**
- [ ] Write `tests/test_versioning.py::test_base_title_table` with the §5 table rows, plus: `comparison_key("Hero — option B") != comparison_key("Hero — option C")`; `comparison_key("Privacy page — draft 1") == comparison_key("privacy  page – Draft 8")`; `base_title("Layout 2") == "Layout"`; `base_title("Layout alt 2") == "Layout alt 2"`; `base_title("v2") == "v2"` (never strip to empty — if stripping would leave nothing, return the original). **Run; see it fail** (module missing).
- [ ] Write the migration test in `tests/test_db.py::test_migration_from_v14_is_idempotent`: build a DB with the **old** `CREATE TABLE mockups` DDL (copy it into the test as a literal — no `latest_at`/`version_count`), insert 3 rows with real files, close; run `init_db()` twice. Assert: 3 designs, 3 versions (all `number == 1`, `file_path` equal to the original), 0 aliases, `latest_at == created_at`, titles unchanged, file bytes unchanged, `list_mockups(sort="newest")` order equal to the pre-migration `created_at DESC` order. **Run; see it fail.**
- [ ] Implement schema + migration + `insert_mockup` change; run the full suite — all 84 existing tests must still pass.
- [ ] Write tests for the versioning core, then implement: `add_version` → v2 exists, `version_count == 2`, `latest_at == v2.created_at`, design mirrors v2, **design title becomes `base_title(v1.title)`**, v1 file untouched; a third version does **not** re-derive the title after a manual `update_mockup(title=…)`; `add_version` with a db failure (monkeypatch `insert_version` to raise) leaves no new file; `find_fold_target` returns id on exactly one match, `None` on two, `None` across projects; `resolve` for design id / alias id / unknown id / unknown number.
- [ ] **RF-1:** add v2, v3 → `delete_version(v3)` → mirrors equal v2, `version_count == 2`, `latest_at == v2.created_at`, v3 file gone, title unchanged; `delete_version` on a single-version design raises.
- [ ] **RF-2 (data half):** v1 html, v2 png → both files exist with their own extensions; design `content_type == "png"`; `get_version(v1).content_type == "html"`.
- [ ] **RF-3:** create alias `old → (design, 2)` via `insert_alias`, `split_version(design, 2)` → returns `"old"`, alias row gone, `resolve("old") == ("old", 1)`, source design lost v2 and kept numbers (v1, v3 — no renumbering), its mirrors recomputed; `split_version` on a single-version design raises.
- [ ] `delete_design` removes every version file (including `{slug}/{id}/v{n}.*` dirs' files) and the rows (cascade — assert versions and aliases for that id are gone; this also proves `foreign_keys=ON`).
- [ ] `list_mockups`: a design with an old `created_at` and a new v2 sorts first under `newest`; `q="draft 3b"` finds a design whose v1 title contains it; `list_projects` orders by most recent activity.
- [ ] Full suite green; commit (`feat(db): versioned designs — schema, migration, versioning core`).

**Downstream consumers:** chunk 2 (routes/tools call `versioning.*`, `db.get_versions/get_version`), chunk 3 (fold uses `comparison_key`, `insert_version`, `insert_alias`, `refresh_design_mirror`), chunk 5 (UI reads `version_count`, `versions`).

---

## Task 2 — Agent and gallery interfaces

**Files:** modify `app/mcp_server.py`, `app/routes/api.py`, `app/routes/gallery.py`; extend `tests/test_mcp_tools.py`, `tests/test_api.py`, `tests/test_gallery.py`.

**Interfaces consumed:** everything listed as produced in chunk 1.

**Decisions**
- One internal entry point for "store an upload": `_send_mockup(*, db, project, title, description, content, content_type, tags, parent: str | None = None, fold: bool = True) -> dict`. Order: `parent` given → `resolve(parent)` (None → `ValueError("Unknown parent: <id>")`, mapped to **404** by the upload route and `ToolError` by MCP); parent's `project_slug != slugify_project(project)` → `ValueError` mapped to **400**; else `add_version`. No parent and `fold` → `find_fold_target` → `add_version(..., folded=True)` or `create_design`. `fold=False` → `create_design`. Tags on an added version: **union** into the design's tags.
  - To map 404 vs 400 cleanly, raise a small `class UnknownParent(ValueError)` from `app/versioning.py`; the route checks `isinstance` before the generic 400.
- Response shape (both upload and `send_mockup`): today's fields (`id` = design id, `gallery_url`, …) **plus** `view_url` = `{BASE_URL}/view/{id}`, `version`, `version_url` = `{BASE_URL}/view/{id}/v/{n}`, `folded`, and when folded `note` = exactly: `Added as version {n} of '{design title}'. Resend with fold=false if this was meant to be a separate mockup.`
- Upload form: `parent: str | None = Form(None)`, `fold: str | None = Form(None)`; `fold` is false only for `"false"`, `"0"`, `"no"` (case-insensitive); anything else / absent → true.
- `_get_mockup(*, db, id, version: int | None = None)` — resolves aliases; returns design dict + `versions` list (`number`, `title`, `created_at`, `content_type`, `view_url` = `/v/{n}` form) newest first; `view_url` top-level = `/view/{id}` when viewing latest, `/view/{id}/v/{n}` when `version` given or id is an alias; plus `version` (the one being described) and `gallery_url` (`?mockup={id}` or `&v={n}`).
- `_update_mockup`: with `content` → `add_version` (title of the version = the `title` arg if given, else the design's current title; description likewise); **no file is deleted**. Metadata-only unchanged. Tool description changes to: `"Update mockup metadata, or add a new version by supplying content (earlier versions are kept)."`
- New `_split_version(*, db, id, version)` + tool `split_version`. `_delete_mockup(*, db, id, version: int | None = None)` → `delete_version` or `delete_design`. `_set_created_at(..., version: int | None = None)` → updates that version's `created_at` (default latest), then `refresh_design_mirror`; when the version is the design's lowest-numbered one, also sets the design's `created_at` (spec §6.2). (`db.update_version_created_at(db, mockup_id, number, created_at)` — add to db.py here.)
- Instructions string gains, verbatim: `To revise an existing mockup, upload with -F parent=<id> instead of creating a new one. Use -F fold=false only for deliberate variants.`
- API: `GET /api/mockups/{id}` → `_get_mockup` shape (accepts alias ids, `?v=` optional). `POST /api/mockups/{id}/versions/{n}/split` → new design JSON (404 unknown, 409 only version). `DELETE /api/mockups/{id}/versions/{n}` → 204 / 404 / 409. `DELETE /api/mockups/{id}` → `delete_design` (all versions).
- Gallery routes: `/view/{mockup_id}` and `/view/{mockup_id}/v/{number}` share one helper that calls `resolve`, loads the version row, and applies today's header logic (CSP for html/svg, nosniff). Unknown → 404 JSON as today.

**Steps**
- [ ] Update `test_update_mockup_content` and `test_update_mockup_content_type_change_deletes_old_file` for the **intended behaviour change** (spec §6.2): content update creates v2 and v1's file still exists. Rename the second to `..._keeps_old_version_file`. Run — see them fail.
- [ ] Write API tests first (see fail): upload with `parent` → `version == 2`, `folded == False`, v2 served at `/view/{id}`; `parent=<alias>` works; unknown parent → 404 `{"error": "Unknown parent: <id>"}`; parent in another project → 400; auto-fold on exactly one match → `folded == True` and `note` text exact; two candidates → new design; `fold=false` → new design; an `"… option B"` upload next to `"… option A"` → new design.
- [ ] Gallery tests (see fail): `/view/{id}` = latest bytes; `/view/{id}/v/1` = v1 bytes; `/view/{alias}` = pinned version bytes; `/view/{id}/v/99` → 404; **RF-2 (serving half):** html v1 + png v2 → `/view/{id}` `image/png` without CSP, `/view/{id}/v/1` `text/html` **with** `sandbox allow-scripts`.
- [ ] MCP tests (see fail): `get_mockup` lists versions newest first; `get_mockup(version=1)` view_url ends `/v/1`; `split_version` returns a design; `delete_mockup(version=)` on the last version raises `ToolError`; **RF-4:** set v1's `created_at` later than v2's → `get_versions` order and `latest_at` unchanged (still v2).
- [ ] Implement until green; full suite green.
- [ ] Commit (`feat: versions over upload, MCP and /view`).

**Downstream consumers:** chunk 3 (fold is independent of these routes but its `/view/<old id>` test uses the gallery route), chunk 5 (UI calls `/api/mockups/{id}`, the split/delete endpoints, and builds `/view/{id}/v/{n}` links).

---

## Task 3 — Opt-in fold command + docs

**Files:** create `app/fold.py`, `tests/test_fold.py`; modify `README.md`, `CHANGELOG.md`.

**Interfaces consumed:** `versioning.comparison_key`, `base_title`; `db.insert_version`, `insert_alias`, `refresh_design_mirror`, `get_versions`.

**Decisions**
- `async plan_folds(db) -> list[FoldGroup]`, `FoldGroup = {project_slug, base_title, members: [{id, title, created_at}]}` sorted oldest first; only designs with `version_count == 1`; groups of size ≥ 2; key = `(project_slug, comparison_key(title))`; displayed base = `base_title` of the **oldest** member.
- `async apply_fold(db, group) -> None` — one transaction per group: for members 2…n in time order insert a version row on the survivor (next number, member's title/description/content_type/file_path/created_at — **files are not moved or copied**), insert alias `member.id → (survivor, number)`, delete the member's design row; survivor `title = group.base_title`, `tags` = sorted union, `favorite` = max; `refresh_design_mirror`.
  - Deleting the member row must **not** cascade-delete the version row just re-parented to the survivor (it belongs to the survivor now) nor the alias (it points at the survivor). Verify with the test below; order the statements so the member's own `mockup_versions` row is removed explicitly first.
- CLI: `python -m app.fold` requires exactly one of `--dry-run` / `--apply`. Uses `init_db()` (so migration runs first) and the normal data dir. Dry-run prints per group: `{project_slug} · "{base_title}" · {n} mockups` then one line per member `  {created_at[:16]}  {title}  ({id})`; then a total line `{groups} groups, {rows} mockups would become {groups} designs`. `--apply` prints the same, then `folded {groups} groups`. A group that fails is reported (`FAILED {base_title}: {error}`) and skipped; exit code 1 if any failed.

**Steps**
- [ ] Tests first (see fail): dry-run changes nothing (row counts and file listing identical before/after); apply on a 3-member group → 1 design, 3 versions numbered 1–3 in time order, 2 aliases, tags union, favorite kept if any member had it, survivor title = base title; `/view/<member 2 id>` (via the `client` fixture) returns member 2's original bytes; designs that already have 2 versions are never grouped; groups never cross projects; `"option B"` / `"option C"` never group.
- [ ] Implement; full suite green.
- [ ] **Dry-run against a copy of the live DB** (Global constraints) and save the output to the scratchpad; **stop and show the owner the group list.** Do not `--apply` on live in this chunk.
- [ ] Docs: README — new "Versions" section (upload `parent`/`fold`, `/view/{id}/v/{n}`, the fold command and that it is opt-in); MCP tools table updated (`split_version`, `delete_mockup(version)`, `update_mockup` now versions). CHANGELOG `## [Unreleased]` gains the 1.5.0 entries (Added / Changed — call out the `update_mockup` behaviour change and the new "newest" sort by latest version / Migration note).
- [ ] Commit (`feat: opt-in fold command for existing duplicates`).

**Downstream consumers:** the owner (runs `--apply` after release), the release step (changelog).

---

## Task 4 — Compact sidebar, brand bar, collapsed bar

Independent of versioning except the readout's design count. Can run in parallel with chunks 1–3 if dispatched separately; it only touches `gallery.html` / `style.css`.

**Files:** modify `app/templates/gallery.html`, `app/static/style.css`.

**Decisions (spec §8.1, §8.2; mockups linked in the spec header)**
- **Brand bar** replaces `.sidebar-brand`: 48px (`var(--meta-h)`), Frame mark (SVG from the "Brand bar options" mockup, 22px), `Mockups <em>MPC</em>`, right-aligned mono readout `{N} designs · v{version}` (N = sum of `/api/projects` counts; version from the template's existing `{{ version }}`), setup-guide link as an icon button (keeps `id="guide-link"` and its show/hide logic). Background: `radial-gradient(120px 60px at 27px 50%, rgba(34,211,238,.16), transparent 70%), linear-gradient(90deg, rgba(34,211,238,.05), transparent 55%)`.
- **Scope row** replaces `.sidebar-projects`: `button.scope-btn` (current scope name + count + ▾, `aria-haspopup`, `aria-expanded`) and `button.fav-toggle` (★ + favorites count, `aria-pressed`). The popover `.scope-pop` holds `input.scope-filter` and the project list (All projects first, divider, then `/api/projects` order = most recent activity). Filter matches project name case-insensitively. Selecting sets `state.activeProject` exactly as the old list did (`null` / slug); the ★ toggle sets `state.activeProject = FAVORITES` / back to `null`. Esc, outside click and selection close it. Reuse the header popover conventions from 1.4.3 (`closeMenus`-style single close function, `window` blur closes).
- Remove the now-orphaned CSS (`.sidebar-projects`, `.project-list`, `.project-item*`, `.project-divider`, `.project-name`, `.project-count`, `.section-label` if unused elsewhere — grep first) and the `renderProjects` list code it replaces. Leave `.sort-seg` and the search input unchanged.
- **Collapsed bar** (`.shell.sb-collapsed` on desktop, drawer closed on mobile ≤720px): viewer bar stays 48px; left block becomes two tiers: `.bar-eyebrow` (10px Frame mark + `MOCKUPS·<b>MPC</b>`, mono 8px, `letter-spacing: .14em`, uppercase, ghost colour, "MPC" in `--accent-dim`, glow `radial-gradient(140px 26px at 30px 0%, rgba(34,211,238,.12), transparent 75%)`) above one row (menu, star, copy, pop-out; buttons 26px tall). The menu toggle stops being `position:absolute` in this state and joins the row. From the separator on: single row, vertically centred in 48px, title 15px (13px expanded). Expanded state is unchanged from 1.4.3 apart from the brand bar.
- Mobile drawer: the scope row and brand bar live inside the drawer; the collapsed-bar layout applies whenever the drawer is closed.

**Steps**
- [ ] Add a pytest in `tests/test_gallery.py` asserting the served HTML contains `class="brand-bar"`, `id="scope-btn"`, `class="bar-eyebrow"` and no longer contains `id="project-list"` (see fail).
- [ ] Implement.
- [ ] Browser check on the throwaway instance (seed ≥ 12 projects and ≥ 30 mockups): desktop 1280 expanded and collapsed, 375 drawer open and closed. Assert with Playwright: brand bar height 48 == viewer bar height; picker opens/filters/selects and the feed reloads for that project; ★ toggle filters favorites; collapsed: eyebrow `top < ` button-row `top`, title font-size 15px, bar height 48; no console errors. Screenshots to the scratchpad, reviewed before commit.
- [ ] Full suite green; commit (`feat(ui): compact sidebar — brand bar, scope picker, collapsed eyebrow`).

**Downstream consumers:** chunk 5 (feed rows live under the new scope row; version UI must not re-add height).

---

## Task 5 — Version UI

**Files:** modify `app/templates/gallery.html`, `app/static/style.css`.

**Interfaces consumed:** `GET /api/mockups` items (`version_count`, `latest_at`), `GET /api/mockups/{id}[?v=n]` (`versions`, `version`), `POST …/versions/{n}/split`, `DELETE …/versions/{n}`, `DELETE /api/mockups/{id}`.

**Decisions (spec §8.1, §8.3)**
- State: `state.activeMockupId` stays the design id; add `state.activeVersion` (number or `null` = latest). URL: `?mockup={id}` for latest, `&v={n}` for a pinned version (gallery links may use query strings; only `/view` links must not).
- Feed row: base title (design `title`); `button.ver-chip` `"{n} versions"` only when `version_count >= 2`; chip click (stopPropagation) toggles `.ver-list` under the row, fetched from `/api/mockups/{id}` on first open and cached per row until the feed reloads. Rows `v{n}` · title · time; latest gets a `latest` tag; active version highlighted. Hover shows `button.ver-split` (always visible under `@media (hover: none)`).
- Viewer: iframe/img `src` = `/view/{id}` for latest or `/view/{id}/v/{n}`; header pill `.ver-pill` after the title: `v{n} · latest` or `v{n} of {count}` with class `old` (amber). Copy-link and pop-out use the same URL rule. Details popover adds `Versions: {count}`.
- Split: `confirm("Split v{n} '{title}' into its own mockup?")` → POST split → reload feed, select the new design. Delete on a design with `version_count >= 2`: `confirm("Delete '{title}' and all {n} versions?")`; single-version designs keep today's behaviour.
- Alias deep link: `?mockup=<alias>` → `/api/mockups/<alias>` returns the target design + `version`; the UI replaces the URL with `?mockup={design id}&v={n}` (history.replaceState) — **RF-5**.

**Steps**
- [ ] Browser checks drive this chunk (no JS test harness exists). On the throwaway instance, seed a design with 4 versions (via `parent`), one alias (via `python -m app.fold --apply` on the throwaway data), and single-version designs. Assert with Playwright: chip only on the multi-version row; chip toggles the list without changing the selection; clicking v2 → iframe src ends `/v/2`, pill text `v2 of 4` with class `old`, copy-link clipboard ends `/v/2`; clicking the row → latest, pill `v4 · latest`, copy-link ends `/view/{id}`; split v2 → feed gains a design, source shows `3 versions`; delete prompts with the count; **RF-5** `?mockup=<alias>` opens the pinned version and rewrites the URL; phone width: split visible without hover; no console errors.
- [ ] Full suite green; commit (`feat(ui): version history, pill, split`).

**Downstream consumers:** release.

---

## After Task 5 (controller only)

- [ ] Whole-branch review (integration lens: chunk 1's invariants honoured by chunks 2/3/5; error mapping 404/400/409 consistent across API, MCP and UI; no orphaned CSS/JS from chunk 4).
- [ ] Owner approves the live fold dry-run list (from chunk 3).
- [ ] Release 1.5.0 per the 4-step process (owner runs `mcp-publisher login github` first). Deploy. Then, with the owner's go-ahead, `docker exec mockups-mpc python -m app.fold --apply`, and verify a sampled folded group in the browser plus `/view/<old id>` for one alias.

**Pre-existing drift noticed, not in scope:** `pyproject.toml` still says `version = "1.3.1"`; the release process does not bump it. Raise with the owner; do not change it in this plan unless asked.
