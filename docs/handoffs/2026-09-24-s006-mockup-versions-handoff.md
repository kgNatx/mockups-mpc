# Handoff — mockup versions + compact sidebar, built, not released (2026-09-24)

> **Update (s007, 2026-09-24):** everything listed below as not done was finished, released as 1.5.0, deployed, and the live fold applied. Current state: [s007 handoff](2026-09-24-s007-release-1.5.0-handoff.md).

Session: s006 (estimate — sessions after s3 left no handoffs: v1.4.2 on 07-07, the 421 fix on 07-17)

## TL;DR

Released **1.4.3** (direct-link copy + compact viewer header + MCP 421 fix) and committed a touch-screen
feed fix. Then designed, specced, planned and **built 1.5.0 — versioned mockups + a compact sidebar** on
branch `feat/mockup-versions` (worktree `.worktrees/versions`), subagent-driven: 5 tasks, each task-reviewed,
then an Opus whole-branch review → one fix wave → Opus re-review: **ready to merge, 195 tests pass.**
Owner approved the live fold dry-run list. **Nothing merged, pushed, released or deployed.**

Owner direction for next session: **fold in the deferred minor findings before release**, run one scoped
review of those fixes, then release 1.5.0 and fold the live data.

## Where things are

- `main` (local): 4 commits not pushed — `e9a7108` touch fix, `d69ae10` spec, `4e3b6ca` plan, `3de19b1` plan headings.
- `feat/mockup-versions` (worktree `/home/kyleg/containers/mockups-mpc/.worktrees/versions`): 14 commits on top of `3de19b1`, head `d8b1967`.
- Live server runs **1.4.3 + the touch fix** (deployed uncommitted-then-committed `e9a7108`). All four version trackers at 1.4.3.
- Spec: `docs/specs/2026-09-24-mockup-versions-design.md` (amended in-branch for R24 note text and R26 title rule).
- Plan: `docs/plans/2026-09-24-mockup-versions.md`. **Ledger (every ruling R1–R26 + all deferred minors):** `docs/handoffs/2026-09-24-s006-mockup-versions-ledger.md`.
- Fold dry-run review page (owner approved it): https://mockups.hippienet.wtf/?mockup=1b97a111-aa76-4bcc-85c2-7be874321ded — 51 groups, 131 mockups → 51 designs, 16 flagged (parenthetical-only differences).

## What 1.5.0 is (short)

- **Data:** `mockups` rows are designs; `mockup_versions` holds content; `mockup_aliases` keeps folded ids
  resolving (with `source_number`, so pre-fold `/v/n` links still work). High-water mark
  `last_version_number` — numbers never reused. All writes go through `db.transaction()` (per-connection
  lock, **not re-entrant**). Only `app/db.py` holds SQL; `app/versioning.py` orchestrates.
- **Migration:** automatic and idempotent on startup (adds tables/columns, gives every mockup a v1). Nothing merges.
- **Fold:** `python -m app.fold --dry-run | --apply [--data-dir PATH]` — opt-in, one transaction per group.
- **Agents:** upload `-F parent=<id>` adds a version; no parent → auto-fold on exactly one base-title match
  in the project; `-F fold=false` forces a new design. MCP: `update_mockup(content=)` adds a version;
  new `split_version`; `version` params on `get_mockup`/`delete_mockup`/`set_created_at`.
  Server `instructions` string updated with the `parent=` sentence.
- **Links:** `/view/{id}` latest (alias → its pinned version); `/view/{id}/v/{n}` fixed; gallery `?mockup=&v=`.
- **UI:** brand bar (glow + readout, Frame mark), project picker, collapsed bar with eyebrow; version chip →
  history → split; version pill after the title; viewer follows a new version when unpinned.

## Explicitly NOT done

1. **Deferred minor findings** — listed in the ledger (`minor (deferred)` lines) and the final review's
   "can ship" list (M2, M5, M6, M7). Owner wants them done before release.
2. **Agent-facing docs outside the code:** `app/static/setup-guide.html` (the in-app Setup Guide) has no
   versions content; Kyle's global `~/.claude/CLAUDE.md` "Mockups" section still shows a curl with no
   `-F parent=` — that file is Kyle's; propose the one-line change, don't edit unasked.
3. Merge, push, 1.5.0 release, deploy, live `fold --apply`.
4. `pyproject.toml` still says `1.3.1` (pre-existing drift; release process never bumps it — ask).

## Release + deploy sequence (after the minors)

1. Merge `feat/mockup-versions` → `main` (run the suite on the merged tree), push `main`.
2. Release 1.5.0 per the 4-step process (memory `project_release_process`): bump `VERSION` + `server.json`
   + CHANGELOG `[Unreleased]` → `[1.5.0]`; build + push GHCR `1.5.0` + `latest`; `gh release create v1.5.0`;
   `mcp-publisher publish` (**ask Kyle to run `mcp-publisher login github` first** — the token expires).
3. Deploy: `docker compose -f docker-compose.yml up -d --build` (startup migration runs; wait for healthy,
   verify with `curl -4`, and an MCP `initialize` handshake).
4. **Back up `data/mockups.db` first**, then `docker exec mockups-mpc python -m app.fold --apply`.
   Spot-check one folded group in the browser and one `/view/<old id>`.

## Process lessons (this session)

- Subagents launched long tracked background tasks and idled → hung Playwright (no `browser.close()` in
  `finally`). Dispatch prompts now require foreground runs + log files + `setDefaultTimeout`.
- A subagent's self-test measured a stretched box, not the text — the controller caught the pill
  placement only by **looking at screenshots**. Keep "controller eyeballs screenshots" for UI tasks.
- Two implementer questions caught real plan defects (version-number reuse; the shared aiosqlite
  connection not serialising coroutines). The inbox-file protocol worked.

## Commit trail

main: `20c538e` 421 fix · `680e4d4` direct link + compact header · `38782fe` release 1.4.3 · `e9a7108` touch fix ·
`d69ae10` spec · `4e3b6ca` plan · `3de19b1` plan headings. Branch: `4e7dace`…`d8b1967` (14 commits; see ledger).

## Next session kickoff

Starting s007. Paste-ready prompt:

> Kickoff for mockups-mpc s007. Read, in order:
> 1. `docs/handoffs/2026-09-24-s006-mockup-versions-handoff.md` (this doc).
> 2. `docs/handoffs/2026-09-24-s006-mockup-versions-ledger.md` — every `minor (deferred)` line and rulings R1–R26.
> 3. The ledger's appendix: the final review's findings, incl. the M2/M5/M6/M7 "can ship" items.
> 4. Skim `docs/specs/2026-09-24-mockup-versions-design.md` §3–§8 in the worktree (branch copy is the amended one).
>
> Then state: (a) the work sits on `feat/mockup-versions` in `.worktrees/versions`, reviewed ready-to-merge, 195 tests, unreleased; (b) the next action is to fold the deferred minors in on that branch (plus the Setup Guide versions content), then one scoped review of that diff, then merge + release 1.5.0 + deploy + live fold; (c) the locks: only `db.py` holds SQL; `db.transaction()` is not re-entrant; never run a server or the fold against `./data` except the release step; UI work is verified on a throwaway copy of `app/` in the scratchpad with screenshots the controller looks at; `mcp-publisher login github` is Kyle's to run; back up `mockups.db` before the live fold.
> Ask Kyle to confirm: which minors to include (default: all), the Kyle-owned `~/.claude/CLAUDE.md` Mockups-section update (add `-F parent=<id>`), and the `pyproject.toml` version question. Wait for confirmation before touching code.
