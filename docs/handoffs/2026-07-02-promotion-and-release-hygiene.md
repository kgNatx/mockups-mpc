# Handoff — session 3: promotion polish + release/version reconciliation (2026-07-02)

## TL;DR

Open-source promotion pass. No app code changed — everything shipped is docs,
metadata, and release hygiene. Cleaned up the README, added a demo GIF, reframed
the positioning gallery-first, and **reconciled three drifted version trackers**
(GHCR, MCP registry, GitHub Releases) so they all now agree on **1.4.1**. Also
formally shelved the auth-lockdown follow-up. The board is now clear.

## What shipped (all on `main`, docs-only)

1. **README polish** — CI + MIT badges; corrected the stale test count (said 47,
   suite is 84) by dropping the hard number so it can't re-drift; replaced the
   static screenshot with an animated **demo GIF** (`docs/gallery-demo.gif`,
   9 frames, ~1 MB). Removed the orphaned `docs/gallery-screenshot.png`.
2. **Positioning reframe** — lead with "a self-hosted **gallery** for AI-generated
   mockups, with an MCP interface," not "MCP server and gallery." Corrected the
   mechanics (curl moves the file bytes, MCP only coordinates) and sharpened the
   value prop (no repo clutter, permanent home). Aligned across README,
   `server.json` description, and the GitHub repo description.
3. **Auth lockdown — SHELVED** (was the last open follow-up). A bearer token is a
   shared secret with no distribution mechanism; not worth it for a LAN-only server
   behind a Traefik allowlist. Recorded in the prior handoff (Follow-up 2), memory,
   and second brain. See commit `3cd5a0f`.
4. **Version reconciliation** — the three trackers had drifted:
   - GHCR image: `1.4.1` (current)
   - MCP registry: was frozen at **1.2.2** (March) → **published 1.4.1**, now latest
   - GitHub Releases: was frozen at **v1.2.0** → created **v1.4.1** Release, now Latest
5. **Docker workflow made manual-only** (`cc4496b`) — `.github/workflows/docker.yml`
   changed from `on: push: tags: [v*]` to `workflow_dispatch`. This was the footgun:
   the tag-triggered Actions build is why tagging was avoided, which drifted GitHub
   Releases behind. Now tags are safe → releasing can tag normally.

## Why the versions looked disconnected (the load-bearing fact)

Releases 1.3.0 → 1.4.1 were cut via VERSION bump + local GHCR push **without git
tags**, deliberately, to avoid the tag-triggered Actions build. So the image/registry
marched forward while GitHub tags/Releases froze at v1.2.x. The workflow change +
v1.4.1 Release closes that gap. **Release process is now 4 steps (bump → local build/push
→ tag+Release → mcp-publisher publish)** — full detail in the updated Workflow-notes
section of `docs/handoffs/2026-06-05-post-review-followups.md`.

## State of the world

- `main` at **1.4.1**, CI green. All three version trackers agree on 1.4.1.
- Prod container untouched this session — still `Up 12 days (healthy)`.
- MCP registry: `io.github.kgNatx/mockups-gallery` v1.4.1 `isLatest:true`.
- GitHub Releases: v1.4.1 Latest (tag points at `main` HEAD, not the original June
  1.4.1 commit — app code is byte-identical since only docs changed, so the image
  matches; couldn't tag the original commit without triggering that commit's old
  workflow).

## What is NOT done / open

- **Nothing on the board.** Both prior follow-ups (thumbnails, auth) are shelved.
- Did **not** backfill 1.3.0/1.3.1/1.4.0 GitHub Releases — Kyle's call. Backfilling
  accurately would tag their original commits, which still carry the old tag-trigger
  workflow → each would fire a build. Not worth it for cosmetic history.
- P3 marquee font-load race — still deliberately left as-is (self-corrects on hover).

## Commit trail

`7ed4ae0` README badges + test count · `3cd5a0f` shelve auth ·
`51bd3d6` demo GIF · `32632b5` positioning reframe ·
`1f364d2` trim server.json description to 100-char registry cap ·
`cc4496b` Docker workflow manual-only · (this wrap-up's docs commit follows).
Plus non-git: MCP registry publish (1.4.1), GitHub Release v1.4.1.
