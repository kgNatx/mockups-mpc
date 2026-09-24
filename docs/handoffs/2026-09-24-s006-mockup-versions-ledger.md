# SDD ledger — mockup versions (s006, 2026-09-24)

> Copied verbatim from the git-ignored SDD workspace (`.worktrees/versions/.superpowers/sdd/2026-09-24-mockup-versions/progress.md`) so the rulings and deferred minors survive the worktree. Review-finding texts: `final-review.md` in the same workspace. Plan: `docs/plans/2026-09-24-mockup-versions.md`. Handoff: `docs/handoffs/2026-09-24-s006-mockup-versions-handoff.md`.

Spec: docs/specs/2026-09-24-mockup-versions-design.md (binding)
Worktree: /home/kyleg/containers/mockups-mpc/.worktrees/versions  branch feat/mockup-versions  MERGE_BASE 3de19b1
Baseline: 84 passed.  Python: /home/kyleg/containers/mockups-mpc/.venv/bin/python

## Pre-flight scan
| pair / task | produces vs consumes | finding |
|---|---|---|
| T1→T2 | versioning.* + db read fns → routes/tools; T2 adds `UnknownParent` to versioning.py and `update_version_created_at` to db.py | consistent; T2 extends T1 files (allowed, stated in T2) |
| T1→T3 | comparison_key, base_title, insert_version, insert_alias, refresh_design_mirror | consistent; see R2 (re-parent vs insert) |
| T2→T3 | T3 test hits /view/<old id> (T2 route) | order T1,T2,T3 required — holds |
| T2→T5 | /api/mockups/{id} shape (versions, version), split/delete endpoints | consistent |
| T4↔T5 | both edit gallery.html/style.css | sequential only (never parallel) |
| T1 self | insert_mockup now also writes v1; split_version "moves the version row as the new design's v1" | CONFLICT: split cannot create the new design via insert_mockup (would add a 2nd v1) — R1 |
| T2 self | _update_mockup with content+title: which title changes? | ambiguous — R3 |
| T3 self | apply_fold "insert version on survivor … delete member's own version row first" | workable but indirect — R2 |
| T4 self | readout N from /api/projects | consistent |
| T5 self | alias deep link via /api/mockups/<alias> | depends on T2 alias support — consistent |

## Rulings
- Ruling R1: db.py gets `insert_design_row(...)` (design row only, same columns as insert_mockup); `insert_mockup` = insert_design_row + insert_version(v1) in one transaction; split_version uses insert_design_row + re-parents the version row (UPDATE mockup_id/number=1). — avoids a duplicate v1 — cost if wrong: small refactor inside db.py.
- Ruling R2: fold apply re-parents each member's existing version row with UPDATE (mockup_id=survivor, number=next), inserts the alias, then deletes the member design row (no versions left to cascade). Equivalent to the plan's insert+delete, fewer moving parts. — cost if wrong: none observable (same end state, tests assert end state).
- Ruling R3: update_mockup with content: `title` arg (if given) is the NEW VERSION's title; design title follows the T1 rule (base_title(v1) on 1→2, else unchanged). Metadata-only update (no content) still renames the design. — spec §6.2 says "supplying content adds a version", silent on title — cost if wrong: agents renaming+updating in one call see design title unchanged.
Task 1: dispatched impl-t1 (opus), BASE 3de19b1
- Ruling R4 (impl-t1 Q1): high-water mark `mockups.last_version_number`; next = MAX(hwm, MAX(number))+1 — plan's MAX+1 reused numbers after deleting/splitting the top version and could overwrite a split design's file — cost if wrong: one extra column.
- Ruling R5 (Q2): split design copies tags, favorite=0, title = version title — cost if wrong: user re-tags/re-stars.
- Ruling R6 (Q3): delete version removes its aliases; split with multiple aliases reuses lowest alias_id, re-points others — cost if wrong: old links to a deleted version 404 (intended).
- Ruling R7 (Q4): db.transaction() with asyncio.Lock + BEGIN IMMEDIATE; all writes take the lock — single shared aiosqlite connection does not serialize coroutines — cost if wrong: small overhead per write.
Task 1: impl DONE_WITH_CONCERNS, commit 4e7dace, 111 passed
- Ruling R8 (impl-t1 concern 3): 1→2 title re-derivation applies only when design.title == v1.title (i.e. never renamed) — protects manual renames when a design drops to 1 version and gains another — cost if wrong: an un-renamed design that was deliberately given its v1's full title keeps it. → fix round with review findings.
- Note for T3: db.transaction() lock is not re-entrant; no committing helper inside transaction().
- Note for T2: mcp_server _update/_delete/_set_created_at are stale until T2 (expected).
Task 1 review (rev-t1, opus): spec ❌ / changes requested — I1 alias-id reuse → file overwrite (probe-confirmed); I2 title re-derive overwrites manual rename.
- Ruling R9 (I1): exclusive-create ('xb') at the version write site, bump number on collision — root-cause guard at the only write site — cost if wrong: occasional gap in numbering.
- Ruling R10 (I2, supersedes R8): re-derive title only when last_version_number == 1 before insert — matches spec §3.1 wording — cost if wrong: none known.
Task 1: minor (deferred): M3 commit failure in transaction() leaves orphan file + open txn (wrap commit → rollback, cleanup outside async with)
Task 1: minor (deferred): M4 reads don't take the lock → may see uncommitted rows (document in lock comment)
Task 1: minor (deferred): M5 lock not re-entrant, not stated in code comment (→ tell T3)
Task 1: minor (deferred): M6 next_version_number returns 1 for unknown id (consider ValueError)
Task 1: minor (deferred): M7 delete_design not atomic vs concurrent add_version (orphan file possible)
Task 1: fix round 1/5 dispatched (resume impl-t1), FIX_BASE 4e7dace
Task 1: fix round 1/5 (2 addressed, 0 open; commits 4e7dace..cba44eb)
Task 1: minor (deferred): M8 exclusive-create write: a mid-write failure after open('xb') leaves an empty file (pre-existing shape)
Task 1: complete (commits 3de19b1..cba44eb, review clean)
Task 2: dispatched impl-t2 (sonnet), BASE cba44eb
Task 2: impl DONE, commit eb7b6a2, 153 passed; concerns: 404/409 by message substring; update_mockup tags replace (not union); whole-design delete doesn't resolve aliases. Note for owner: bare trailing numbers fold ('Mock 1'/'Mock 2') — raised at spec review, surface at finish.
Task 2 review (rev-t2, opus): spec ❌ — I1 alias+explicit version targets pinned version (destructive).
- Ruling R11 (I1): fix at root in versioning.resolve — alias + number resolves only when number == alias.number — cost if wrong: none (spec §7 404).
- Ruling R12 (M4): update_mockup and tag_mockup accept alias ids (resolve to target design); whole delete by alias stays 404 — agents hold old ids — cost if wrong: an old link's owner edits the merged design (intended).
- Ruling R13 (M5): update_mockup(content, tags) keeps REPLACE semantics — tool contract "Replace all tags" — cost if wrong: agent loses tags it expected merged.
- Ruling R14 (M6, spec §9): last-version error text names delete_mockup without version. (M7 test global mutation fixed in same round — order-dependent test bomb.)
Task 2: minor (deferred): M2 404/409 decided by "not found" substring (use typed exceptions)
Task 2: minor (deferred): M3 parent race → 400 / TypeError→500 when parent vanishes between resolve and add_version
Task 2: minor (deferred): M8 test gaps: project-mismatch doesn't assert no version added; tag union on auto-fold path untested; svg CSP on /v/{n} untested
Task 2: note for changelog: send_mockup auto-folds "Screen 1"/"Screen 2" by default
Task 2: fix round 1/5 dispatched (resume impl-t2), FIX_BASE eb7b6a2
Task 2: fix round 1/5 (4 addressed, 0 open; commits eb7b6a2..fe7f9bb)
Task 2: minor (deferred): M9 _set_created_at returns _get_mockup with raw (possibly alias) id
Task 2: minor (deferred): M10 alias+mismatched version on get_mockup says "Mockup not found" not "Version not found"
Task 2: complete (commits cba44eb..fe7f9bb, review clean)
- Ruling R15 (T3): app.fold gains optional `--data-dir PATH` (default: config data dir) — needed to dry-run on a copy of live data without touching it — cost if wrong: one extra CLI flag.
Task 3: dispatched impl-t3 (sonnet), BASE fe7f9bb
Task 3: impl DONE, commits e434748, 176592a; 171 passed. Dry-run on live copy: 51 groups, 131 mockups → 51 designs (scratchpad/livecopy/fold-dry-run.txt) — owner approval needed before live --apply.
- Ruling R16: my T3 dispatch hardcoded source number 1 for move_version — WRONG; implementer's lookup of the actual number stands (R2's wording "existing version row" is the ruling) — cost if wrong: none.
Task 3 review (rev-t3, sonnet): spec ✅, Approved, but 2 Important test gaps (mid-group rollback; pre-existing alias on re-folded member) — entering fix round (fold runs on live data).
- Ruling R17: "folded N groups" = succeeded only — accepted — cost if wrong: cosmetic.
- Ruling R18: README API Routes table update assigned to T3 fix round (README scope of §11) — cost if wrong: none.
Task 3: fix round 1/5 dispatched (resume impl-t3), FIX_BASE 176592a
Task 3: fix round 1/5 (3 addressed, 0 open; commits 176592a..264297f)
Task 3: complete (commits fe7f9bb..264297f, review clean)
Task 4: dispatched impl-t4 (sonnet), BASE 264297f
Task 4: impl DONE, commit 601986c, 175 passed, browser 27/28 (favicon 404 pre-existing); controller eyeballed screenshots vs mockups: match.
Task 4 review (rev-t4, sonnet): spec ✅, Approved. Minors → carried into T5 (same popover code):
- Ruling R19: T5 unifies popover closing (opening any popover closes the others; scope pop + meta-bar popovers) and adds the app's cyan :focus-visible ring to .scope-btn/.fav-toggle/.brand-guide-btn — T5 edits the same code; cheap — cost if wrong: none.
Task 4: minor (deferred): favicon.ico 404 (pre-existing)
Task 4: complete (commits 264297f..601986c, review clean)
Task 5: dispatched impl-t5 (sonnet), BASE 601986c
Task 5: impl DONE, commit 8843bb0, 175 passed, browser 41/42 (favicon). Controller eyeball: pill placed at right (spec says after title?); touch badge squeezed to 1 letter with chip.
Task 5 review (rev-t5, sonnet): spec ✅, changes requested — I1 fetchAndDisplay version race.
- Ruling R20: pill-only-when-version_count>=2 approved — avoids a fetch per single-version design; single-version designs have nothing to show — cost if wrong: owner wants v1 tag everywhere (small change).
- Ruling R21 (controller finding): pill must sit right after the title text (spec §8.3 + mockup), not pushed right by title flex:1 — cost if wrong: none.
- Ruling R22: clicking the active row while pinned → latest; unpinned keeps toggle-deselect — spec §8.1 "row click opens the latest" — cost if wrong: one extra click to close.
Task 5: minor (deferred): versionsCache not pruned; open .ver-list collapses on feed append; duplicate focus-ring rule block; redundant closest(".ver-split") guard
Task 5: minor (deferred): touch layout — project badge squeezed to 1 letter when a version chip is present (375px screenshot)
Task 5: fix round 1/5 dispatched (resume impl-t5), FIX_BASE 8843bb0
Task 5: controller screenshot check — fix round 1 item 2 (pill placement) NOT fixed (title still flex:1 inside wrap); resumed impl-t5 with Entry 7 before re-review.
Task 5: fix round 1/5 (3 addressed, 0 open; commits 8843bb0..9d38f2f — pill needed a 2nd commit after controller screenshot check)
Task 5: complete (commits 601986c..9d38f2f, review clean)
Final review: dispatching (opus) over 3de19b1..9d38f2f
Final review (rev-final, opus): NOT READY — I1 feed dates, I2 description revert, I3 pre-fold version links 404, I4 viewer doesn't follow latest, I5 note advice; minors M1 M3 M4 M8 M9 cheap; rest can ship (triage table in final-review.md).
- Ruling R23 (I3): alias gains source_number; resolve accepts pinned or source number — spec §2 "every existing link keeps working" — cost if wrong: one nullable column.
- Ruling R24 (I5): auto-fold note names split_version / split endpoint as the undo (amends spec §6.1 text) — resend-with-fold=false leaves a stray version — cost if wrong: note wording.
- Ruling R25: M1, M3, M9 and docs M4/M8 ride the final fix wave (cheap, correctness/docs); M2 surfaced to owner + changelog; M5 M6 M7 ship as-is.
Final fix wave: dispatched fix-final (opus), FIX_BASE 9d38f2f
- Ruling R26 (M3): base_title strips trailing parentheticals + iteration tokens to a fixpoint (idempotent); spec §5 amended — 'Hero (mobile) (v2)' → 'Hero' (parenthetical variants already folded before) — cost if wrong: parenthetical variant names fold together.
Final fix wave: fix-final DONE, commits ff70e69 31a5a96 d8b1967 (9d38f2f..d8b1967), 195 passed. Concerns: first poll tick is baseline-only; pinned pill stale count; post-fold alias version link 404 after re-split (documented).

---

## Appendix — final whole-branch review findings (verbatim from final-review.md)

# Final whole-branch review (rev-final, opus, 3de19b1..9d38f2f) — findings for the final fix wave
Probe (temp v1.4-shaped DB → migrate → fold --apply → auto-fold upload → metadata edit → split): scratchpad/final-review/probe.py

I1 Feed date headers + row times use created_at while "newest" sorts by latest_at (gallery.html:505-509, :626). A design created Jan 1 with a new version today sits at the top under a "Jan 1" header. Fix: for sort newest/favorites use latest_at for date key, label and row time; "oldest" keeps created_at.
I2 Metadata-only description edit is reverted by the next refresh_design_mirror (mcp_server.py:181 db_update_mockup(description=…); db.py:234 copies description from highest version). Probe: "hand-edited" → "d4" after set_created_at. Fix at root in versioning: a design-level description edit also writes the highest version's description, in one transaction.
I3 Version links minted before fold --apply 404 after it (versioning.py:234 R11; fold.py:115): upload returns version_url /view/C/v/1; fold C into A as v3; resolve("C",1) → None. Spec §2 "every existing link keeps working".
I4 Viewer never follows a new version and the pill says "latest" falsely (gallery.html:1282-1287 poll reloads only the feed; :526-528). Fix: in the poll, if the active design is unpinned and its latest_at or version_count changed, fetchAndDisplay(activeId, null).
I5 Auto-fold note advises "Resend with fold=false", which leaves the misfolded version inside the other design (mcp_server.py:63-67).
M1 split / delete of v1 leaves design created_at stale (refresh_design_mirror never recomputes it; spec §3.1 created_at = first version's time).
M3 base_title not idempotent with two parentheticals (versioning.py:34-47): "Foo (a) (b)" → "Foo (a)" → "Foo".
M4 README claims folding/splitting never deletes an id you were given — wrong for split (old /view/S/v/n 404s) and delete-version (R6 removes aliases).
M8 CHANGELOG omits the UI rebuild, POST …/versions/{n}/split, search over version titles, set_created_at version param, /?mockup=&v=; README lacks --data-dir; README says /view/{id} always serves latest (an alias serves its pinned version).
M9 fold.py:51 runs its own SELECT (only db.py may hold SQL).
Can ship (not in this wave): M2 split disables auto-fold for the series (tell owner); M5 favorite PUT by alias 404; M6 alias+wrong v → silent empty viewer; M7 "v5 of 3" with gaps; all previously deferred task minors.
