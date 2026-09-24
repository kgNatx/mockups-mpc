# Mockup versions + compact sidebar — design

**Date:** 2026-09-24 · **Target release:** 1.5.0 · **Status:** approved in brainstorming, awaiting spec review (owner)

Mockups: [Compact sidebar](https://mockups.hippienet.wtf/?mockup=e4a7673b-d7a1-4fac-8c08-933d2fa92777) (option A chosen) ·
[Sidebar with versions](https://mockups.hippienet.wtf/?mockup=0529a48d-1741-41eb-ad09-41a99d37ba54) ·
[Brand bar options](https://mockups.hippienet.wtf/?mockup=dfe66248-804f-4e12-8737-4088906570e2) (glow + readout, Frame mark chosen) ·
[Collapsed bar final](https://mockups.hippienet.wtf/?mockup=bacb9428-25f5-4c05-91e3-b8bde08d0a15)

## 1. Problem

The gallery fills with near-duplicates. Agents iterate by uploading a new mockup each time, because the
cheap path (`curl` to `/api/upload`) can only create, and `update_mockup` both pushes the whole file
through model context and overwrites history. Measured on the live instance (2026-09-24, 948 mockups):
at least 54 iteration groups holding 137 rows; the largest is "Privacy page — draft 1 … draft 8"
(9 rows in 56 minutes). Only 6 pairs share an exact title — agents mark iterations in the title.

Separately, the sidebar's project list (32 projects) takes most of the sidebar's height, while the
owner mostly uses the feed ("most recent at the top").

## 2. Goals and non-goals

**Goals**
- One feed row per design, showing its latest version; earlier versions one click away, in order.
- Agents add a version with the same cheap `curl` upload, by naming the parent — or automatically
  when the title is clearly an iteration of an existing design.
- Every existing link keeps working, including links to mockups that get folded.
- Any fold, automatic or scripted, can be undone per version (Split).
- A version-specific direct link exists and never changes what it shows.
- Upgrading an existing install is safe: nothing merges without the owner running a command.
- The sidebar gives its height back to the feed.

**Non-goals**
- Diffing versions, branching, or merging two designs from the UI.
- A rename control in the UI (rename via `update_mockup(title=…)`).
- Folding variants (option A / option B) — they stay separate designs by rule.

## 3. Data model

`mockups` keeps its meaning of "the thing in the list" — now a **design**. `mockup_versions` holds
content. One write function (§3.4) owns every change that touches both.

### 3.1 `mockups` (existing table)

| column | change |
|---|---|
| `id`, `project`, `project_slug`, `tags`, `favorite`, `created_at` | unchanged. `created_at` = first version's time. |
| `title` | display title. A single-version design keeps its full title. When a design gains its **second** version, `title` becomes `base_title(v1.title)` (§5); after that it changes only via `update_mockup(title=…)`. |
| `description`, `content_type`, `file_path` | kept, **mirror the latest version** (so existing readers keep working). |
| `updated_at` | unchanged meaning (last metadata or version change). |
| `latest_at` | **new**, TEXT NOT NULL: the latest version's `created_at`. Indexed. Sort key for "newest". |
| `version_count` | **new**, INTEGER NOT NULL DEFAULT 1. |

### 3.2 `mockup_versions` (new)

| column | type | notes |
|---|---|---|
| `mockup_id` | TEXT NOT NULL | FK → `mockups.id`, ON DELETE CASCADE |
| `number` | INTEGER NOT NULL | 1-based; `PRIMARY KEY (mockup_id, number)` |
| `title` | TEXT NOT NULL | the title as uploaded, e.g. "Privacy page — draft 3b (rail fixed)" |
| `description` | TEXT | as uploaded |
| `content_type` | TEXT NOT NULL | |
| `file_path` | TEXT NOT NULL | relative to the data dir |
| `created_at` | TEXT NOT NULL | |

- **Numbers are never reused.** New version = `MAX(number) + 1`. Deleting a version leaves a gap, so
  `/v/{n}` can never start pointing at different content.
- A design always has ≥ 1 version.

### 3.3 `mockup_aliases` (new)

| column | type | notes |
|---|---|---|
| `alias_id` | TEXT PRIMARY KEY | a former `mockups.id` |
| `mockup_id` | TEXT NOT NULL | FK → `mockups.id`, ON DELETE CASCADE |
| `number` | INTEGER NOT NULL | the version the old id now means |

An alias id resolves to **that version, pinned** — it showed one fixed file before the fold and keeps
showing that file after.

### 3.4 Invariants and the single write path

All version writes go through `app/versioning.py` (module boundary: routes and MCP tools never write
`mockup_versions` directly). Each operation is one transaction that keeps `mockups` mirror columns,
`latest_at`, and `version_count` consistent with `mockup_versions`:

- `add_version(db, mockup_id, *, title, description, content_type, content) -> VersionRef`
- `create_design(db, *, project, title, description, content_type, content, tags) -> VersionRef` (v1)
- `split_version(db, mockup_id, number) -> str` (new design id)
- `delete_version(db, mockup_id, number)` — refuses on the last version (`ValueError`)
- `resolve(db, id, number=None) -> (mockup_id, number) | None` — accepts a design id or an alias id

`VersionRef` = `{mockup_id, number, folded: bool}`. File write happens before the DB transaction; on DB
failure the new file is removed (no orphan). Existing files are never moved.

### 3.5 Files

- Existing files stay where they are; v1 of every existing mockup points at its current `file_path`.
- New versions: `{project_slug}/{mockup_id}/v{n}.{ext}`.
- Deleting a design deletes every version's file. Deleting a version deletes its file.

## 4. Migration

### 4.1 Automatic, on startup (in `init_db`, idempotent like `_migrate_favorite_column`)

1. Create `mockup_versions`, `mockup_aliases` (IF NOT EXISTS); add `latest_at`, `version_count` if absent.
2. For every `mockups` row with no versions: insert v1 from its own `title`, `description`,
   `content_type`, `file_path`, `created_at`; set `latest_at = created_at`, `version_count = 1`.
   **Titles are not rewritten** — base-title normalisation only happens on fold.
3. Nothing merges. The list looks identical after upgrade.

Must hold: running it twice changes nothing the second time; a v1.4.x database with N mockups ends
with N designs, N versions, 0 aliases.

### 4.2 Opt-in fold command

```
python -m app.fold --dry-run     # print proposed groups, change nothing
python -m app.fold --apply       # perform them
```

- Groups = designs with `version_count = 1` sharing `(project_slug, base_title(title))`, size ≥ 2.
  Designs already carrying several versions are left alone (they were grouped deliberately).
- Within a group, order by `created_at`. The **oldest** design survives; the others become versions
  2…n in time order, their ids become aliases to their version numbers, their rows are deleted.
- Survivor gets: `title = base_title` of the group, `tags` = union, `favorite` = any member's.
- Dry-run output per group: project, base title, and each member's `created_at` + original title.
- Documented in README and the 1.5.0 changelog entry.

## 5. Base title (the fuzzy rule)

`base_title(title: str) -> str` in `app/versioning.py`; the only definition, used by upload, MCP, and fold.
Comparison key = `base_title(t).casefold()` with whitespace collapsed.

**Strips** (as a trailing token, with any preceding ` — `, ` – `, ` - `, `:` or `,`):
`v2`, `V3`, `v2.1`, `draft 4`, `rev 2`, `r5`, `iteration 3`, `iter 3`, `round 2`, `take 2`,
a number with an optional letter (`3`, `3b`), and trailing parentheticals (`(rail fixed)`), repeatedly.
Repeats until nothing strips ("draft 3b (rail fixed)" → base).

**Keeps** (variant markers — never stripped): `option B`, `variant C`, `alt 2`, and a standalone
trailing `A`/`B`/`C`/…

Test table (must be seen to fail before the function exists), from real titles:

| title | base |
|---|---|
| Privacy page — draft 3b (rail fixed) | Privacy page |
| Privacy page — draft 8 | Privacy page |
| Entangram hero v7 | Entangram hero |
| Strata landing — r5 | Strata landing |
| Hero — option B | Hero — option B |
| Hero — option C | Hero — option C *(≠ previous: must not fold)* |
| Layout A | Layout A |
| Scan signature chart (v2) | Scan signature chart |

## 6. Agent interfaces

### 6.1 `POST /api/upload`

New optional form fields:
- `parent=<id>` — add a version to that design. Accepts a design id or alias id. Unknown → **404**
  `{"error": "Unknown parent: <id>"}`; never silently creates. `project` must still be sent (form stays
  compatible); if it differs from the parent's project → **400**.
- `fold=false` — skip automatic folding; always create a new design.

Automatic fold (no `parent`, `fold` not false): if **exactly one** design in the same `project_slug`
has the same comparison key, add a version to it. Zero or ≥ 2 matches → new design.

Response adds: `version` (int), `version_url` (`{BASE_URL}/view/{id}/v/{n}`), `folded` (bool), and when
`folded` is true a `note`: `"Added as version {n} of '{design title}'. If this was meant to be a
separate mockup, split it out with split_version(id, {n}) or POST /api/mockups/{id}/versions/{n}/split."` `id`, `view_url`, `gallery_url` keep their meaning (the design).

### 6.2 MCP tools

- `send_mockup` — gains `parent: str | None`, `fold: bool = True`; same semantics and response fields.
- `update_mockup` — **behaviour change:** supplying `content` adds a version (was: overwrite). Metadata-only
  update unchanged. Changelog calls this out.
- `get_mockup(id, version: int | None = None)` — returns the design plus `versions: [{number, title,
  created_at, content_type, view_url}]` (newest first). With `version`, `view_url` is that version's.
- `split_version(id, version)` — **new**. Returns the new design (reusing the alias id if one exists
  for that version, so old links become a normal standalone mockup again).
- `delete_mockup(id, version: int | None = None)` — without `version` deletes the design and all
  versions; with it deletes one version; refuses the last one.
- `set_created_at(id, created_at, version: int | None = None)` — defaults to the latest version
  (that is what orders the list). Setting the first version's time also sets the design's `created_at`.
- `list_mockups` — unchanged signature; each item gains `version_count`.
- Server `instructions` gain: *"To revise an existing mockup, upload with `-F parent=<id>` instead of
  creating a new one. Use `-F fold=false` only for deliberate variants."*

### 6.3 Gallery API (for the UI)

- `GET /api/mockups` — items gain `version_count`, `latest_at`; `sort=newest` orders by `latest_at DESC`.
  Search `q` also matches any version's title (`EXISTS` on `mockup_versions`).
- `GET /api/mockups/{id}` — gains `versions` (as `get_mockup`). Accepts alias ids.
- `POST /api/mockups/{id}/versions/{n}/split` → new design JSON.
- `DELETE /api/mockups/{id}/versions/{n}` → 204; 409 on last version.
- `GET /api/projects` — ordered by most recent `latest_at` (was: by count), with `count` = designs.

## 7. Links

| URL | shows |
|---|---|
| `/view/{id}` | latest version (design id) or the pinned version (alias id) |
| `/view/{id}/v/{n}` | version n, fixed; 404 if n doesn't exist |
| `/?mockup={id}` | gallery on the latest version |
| `/?mockup={id}&v={n}` | gallery on version n |

Version links use a **path segment**, not a query string: portal proofs (slipwave) refuse query strings.
The existing CSP sandbox + nosniff headers apply to every `/view` variant.

## 8. UI

### 8.1 Sidebar

- **Brand bar** — height `var(--meta-h)` (48px), aligned with the viewer bar. Treatment "glow +
  readout": radial cyan glow behind the mark + faint left-to-right wash; **Frame** mark (browser window
  glyph); wordmark "Mockups" + dimmed "MPC"; right side a mono readout `{N} designs · v{VERSION}` and the
  setup guide as an icon button. No left rail. (`{N}` = total designs, from `/api/projects` counts.)
- **Scope row** — replaces the project list: a picker button showing the current scope ("All projects"
  + count, ▾) and a ★ favorites toggle with its count. The picker opens a popover with a filter input and
  the projects, most recently active first, each with a count. Selecting closes it. Esc / outside click
  close it. The "★ First" sort stays.
- **Feed rows** — one per design, showing the base title. A `N versions` chip only when
  `version_count ≥ 2`. The chip toggles an inline history under the row (row click still opens the
  latest): each version as `v{n}` · its own title · time, latest marked "latest". Hover (always on
  touch) reveals a Split action.
- Deleting a design with `version_count ≥ 2` confirms: *"Delete '{title}' and all {n} versions?"*.
  Split confirms, naming the version and that it becomes its own mockup.

### 8.2 Collapsed sidebar (desktop collapsed, or phone with the drawer closed)

Mockup: [Collapsed bar final](https://mockups.hippienet.wtf/?mockup=bacb9428-25f5-4c05-91e3-b8bde08d0a15).

- The viewer bar **stays 48px** (nothing below it moves on collapse/expand).
- The sidebar brand bar and its readout are gone with the sidebar. The brand reappears as a tiny
  **eyebrow** at the top-left of the viewer bar: Frame mark (10px) + `MOCKUPS·MPC` in mono, 8px,
  uppercase, letter-spaced, "MPC" in `--accent-dim`; a soft cyan glow behind it at the top-left.
- **Left of the separator — two tiers:** the eyebrow on top; beneath it one row of buttons (menu,
  favorite, copy, pop-out) at 26px tall, left-aligned to the same edge as the eyebrow. The menu button
  is no longer a separate 48×48 cell.
- **From the separator rightward — one tier, vertically centred in the full 48px:** title at 15px
  (13px when expanded) with the version pill, then the right-hand icons (viewport, fullscreen, details).
- Expanding the sidebar returns the bar to its expanded layout (§8.1, §8.3); only CSS state changes
  (`sb-collapsed` / `nav-open` classes already exist).

### 8.3 Viewer bar

- A version pill after the title: `v{n} · latest`, or `v{n} of v{latest}` in amber on an older version.
  (Amended s007: was `v{n} of {count}`, which reads "v5 of 3" once deleted versions leave gaps.)
- Copy direct link and pop-out use `/view/{id}` on the latest (link follows future versions) and
  `/view/{id}/v/{n}` on an older version.
- The details popover gains a "Versions" line.

## 9. Error handling

- Unknown `parent`, unknown version, unknown id → 404 with a JSON `error`.
- Deleting the last version → 409 (API) / `ValueError` (MCP) naming `delete_mockup` without `version` as
  the way to delete the design.
- File write succeeds but DB transaction fails → new file removed; nothing half-written.
- Fold `--apply` runs each group in its own transaction; a failing group is reported and skipped.

## 10. Testing

pytest, extending the existing suites. Must be seen to fail first: the §5 title table; migration
idempotence; alias resolution; `/view/{id}/v/{n}`.

- `base_title`: the §5 table, plus variants never sharing a key.
- Migration: build a v1.4.x-shaped DB with 3 mockups → run `init_db` twice → 3 designs, 3 versions,
  0 aliases, files untouched, list order unchanged.
- Upload: `parent` adds v2 and bumps `latest_at`; alias as `parent` works; unknown parent 404; project
  mismatch 400; auto-fold on exactly one match; no fold on two matches; `fold=false` never folds;
  "option B" upload does not fold into "option A".
- MCP: `update_mockup(content=…)` creates v2 and keeps v1's file; `get_mockup` lists versions;
  `split_version` restores the alias id; `delete_mockup(version=)` refuses the last version.
- Fold: dry-run changes nothing; apply on a 3-member group → 1 design, 3 versions, 2 aliases, tags
  unioned, favorite kept; `/view/<old id>` serves the old file byte-identically.
- Views: `/view/{id}` = latest; `/view/{id}/v/1` = v1; alias id = pinned version; CSP header present on all.
- Before applying the fold on the live instance: run `--dry-run` against a **copy** of the live DB and
  show the owner the group list. `--apply` on live only after approval.
- UI verified in a browser on a throwaway instance (temp data dir), desktop and 375px widths.

## 11. Release

1.5.0 (minor: feature + schema + `update_mockup` behaviour change). Changelog entry covers the
automatic migration, the opt-in fold command, new upload fields, and the `update_mockup` change. README
gains the fold command and upload fields. Standard 4-step release; owner runs
`mcp-publisher login github` before step 4.
