# Handoff — post-review follow-ups (2026-06-05)

Written after shipping **v1.4.0**, which remediated 31 of 32 findings from the first
full multi-agent code review. This handoff covers the three follow-ups Kyle wants
next, in priority order, plus one P3 deliberately left unfixed and the workflow
gotchas that bit this session.

Start with the **deployment reality** and **workflow notes** at the bottom before
touching anything — they will save you a deploy mistake.

---

## State of the world

- **UPDATED 2026-06-05 (session 2):** `main` is at **v1.4.1**, pushed, GHCR has
  `1.4.1` + `latest` (local build, no `v*` tag). Running prod container = v1.4.1.
  **84 tests pass.** Follow-up 1 (cache-bust) shipped; Follow-up 3 (thumbnails)
  shelved. Only Follow-up 2 (auth) remains. See the session-2 handoff:
  `docs/handoffs/2026-06-05-session2-deploy-and-release.md`.
- The review's full findings were in a `/tmp` workflow output (ephemeral, likely
  gone now). The actionable remainder is captured below — you don't need it.

---

## Follow-up 1 — Stylesheet cache-bust — DONE (shipped in v1.4.1, 2026-06-05)

Implemented as specified: `gallery.html` href is now
`/static/style.css?v={{ version }}`, version sourced from `config.APP_VERSION`
(reads the root `VERSION` file, `"dev"` fallback). **Gotcha caught:** the `VERSION`
file was NOT in the image — the Dockerfile only did `COPY app/ app/` — so a naive
"read the VERSION file" would have silently fallen back to `"dev"` in prod. Fixed
by adding `COPY VERSION .` to the Dockerfile. Test:
`tests/test_gallery.py::test_gallery_stylesheet_is_cache_busted`.

---

## Follow-up 2 — Auth lockdown — SHELVED (2026-07-02)

**Decision (Kyle, 2026-07-02): shelved — not worth it for now.** A bearer token is a
shared secret that has to be manually distributed to every client (agent `curl`
commands via `~/.claude/CLAUDE.md` + in-app setup guide + MCP `instructions` string;
MCP tool calls via `.mcp.json` headers). That's churn across all the docs/config to
defend a server that is **not internet-reachable** — the Traefik LAN-only IP allowlist
already covers the real threat model. The one narrow win it would buy (a popped-out
mockup's injected JS can't fire a `DELETE` because it lacks the token) doesn't justify
the cost right now. Revisit only if the deployment ever becomes internet-exposed, or if
Kyle reopens it. Original spec kept below for whoever picks it up.

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

## Follow-up 3 — Feed thumbnails — SHELVED (2026-06-05)

**Decision (Kyle, 2026-06-05): shelved.** Not worth the cost/complexity right now;
the feed stays text-only. Revisit only if Kyle reopens it. Reasoning below, kept
for whoever picks this up later.

**Problem:** the feed (`createFeedItem` in `app/templates/gallery.html`) is
text-only. Thumbnails were explicitly deferred in the v1.3.0 spec
(`docs/specs/2026-05-20-favorites-ui-uplift-design.md` — read it for prior
thinking). Kyle wants the gallery more visual.

**Why Phase 1 alone doesn't deliver here (the load-bearing fact):** the live
gallery is **86% HTML** — 370 `html` vs 58 `png`, zero `svg`/`jpg` (queried from
prod `./data/mockups.db` on 2026-06-05). The original Phase 1 plan below renders
real thumbnails only for image types and shows a placeholder glyph for `html`, so
it would cover just the **58 PNGs (14%)** and leave the **370 HTML mockups (86%)**
as glyphs — i.e. the gallery would look essentially as text-y as it does now. The
real visual win lives entirely in **rendered HTML thumbnails (Phase 2)**, which is
the expensive part. So the actual fork is "rendered HTML thumbnails or nothing,"
NOT "Phase 1 vs Phase 2." If reopened, lean toward keeping Chromium OUT of the
always-on prod container (sidecar / one-shot renderer writing `<id>.thumb.png`
into `./data`, main app serves the thumb only if it exists; backfill existing).

**Original phased approach (kept for reference — note Phase 1's weak coverage above):**
- **Phase 1 (cheap, no new deps):** for image types (`png`/`jpg`/`svg`), the
  thumbnail is just the existing file rendered small via CSS — serve through the
  existing `/view/{id}` and size it in `.feed-item`. For `html` mockups, show a
  type glyph/placeholder (no render). NOTE: only ~14% coverage given current data.
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
- **GHCR push is LOCAL; the Docker workflow is manual-only.** As of 2026-07-02
  (commit `cc4496b`), `.github/workflows/docker.yml` is `workflow_dispatch` only —
  it **no longer triggers on `v*` tags**, so tagging a release is now safe and does
  NOT kick off an Actions build. (This inverts the old "never push a `v*` tag" rule;
  that rule existed only to dodge the redundant Actions build, which is now off.)
  **Full release process (all four steps):**
  1. Bump `VERSION` + `server.json` (version field **and** the `ghcr.io/...:<ver>`
     identifier) + add a `CHANGELOG.md` entry; commit; `git push origin main`
     (fires `ci.yml` = tests only).
  2. Build + push the image locally:
     `docker build -t ghcr.io/kgnatx/mockups-mpc:<ver> -t ghcr.io/kgnatx/mockups-mpc:latest . && docker push` (both tags).
  3. Tag + GitHub Release:
     `gh release create v<ver> --target main --title "v<ver>" --notes "<CHANGELOG entry>"`.
     Targeting `main` HEAD keeps the tag on a commit whose workflow is manual-only,
     so no build fires.
  4. Publish to the MCP registry: `mcp-publisher login github` (interactive — Kyle
     must authorize in a browser; the saved token expires) then `mcp-publisher
     publish`. The registry **rejects duplicate versions** (works only on a fresh
     bump) and **caps `description` at 100 chars** (`mcp-publisher validate` first).
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

1. ~~Cache-bust~~ — **DONE, shipped in v1.4.1** (see Follow-up 1).
2. Auth lockdown — **ask Kyle the two scope questions first**, then implement.
   This is now the ONLY open follow-up.
3. ~~Thumbnails~~ — **SHELVED 2026-06-05** (see Follow-up 3). Gallery is 86% HTML,
   so the cheap path covers only 14%; the real win needs rendered HTML thumbnails,
   which isn't worth it right now. Don't pick this up unless Kyle reopens it.

Each should be its own branch off `main`, tested, then merged + deployed + (if you
cut a release) version-bumped and pushed to GHCR per the workflow notes.
