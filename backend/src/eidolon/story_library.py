"""Mount and extract a local story library without touching user-owned tables.

Only the four episode tables belong to a library. Extraction keeps a complete
SQLite backup of the source, copies original rows/blobs without re-embedding,
and refuses to replace a different existing library.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from eidolon.corpus import StoryCorpus
from eidolon.database import connect, readonly
from eidolon.embedding import NoEmbedder

log = logging.getLogger(__name__)

STORY_COLUMNS = {
    "episodes": ("id", "category", "source", "title", "imported_from", "imported_at"),
    "episode_cast": ("episode_id", "character_id"),
    "episode_lines": ("episode_id", "seq", "speaker", "ja", "zh"),
    "episode_passages": ("episode_id", "seq", "text", "model", "embedding"),
}
STORY_TABLES = frozenset(STORY_COLUMNS)


def _tables(db: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not r[0].startswith("sqlite_")
    }


def check_library(path: Path) -> None:
    """Permit a new library or an existing story-only database, never an application DB."""
    if not path.exists():
        return
    db = readonly(path)
    try:
        tables = _tables(db)
        if tables - STORY_TABLES:
            raise ValueError(
                f"剧情库不能包含账户、聊天或其他应用表：{path}；请使用 story migrate 导出"
            )
        if tables and not STORY_TABLES <= tables:
            raise ValueError(f"剧情库表不完整：{path}")
        for table, columns in STORY_COLUMNS.items():
            if table not in tables:
                continue
            actual = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            allowed = set(columns)
            if actual - allowed or allowed - actual - {"imported_from"}:
                raise ValueError(f"剧情库列不兼容：{table}；请重新导出资源包")
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError(f"剧情库完整性检查失败：{path}")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError(f"剧情库关联不完整：{path}")
    finally:
        db.close()


def mounted_library(path: Path, *, enabled: bool = True) -> Path | None:
    """An absent/disabled pack stays absent; mounting does not create an empty DB."""
    if not enabled:
        return None
    if not path.is_file():
        log.info(
            "Story library is not mounted at %s; import stories or use story migrate for legacy data",
            path,
        )
        return None
    check_library(path)
    return path


def _rows(db: sqlite3.Connection, table: str):
    columns = list(STORY_COLUMNS[table])
    actual = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    # Old CSV corpora predate imported_from; preserve their original CSV meaning.
    selected = [
        "'csv'" if c == "imported_from" and c not in actual else c for c in columns
    ]
    if set(columns) - actual - {"imported_from"}:
        raise ValueError(f"剧情表结构不兼容：{table}")
    return db.execute(
        f"SELECT {','.join(selected)} FROM {table} ORDER BY {','.join(columns[:2])}"
    )


def _inventory(db: sqlite3.Connection) -> dict:
    result = {}
    for table in STORY_COLUMNS:
        digest = hashlib.sha256()
        count = 0
        for row in _rows(db, table):
            encoded = [
                dict(blob=value.hex()) if isinstance(value, bytes) else value
                for value in row
            ]
            digest.update(
                (
                    json.dumps(encoded, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                ).encode()
            )
            count += 1
        result[table] = dict(rows=count, sha256=digest.hexdigest())
    return result


@dataclass(frozen=True)
class StoryMigration:
    source: str
    destination: str
    backup: str | None
    reused: bool
    tables: dict


def migrate_stories(source: Path, destination: Path) -> StoryMigration:
    """Export only story data; retain the source and a full backup of its snapshot."""
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError("剧情库必须与源应用数据库分开")
    if not source.is_file():
        raise ValueError(f"源数据库不存在：{source}")
    check_library(destination)
    db = readonly(source)
    temporary = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
    try:
        db.execute("BEGIN")
        if not STORY_TABLES <= _tables(db):
            raise ValueError("源数据库没有完整剧情表，无法迁移")
        expected = _inventory(db)
        if destination.exists():
            existing = readonly(destination)
            try:
                if _inventory(existing) != expected:
                    raise ValueError(
                        "目标剧情库已存在且内容不同；不会覆盖，请选择新路径"
                    )
            finally:
                existing.close()
            return StoryMigration(str(source), str(destination), None, True, expected)
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = source.with_name(
            source.name
            + ".before-story-split-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid4().hex[:8]
            + ".db"
        )
        backup_db = connect(backup)
        try:
            db.backup(backup_db)
        finally:
            backup_db.close()
        corpus = StoryCorpus(temporary, NoEmbedder())
        corpus.close()
        target = connect(temporary)
        try:
            with target:
                for table, columns in STORY_COLUMNS.items():
                    target.executemany(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        _rows(db, table),
                    )
            if _inventory(target) != expected:
                raise ValueError("剧情迁移校验失败，保留源库和备份")
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            target.close()
        check_library(temporary)
        # Refuse a target created by another process while extraction was running.
        if destination.exists():
            raise ValueError("迁移期间目标已出现；不会覆盖")
        os.link(temporary, destination)
        temporary.unlink()
        result = StoryMigration(
            str(source), str(destination), str(backup), False, expected
        )
        destination.with_name(destination.name + ".manifest.json").write_text(
            json.dumps({"version": 1, **asdict(result)}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        db.close()
        for path in [
            temporary,
            Path(str(temporary) + "-wal"),
            Path(str(temporary) + "-shm"),
        ]:
            path.unlink(missing_ok=True)
