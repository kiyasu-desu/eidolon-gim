"""A detachable library preserves story rows and never exports user data."""

import json
from pathlib import Path

import pytest

from eidolon.__main__ import main
from eidolon.corpus import Episode, Line, StoryCorpus
from eidolon.database import connect, readonly
from eidolon.embedding import NoEmbedder
from eidolon.story_library import (
    STORY_TABLES,
    check_library,
    migrate_stories,
    mounted_library,
)
from tests.fakes import FakeEmbedder


@pytest.fixture
async def legacy(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    corpus = StoryCorpus(path, FakeEmbedder())
    await corpus.save(
        [
            Episode(
                "canon",
                "local",
                "source",
                "Synthetic experience",
                frozenset({"temari"}),
                (Line("speaker", "A synthetic line", "合成测试"),),
                "gim-csv",
            ),
            Episode(
                "conditional",
                "local",
                "source",
                "Synthetic condition",
                frozenset({"temari"}),
                (Line("speaker", "Only if it happens"),),
                "gim-conditional-csv",
            ),
        ]
    )
    corpus.close()
    db = connect(path)
    try:
        with db:
            db.execute(
                "CREATE TABLE private_user_data (id TEXT PRIMARY KEY, message TEXT, memory BLOB)"
            )
            db.execute(
                "INSERT INTO private_user_data VALUES ('user', 'keep my chat', ?)",
                (b"personal-memory",),
            )
    finally:
        db.close()
    return path


def contents(path: Path) -> dict:
    db = readonly(path)
    try:
        tables = [
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        return {
            name: db.execute(f'SELECT * FROM "{name}" ORDER BY 1,2').fetchall()
            for name in tables
            if not name.startswith("sqlite_")
        }
    finally:
        db.close()


async def test_migration_preserves_vectors_classification_and_user_database(
    legacy: Path, tmp_path: Path
):
    original = contents(legacy)
    target = tmp_path / "pack/stories.db"

    report = migrate_stories(legacy, target)

    assert contents(legacy) == original
    assert report.backup is not None and contents(Path(report.backup)) == original
    assert contents(target) == {name: original[name] for name in STORY_TABLES}
    check_library(target)
    corpus = StoryCorpus(target, NoEmbedder())
    try:
        assert corpus.imported_from("canon") == "gim-csv"
        assert corpus.imported_from("conditional") == "gim-conditional-csv"
    finally:
        corpus.close()
    again = migrate_stories(legacy, target)
    assert again.reused and again.backup is None
    assert again.tables == report.tables
    assert (
        json.loads(
            target.with_name("stories.db.manifest.json").read_text(encoding="utf-8")
        )["version"]
        == 1
    )


async def test_existing_or_mixed_target_is_never_overwritten(
    legacy: Path, tmp_path: Path
):
    with pytest.raises(ValueError, match="分开"):
        migrate_stories(legacy, legacy)
    with pytest.raises(ValueError, match="应用表"):
        check_library(legacy)
    assert mounted_library(legacy, enabled=False) is None
    missing = tmp_path / "absent/stories.db"
    assert mounted_library(missing) is None and not missing.parent.exists()
    target = tmp_path / "different.db"
    StoryCorpus(target, NoEmbedder()).close()
    before = target.read_bytes()
    with pytest.raises(ValueError, match="内容不同"):
        migrate_stories(legacy, target)
    assert target.read_bytes() == before


def test_cli_migration_retains_source_and_publishes_story_only_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    source, output = tmp_path / "source.db", tmp_path / "pack.db"
    StoryCorpus(source, NoEmbedder()).close()
    assert (
        main(["story", "migrate", "--source", str(source), "--output", str(output)])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["destination"] == str(output.resolve())
    assert set(contents(output)) == STORY_TABLES
    assert source.exists()


def test_story_import_refuses_a_user_database(
    legacy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    source = contents(legacy)
    csv = tmp_path / "csv"
    csv.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    assert (
        main(
            [
                "--db",
                str(legacy),
                "story",
                "import-gim",
                str(csv),
                "--manifest",
                str(manifest),
                "--report",
                str(tmp_path / "report.json"),
                "--offline",
            ]
        )
        == 1
    )
    assert "应用表" in capsys.readouterr().err
    assert contents(legacy) == source
