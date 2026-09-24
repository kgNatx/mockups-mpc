"""Opt-in fold command: merge near-duplicate single-version designs into version history.

This never runs on its own — the owner runs it by hand, typically once, right
after upgrading to 1.5.0. It looks for designs that share a project and a base
title (app.versioning.base_title) and were never explicitly versioned, and
turns each such group into one design with a version per member. Old ids
become aliases so existing links keep working.

    python -m app.fold --dry-run     # print proposed groups, change nothing
    python -m app.fold --apply       # perform them
    python -m app.fold --apply --data-dir /path/to/scratch/copy
"""
import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

from app import config
from app import db as queries
from app.db import init_db
from app.versioning import base_title, comparison_key


@dataclass
class FoldMember:
    id: str
    title: str
    created_at: str


@dataclass
class FoldGroup:
    project_slug: str
    base_title: str
    members: list[FoldMember] = field(default_factory=list)


async def plan_folds(db: aiosqlite.Connection) -> list[FoldGroup]:
    """Group un-versioned designs that share a project and a base title.

    Only designs with version_count == 1 are candidates: a design that
    already carries several versions was grouped deliberately (by hand, by
    upload-time auto-fold, or by an earlier run of this command) and is left
    alone. Members within a group are sorted oldest first; the group's
    displayed base title is the oldest member's base_title (not necessarily
    its full original title).
    """
    cursor = await db.execute(
        "SELECT id, project_slug, title, created_at FROM mockups "
        "WHERE version_count = 1 ORDER BY created_at ASC")
    rows = [dict(row) for row in await cursor.fetchall()]

    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (row["project_slug"], comparison_key(row["title"]))
        buckets.setdefault(key, []).append(row)

    groups = []
    for (project_slug, _key), members in buckets.items():
        if len(members) < 2:
            continue
        groups.append(FoldGroup(
            project_slug=project_slug,
            base_title=base_title(members[0]["title"]),
            members=[FoldMember(id=m["id"], title=m["title"], created_at=m["created_at"])
                     for m in members],
        ))
    return groups


async def apply_fold(db: aiosqlite.Connection, group: FoldGroup) -> None:
    """Merge a fold group into one design, in a single transaction.

    The oldest member (group.members[0]) survives. Every other member's
    existing version row is re-parented onto the survivor as the next version
    number, in time order, via db.move_version — this also re-points any
    alias already pinned to that row, so old links keep resolving. The
    member's id then becomes a new alias to that version, and its now-empty
    design row is deleted. Files are never moved or copied: move_version only
    changes which design a mockup_versions row belongs to, not file_path.

    A member's surviving version is looked up rather than assumed to be
    number 1: version_count == 1 only means "one version left", which can be
    a higher number if an earlier one was deleted (see
    test_split_restored_alias_never_overwrites_files in test_versioning.py
    for the scenario this guards against).
    """
    survivor = group.members[0]
    async with queries.transaction(db):
        designs = {}
        for member in group.members:
            design = await queries.get_mockup(db, member.id)
            if design is None:
                raise ValueError(f"Mockup not found: {member.id}")
            designs[member.id] = design

        tags: set[str] = set()
        favorite = False
        for design in designs.values():
            tags.update(design["tags"])
            favorite = favorite or bool(design["favorite"])

        for member in group.members[1:]:
            versions = await queries.get_versions(db, member.id)
            if len(versions) != 1:
                raise ValueError(
                    f"Expected exactly one version on {member.id}, found {len(versions)}")
            source_number = versions[0]["number"]
            number = await queries.next_version_number(db, survivor.id)
            await queries.move_version(
                db, member.id, source_number, to_mockup_id=survivor.id, to_number=number)
            await queries.insert_alias(db, alias_id=member.id, mockup_id=survivor.id, number=number)
            await queries.delete_design_row(db, member.id)

        await queries.update_design_fields(
            db, survivor.id, title=group.base_title, tags=sorted(tags), favorite=favorite)
        await queries.refresh_design_mirror(db, survivor.id)


def _print_group(group: FoldGroup) -> None:
    print(f'{group.project_slug} · "{group.base_title}" · {len(group.members)} mockups')
    for member in group.members:
        print(f"  {member.created_at[:16]}  {member.title}  ({member.id})")


async def _run(*, apply: bool) -> int:
    db = await init_db()
    try:
        groups = await plan_folds(db)
        if not apply:
            for group in groups:
                _print_group(group)
            total_rows = sum(len(g.members) for g in groups)
            print(f"{len(groups)} groups, {total_rows} mockups would become {len(groups)} designs")
            return 0

        failed = 0
        for group in groups:
            _print_group(group)
            try:
                await apply_fold(db, group)
            except Exception as e:
                print(f"FAILED {group.base_title}: {e}")
                failed += 1
        print(f"folded {len(groups) - failed} groups")
        return 1 if failed else 0
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.fold",
        description="Merge near-duplicate single-version designs into version history.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print proposed groups, change nothing")
    mode.add_argument("--apply", action="store_true", help="Perform the folds")
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Data directory to use instead of the configured one (e.g. a scratch copy)")
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        # Must happen before init_db() runs, inside _run(), so the migration
        # and every query below target the requested directory.
        config.DATA_DIR = args.data_dir
        config.DB_PATH = args.data_dir / "mockups.db"

    return asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
