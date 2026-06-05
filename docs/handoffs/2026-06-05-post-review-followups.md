# Handoff — post-review follow-ups (2026-06-05)

Written after shipping **v1.4.0**, which remediated 31 of 32 findings from the first
full multi-agent code review. This handoff covers the three follow-ups Kyle wants
next, in priority order, plus one P3 deliberately left unfixed and the workflow
gotchas that bit this session.

Start with the **deployment reality** and **workflow notes** at the bottom before
touching anything — they will save you a deploy mistake.

---

## State of the world

- `main` is at v1.4.0, pushed to GitHub, CI green. GHCR has `1.4.0` + `latest`
  (built locally, see workflow notes — **do not** push a `v*` git tag).
- Running prod container = the v1.4.0 code (prod compose uses `build: .`).
- 83 tests pass: `.venv/bin/python -m pytest -q`.
- The review's full findings were in a `/tmp` workflow output (ephemeral, likely
  gone now). The actionable remainder is captured below — you don't need it.

---

## Follow-up 1 — Stylesheet cache-bust (smallest, do first)

**Problem:** `app/templates/gallery.html` line ~7 loads `<link rel="stylesheet"
href="/static/style.css">` with no version query. After every deploy Kyle has to
hard-refresh (Ctrl/Cmd-Shift-R) to get new CSS; normal reload serves the cached
copy.

**Fix:** append `?v=<VERSION>` to the href so each release busts the cache.
- `app/routes/gallery.py` `gallery()` already returns a `TemplateResponse`. Read
  the `VERSION` file (or import a version constant) and pass it into the template
  context, then in `gallery.html`: `href="/static/style.css?v={{ version }}"`.
- Consider doing the same for any other static asset linked in the template.

**Test:** assert `GET /` HTML contains `style.css?v=` (e.g. in `tests/test_gallery.py`).

**Effort:** ~15 min. Good warm-up task.

---

## Follow-up 2 — Auth lockdown (defense-in-depth)

**Problem (review security finding, rated P2 under the LAN-only model):** there is
**zero application auth**. Every mutating endpoint is open to anyone who can reach
the port:
- `POST /api/upload`, `DELETE /api/mockups/{id}`, `PUT /api/mockups/{id}/favorite`
  (`app/routes/api.py`)
- the MCP mutation tools: `send_mockup`, `update_mockup`, `delete_mockup`,
  `tag_mockup`, `set_created_at` (`app/mcp_server.py`)

All defense currently rests on the Traefik LAN-only IP allowlist. This is
defense-in-depth, **not urgent** — but Kyle wants it.

**RESOLVE SCOPE WITH KYLE FIRST** — this one has a real UX tension worth a quick
question before coding:
1. **Which endpoints?** Just `DELETE` (most destructive), or all writes + MCP tools?
2. **How does the token reach agent `curl` uploads?** The documented workflow
   (global `~/.claude/CLAUDE.md` "Mockups" rule + `app/static/setup-guide.html`)
   tells agents to `curl -X POST .../api/upload` with **no auth header**. Adding a
   required token means updating that documented command and the MCP server
   `instructions` string in `app/mcp_server.py`. Confirm Kyle wants that churn.

**Recommended approach (pending scope):**
- Add an env var (e.g. `MOCKUPS_WRITE_TOKEN`) in `app/config.py`.
- A FastAPI dependency that checks `Authorization: Bearer <token>` (or `X-API-Key`)
  on the mutating routes. **Backwards-compatible default:** if the env var is
  unset, allow + log a warning (so existing uploads don't break the moment this
  ships); enforce only when a token is configured.
- MCP tools are mounted at `/mcp` via fastmcp — auth there is separate from the
  FastAPI dependency. Check whether fastmcp exposes transport-level auth before
  hand-rolling; the MCP transport may need its own mechanism. If it's hard, gating
  the HTTP `/api` writes alone still closes the stored-XSS amplification path
  (a popped-out mockup's script can't `fetch` a DELETE) and is most of the value.
- Update `app/static/setup-guide.html` and the MCP `instructions` string if the
  upload command changes.

**Tests:** 401/403 without token, success with token, and that reads stay public,
when the token env is set (use `monkeypatch.setenv` + the `client` fixture).

---

## Follow-up 3 — Feed thumbnails

**Problem:** the feed (`createFeedItem` in `app/templates/gallery.html`) is
text-only. Thumbnails were explicitly deferred in the v1.3.0 spec
(`docs/specs/2026-05-20-favorites-ui-uplift-design.md` — read it for prior
thinking). Kyle wants the gallery more visual.

**Recommended phased approach:**
- **Phase 1 (cheap, no new deps):** for image types (`png`/`jpg`/`svg`), the
  thumbnail is just the existing file rendered small via CSS — serve through the
  existing `/view/{id}` and size it in `.feed-item`. For `html` mockups, show a
  type glyph/placeholder (no render). This gets most of the visual win with zero
  backend work.
- **Phase 2 (optional, heavier):** real thumbnails for `html` mockups via a
  headless-render screenshot on upload. This needs a renderer (Playwright/Chromium)
  **in the container** — a big image-size cost. Weigh whether it's worth it vs the
  Phase-1 placeholder. If done: generate on upload in `_send_mockup`
  (`app/mcp_server.py`) + `app/storage.py`, store as e.g. `<id>.thumb.png`, and add
  a `thumb_path` (or `has_thumbnail`) column via an idempotent ALTER-TABLE migration
  — mirror the existing `favorite` migration in `app/db.py` (`_migrate_favorite_column`).

**Gotchas:** SVG served to an `<img>` is safe (scripts don't run there — confirmed),
so SVG thumbnails are fine. Don't sandbox-break: thumbnails should use `<img>`, not
iframes. Keep the 25 MB / type rules consistent with `app/storage.py`.

**Tests:** if you add a column, add a migration-idempotency test (pattern already in
`tests/test_db.py::test_init_db_idempotent_on_rerun`).

---

## Deliberately NOT fixed (P3) — marquee font-load race

`createFeedItem`'s `mouseenter` handler measures `titleText.offsetWidth` to decide
whether to marquee-scroll a long title. If measured during the web-font swap it can
mis-measure. The review's own verifier concluded **no action required** — it
recomputes on every hover and self-corrects within a sub-second window. Left as-is
on purpose. Only revisit if Kyle reports visible title-scroll glitches.

---

## Workflow notes (read before deploying)

- **THIS machine is the prod host.** Prod `docker-compose.yml` uses `build: .`
  (local build, not the GHCR image), Traefik labels, `frontend` external network,
  no published host ports.
- **Deploy = `docker compose up -d --build`.** That rebuilds + restarts the live
  container. Confirm health after: `docker compose ps` (expect `(healthy)` after
  ~20s).
- **`./data` is live prod data** (bind-mounted, root-owned, ~369 mockups). Never
  run a local dev instance against it. To verify UI changes, run a throwaway
  instance on a **temp data dir** (set `app.config.DATA_DIR`/`DB_PATH` to a
  `tempfile.mkdtemp()` before `uvicorn.run`, `BASE_URL=http://localhost:<port>`),
  seed via `curl`, and drive it with the Playwright MCP. That's how v1.4.0 was
  verified.
- **GHCR push is LOCAL, not GitHub Actions.** `.github/workflows/docker.yml`
  triggers on `v*` tags — **do not push a `v*` tag** (Kyle wants local builds).
  Release steps: bump `VERSION` + `server.json` (version field **and** the
  `ghcr.io/...:<ver>` identifier) + add a `CHANGELOG.md` entry; commit; `git push
  origin main` (only fires `ci.yml` = tests); then
  `docker build -t ghcr.io/kgnatx/mockups-mpc:<ver> -t ghcr.io/kgnatx/mockups-mpc:latest .`
  and `docker push` both tags.
- **Deployment is LAN-only** behind a Traefik IP-allowlist on a trusted network —
  NOT internet-exposed. Weight security findings by that threat model (accidental
  footguns from trusted agents > untrusted-internet attackers).
- **Curl gotcha:** `curl` to `https://mockups.hippienet.wtf/static/style.css`
  returns an nginx 404 (a *different* nginx answers that path); `/`, `/api`, and
  `/view` route correctly to the container. Verify CSS/headers via the **browser**
  or `docker exec mockups-mpc ...`, not curl to `/static`.
- **No `Co-Authored-By` trailers** in commits (per Kyle's global rule).

---

## Suggested order

1. Cache-bust (15 min, ships confidence).
2. Auth lockdown — **ask Kyle the two scope questions first**, then implement.
3. Thumbnails — Phase 1 first; check the v1.3.0 spec; decide on Phase 2 with Kyle.

Each should be its own branch off `main`, tested, then merged + deployed + (if you
cut a release) version-bumped and pushed to GHCR per the workflow notes.
