# Handoff — session 2: container recovery + v1.4.1 (2026-06-05)

## TL;DR

Recovered the prod container after a botched "update to latest," shelved the feed
thumbnails idea, and shipped **v1.4.1** (stylesheet cache-bust). Site is live and
healthy at mockups.hippienet.wtf serving `?v=1.4.1`. The only open follow-up from
the prior handoff is now **Follow-up 2 — auth lockdown** (needs Kyle's scope answers).

## What shipped

1. **Container recovery.** The site was down because a redeploy used the wrong
   compose file. `docker-compose.local.yml` (dev) publishes host port 8000, which
   collides with the `ghost-ghost-1` container → the mockups container stuck in
   `Created` with `Bind for 0.0.0.0:8000 failed: port is already allocated`. Fix:
   use the prod compose. Added a dev-only warning header to the local compose file
   (commit `a29292f`).
2. **Thumbnails — SHELVED.** The gallery is 86% HTML (370 html / 58 png, queried
   from prod `data/mockups.db`). The cheap "Phase 1" path covers only the 14% that
   are images; real win needs headless-rendered HTML thumbnails, not worth it now.
   Recorded in the prior handoff's Follow-up 3 + memory (commit `37b0ff9`).
3. **v1.4.1 — stylesheet cache-bust.** `gallery.html` href →
   `/static/style.css?v={{ version }}`, version from `config.APP_VERSION` (reads
   root `VERSION`, `"dev"` fallback). **Added `COPY VERSION .` to the Dockerfile** —
   it wasn't in the image before, so a naive read would've fallen back to `"dev"`.
   TDD'd (`test_gallery_stylesheet_is_cache_busted`), 84 tests pass. Full release:
   VERSION/server.json/CHANGELOG bumped, pushed to main, GHCR `:1.4.1` + `:latest`
   pushed (no `v*` tag). Commits `c4aed11`, `2bde489`, `8bb08e4`.

## State of the world

- `main` at **v1.4.1**, CI green. Prod container rebuilt from source, `healthy`,
  serving the gallery with `?v=1.4.1`. 84 tests: `.venv/bin/python -m pytest -q`.
- Deploy command (server only): `docker compose -f docker-compose.yml up -d --build`.

## Carry-forward gotchas (also in auto-memory)

- **Compose files:** `docker-compose.yml` = prod (Traefik, no host ports);
  `docker-compose.local.yml` = laptop only (binds 8000, collides with Ghost). Never
  use the local one on the server.
- **Deploy health-blip:** during each redeploy the public site serves an unrelated
  "Hell-NO-World" fallback page for ~20-30s — Traefik waits for the 30s-interval
  healthcheck before routing to the container. It's a transient, NOT a fault.
- **Verify deploys properly:** wait for `docker ps` → `(healthy)`; use `curl -4`
  (no IPv6 record; default curl may take a Cloudflare/v6 path); a bare `200` is not
  proof — check `<title>` is `Mockups MPC` and href is `/static/style.css?v=<VERSION>`.
  (Pre-existing note still holds: curl to `/static/style.css` hits a *different*
  nginx and 404s — verify CSS via `docker exec` or the browser.)

## What is NOT done / open

- **Follow-up 2 — auth lockdown** (the only remaining item). Full spec in
  `docs/handoffs/2026-06-05-post-review-followups.md`. **Blocked on two scope
  questions for Kyle** before any code: (1) which endpoints — just `DELETE`, or all
  writes + MCP tools? (2) the documented agent `curl` upload workflow has no auth
  header — is he OK updating that command + the MCP `instructions` string? Don't
  start until answered.
- P3 marquee font-load race — deliberately left as-is (self-corrects on hover).

## Commit trail

`a29292f` local-compose warning · `37b0ff9` shelve thumbnails ·
`c4aed11` cache-bust impl · `2bde489` merge · `8bb08e4` release 1.4.1 ·
(this wrap-up's docs commit follows).
