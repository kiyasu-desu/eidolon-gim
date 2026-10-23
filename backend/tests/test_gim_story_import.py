"""Original fixtures only: exercise the GIM adapter through the real SQLite corpus."""

import csv
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.__main__ import main
from eidolon.characters import load_characters
from eidolon.config import Settings, characters_path_from_env, database_path_from_env
from eidolon.corpus import Episode, Line, StoryCorpus
from eidolon.embedding import NoEmbedder
from eidolon.gim_story_import import import_gim_directory
from eidolon.world import load_world, world_path
from tests.fakes import FakeEmbedder

CHARACTERS = Path(__file__).resolve().parents[2] / "characters/gim/characters.toml"
SOURCE = "adv_original_fixture_01.txt"
ID = f"gim/{SOURCE}"


def story(root: Path, *, source: str = SOURCE, filename: str = "one.csv") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows([
            ["id", "name", "text", "trans"],
            ["0", "__title__", "原创适配夹具", ""],
            ["0", "手毬", r"<em>公園</em>で\n<r\=うた>歌</r>を練習する。", "在公园\n练歌。"],
            ["0", "月村　手毬", "明日も続ける。", ""],
            ["0", "{user}", "わかった。", "明白了。"],
            ["0", "__narration__", "風が吹いた。", ""],
            ["select", "", "休憩する？", "休息吗？"],
            ["select", "", "続ける？", "继续吗？"],
            ["0", "友人", "水を置いておく。", "放一瓶水。"],
            ["译者", "原创测试", "", ""],
            ["info", source, "", ""],
        ])
    return path


def manifest(path: Path, outcome: str = "canon") -> Path:
    path.write_text(json.dumps({
        "source_url": "https://example.invalid/original-fixtures",
        "version": "original-v1",
        "usage_conditions": "Original test text; no game story included.",
        "episodes": {SOURCE: outcome},
    }), encoding="utf-8")
    return path


async def run(root: Path, corpus: StoryCorpus, meta: Path, index: Path | None = None):
    return await import_gim_directory(root, corpus, load_characters(CHARACTERS).values(),
                                      manifest=meta, index=index)


async def test_original_fixture_catalog_audit_idempotency_and_reembed(tmp_path: Path):
    root = tmp_path / "csv"
    path = story(root)
    meta = manifest(tmp_path / "manifest.json")
    database = tmp_path / "corpus.db"
    corpus = StoryCorpus(database, NoEmbedder())
    try:
        first = await run(root, corpus, meta)
        assert not first.has_errors
        assert (first.imported, first.embedded_passages, first.pending_passages) == (1, 0, 1)
        episode = corpus.get(ID)
        assert episode is not None
        assert episode.cast == {"temari"}
        assert episode.lines[:3] == (
            Line("手毬", "公園で\n歌を練習する。", "在公园\n练歌。"),
            Line("月村　手毬", "明日も続ける。"),
            Line("制作人", "わかった。", "明白了。"),
        )
        assert episode.lines[3].speaker is None
        assert len(episode.lines) == 5
        assert corpus.catalog("temari")[0].episodes[0].episode_id == ID
        assert corpus.catalog("mano") == []
        entry = first.files[0]
        assert entry.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry.line_rows == [3, 5, 6, 7, 10]  # quoted multiline translation takes 2 physical rows
        assert entry.valid_lines == 5
        assert [[choice.row for choice in group] for group in entry.choices] == [[8, 9]]
        assert all(c.target == "unknown" for group in entry.choices for c in group)
        assert entry.speakers["制作人"] == 1
        assert (await run(root, corpus, meta)).unchanged == 1
        assert len(corpus.list_episodes()) == 1
        assert await corpus.search("公園", "temari") == []
        assert corpus.search_by_vector([1.0], "temari") == []
    finally:
        corpus.close()
    embedder = FakeEmbedder()
    corpus = StoryCorpus(database, embedder)
    try:
        assert corpus.count_missing_vectors() == 1
        assert await corpus.search("公園", "temari") == []
        assert await corpus.embed_missing() == 1
        assert corpus.count_missing_vectors() == 0
        assert (await corpus.search("公園", "temari"))[0].episode.id == ID
        assert await corpus.search("公園", "mano") == []
        assert "休憩する？" not in embedder.documents[0]
        assert "__title__" not in embedder.documents[0]
        assert (await run(root, corpus, meta)).unchanged == 1
    finally:
        corpus.close()


async def test_offline_update_keeps_vectors_for_unchanged_passages(tmp_path: Path):
    database = tmp_path / "corpus.db"
    embedder = FakeEmbedder()
    original = Episode(ID, "学园剧情", SOURCE, "原创夹具", frozenset({"temari"}),
                       (Line("手毬", "あ" * 800), Line("手毬", "い" * 800)), "gim-csv")
    online = StoryCorpus(database, embedder)
    try:
        assert await online.save([original]) == 2
    finally:
        online.close()
    updated = replace(original, lines=(original.lines[0], Line("手毬", "う" * 800)))
    offline = StoryCorpus(database, NoEmbedder())
    try:
        assert await offline.save([updated]) == 0
        assert await offline.search("あ", "temari") == []
    finally:
        offline.close()
    online = StoryCorpus(database, embedder)
    try:
        assert online.count_missing_vectors() == 1
        assert len(await online.search("あ", "temari")) == 1
        assert await online.embed_missing() == 1
        assert online.count_missing_vectors() == 0
        assert online.get(ID) == updated
    finally:
        online.close()


async def test_updates_and_failure_or_unknown_reclassification(tmp_path: Path):
    root = tmp_path / "csv"
    path = story(root)
    meta = manifest(tmp_path / "manifest.json")
    corpus = StoryCorpus(tmp_path / "corpus.db", FakeEmbedder())
    try:
        assert (await run(root, corpus, meta)).embedded_passages == 1
        path.write_text(path.read_text(encoding="utf-8-sig").replace("明日も", "明後日も"), encoding="utf-8")
        assert (await run(root, corpus, meta)).imported == 1
        episode = corpus.get(ID)
        assert episode is not None and episode.lines[1].ja == "明後日も続ける。"
        manifest(meta, "failure")
        failure = await run(root, corpus, meta)
        assert (failure.skipped_failures, failure.removed) == (1, 1)
        assert corpus.get(ID) is None
        manifest(meta, "canon")
        await run(root, corpus, meta)
        manifest(meta, "unknown")
        unknown = await run(root, corpus, meta)
        assert (unknown.unknown_outcomes, unknown.removed) == (1, 1)
        assert corpus.get(ID) is None
        meta.write_text(meta.read_text().replace(f'"{SOURCE}": "unknown"', ""))
        assert (await run(root, corpus, meta)).unknown_outcomes == 1
    finally:
        corpus.close()


async def test_conditional_import_requires_qualified_messages_and_bound_evidence(tmp_path: Path):
    root = tmp_path / "csv"
    root.mkdir()
    path = root / "conditional.csv"
    label = "【条件情境・未确认实际触发：原创挑战成功情境】"
    rows = [
        ["id", "name", "text", "trans"], ["info", SOURCE, "", ""],
        ["1", "手毬", label + "新しい練習方法を試せた。", ""],
        ["2", "__narration__", label + "風が吹いた。", ""],
    ]

    def write_rows(value: list[list[str]]) -> str:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows(value)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    digest = write_rows(rows)
    meta = manifest(tmp_path / "manifest.json", "conditional")
    original = json.loads(meta.read_text(encoding="utf-8"))
    original["branch_restoration"] = {"entries": {SOURCE: {
        "raw_sha256": "a" * 64, "graph_sha256": "b" * 64, "csv_sha256": digest,
    }}}
    meta.write_text(json.dumps(original), encoding="utf-8")
    corpus = StoryCorpus(tmp_path / "conditional.db", FakeEmbedder())
    try:
        report = await run(root, corpus, meta)
        assert not report.has_errors
        assert (report.imported, report.unknown_outcomes, report.skipped_failures) == (1, 0, 0)
        before = corpus.get(ID)
        assert before is not None and before.cast == {"temari"}
        assert before.imported_from == "gim-conditional-csv"
        assert corpus.imported_from(ID) == "gim-conditional-csv"
        assert all(line.ja.startswith(label) for line in before.lines)
        assert (await run(root, corpus, meta)).unchanged == 1
        recalled = await corpus.search("練習方法", "temari")
        assert recalled and label in recalled[0].text
        assert recalled[0].episode.imported_from == "gim-conditional-csv"
        for damage, complaint in (
            ("label", "per-message"), ("producer", "exclude producer"),
            ("evidence", "source evidence"), ("digest_format", "64-hex"),
            ("digest_mismatch", "does not match"),
        ):
            changed_rows, changed_meta = deepcopy(rows), deepcopy(original)
            if damage == "label":
                changed_rows[3][2] = "A common tail cannot lose its scenario qualification"
            elif damage == "producer":
                changed_rows[2][1] = "{user}"  # _clean turns this into 制作人 before validation.
            elif damage == "evidence":
                del changed_meta["branch_restoration"]
            elif damage == "digest_format":
                changed_meta["branch_restoration"]["entries"][SOURCE]["raw_sha256"] = "not a digest"
            else:
                changed_meta["branch_restoration"]["entries"][SOURCE]["csv_sha256"] = "0" * 64
            changed_digest = write_rows(changed_rows)
            if damage in ("label", "producer"):
                changed_meta["branch_restoration"]["entries"][SOURCE]["csv_sha256"] = changed_digest
            meta.write_text(json.dumps(changed_meta), encoding="utf-8")
            invalid = await run(root, corpus, meta)
            assert invalid.has_errors, damage
            assert complaint in str(invalid.files[0].errors), damage
            assert invalid.imported == 0 and invalid.removed == 0, damage
            assert corpus.get(ID) == before, damage
    finally:
        corpus.close()


@pytest.mark.parametrize("damage, complaint", [
    ("empty", "header"), ("columns", "columns"), ("quotes", "unexpected end"),
    ("contradiction", "contradictory info"), ("bad-info", "invalid source"),
    ("missing-info", "missing info"), ("control", "unknown control"),
    ("duplicate", "duplicate source"),
])
async def test_invalid_files_preserve_previously_saved_episode(tmp_path: Path, damage: str, complaint: str):
    root = tmp_path / "csv"
    path = story(root)
    meta = manifest(tmp_path / "manifest.json")
    corpus = StoryCorpus(tmp_path / "corpus.db", NoEmbedder())
    try:
        await run(root, corpus, meta)
        before = corpus.get(ID)
        if damage == "empty":
            path.write_text("")
        elif damage == "columns":
            path.write_text("id,name,text,trans\n0,手毬,x,,extra\n", encoding="utf-8")
        elif damage == "quotes":
            path.write_text('id,name,text,trans\n0,手毬,"unclosed', encoding="utf-8")
        elif damage == "contradiction":
            with path.open("a", encoding="utf-8") as stream:
                stream.write("info,adv_other.txt,,\n")
        elif damage == "duplicate":
            story(root, filename="copy.csv")
        else:
            text = path.read_text(encoding="utf-8-sig")
            if damage == "bad-info":
                text = text.replace(SOURCE, "../adv_bad.txt")
            elif damage == "missing-info":
                text = text.replace(f"info,{SOURCE},,", "译者,original,,")
            else:
                text = text.replace("明日も", "<unknown>明日も")
            path.write_text(text, encoding="utf-8")
        report = await run(root, corpus, meta)
        assert report.has_errors
        assert complaint in str([entry.errors for entry in report.files])
        assert corpus.get(ID) == before
        if damage == "control":
            assert report.files[0].unknown_controls
    finally:
        corpus.close()


@pytest.mark.parametrize("mapping, complaint", [
    ({SOURCE: "../escape.csv"}, "escapes"),
    ({SOURCE: "missing.csv"}, "missing CSV"),
    ({"adv_other.txt": "one.csv"}, "info/index conflict"),
    ({SOURCE: "one.csv", "adv_other.txt": "one.csv"}, "multiple source"),
])
async def test_index_validation(tmp_path: Path, mapping: dict[str, str], complaint: str):
    root = tmp_path / "csv"
    story(root)
    meta = manifest(tmp_path / "manifest.json")
    index = tmp_path / "index.json"
    index.write_text(json.dumps(mapping), encoding="utf-8")
    corpus = StoryCorpus(tmp_path / "corpus.db", NoEmbedder())
    try:
        report = await run(root, corpus, meta, index)
        assert complaint in str(report.errors + [error for entry in report.files for error in entry.errors])
        assert corpus.list_episodes() == []
    finally:
        corpus.close()


async def test_index_fallback_and_symlink_escape(tmp_path: Path):
    root = tmp_path / "csv"
    path = story(root)
    path.write_text(path.read_text(encoding="utf-8-sig").replace(f"info,{SOURCE},,", "译者,original,,"), encoding="utf-8")
    meta = manifest(tmp_path / "manifest.json")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({SOURCE: "one.csv"}), encoding="utf-8")
    corpus = StoryCorpus(tmp_path / "corpus.db", NoEmbedder())
    try:
        assert (await run(root, corpus, meta, index)).imported == 1
        outside = story(tmp_path / "outside")
        try:
            (root / "escape.csv").symlink_to(outside)
        except OSError:
            pytest.skip("Windows symlink creation requires Developer Mode or administrator")
        report = await run(root, corpus, meta)
        assert "escapes" in str([e.errors for e in report.files])
    finally:
        corpus.close()


def test_cli_writes_auditable_report_and_repeats_without_embedding(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = tmp_path / "csv"
    story(root)
    meta = manifest(tmp_path / "manifest.json")
    report = tmp_path / "report.json"
    args = ["--db", str(tmp_path / "cli.db"), "story", "import-gim", str(root),
            "--characters", str(CHARACTERS), "--manifest", str(meta), "--report", str(report), "--offline"]
    assert main(args) == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["imported"] == 1 and result["files"][0]["cast"] == ["temari"]
    assert result["source_url"] == "https://example.invalid/original-fixtures"
    assert result["manifest_sha256"] == hashlib.sha256(meta.read_bytes()).hexdigest()
    assert main(args) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["unchanged"] == 1
    assert "GIM" in capsys.readouterr().out


def test_cli_with_embedding_and_reported_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class Closable(FakeEmbedder):
        async def aclose(self) -> None:
            pass

    embedder = Closable()
    monkeypatch.setenv("SILICONFLOW_API_KEY", "fake-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "siliconflow")
    monkeypatch.setattr("eidolon.embedding.open_embedder", lambda _: embedder)
    root = tmp_path / "csv"
    path = story(root)
    meta = manifest(tmp_path / "manifest.json")
    report = tmp_path / "report.json"
    args = ["--db", str(tmp_path / "cli.db"), "story", "import-gim", str(root),
            "--characters", str(CHARACTERS), "--manifest", str(meta), "--report", str(report)]
    assert main(args) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["embedded_passages"] == 1
    assert len(embedder.documents) == 1
    path.write_text(path.read_text(encoding="utf-8-sig").replace("明日も", "明後日も"), encoding="utf-8")
    embedder.documents_down = True
    assert main(args) == 1
    assert "save failed" in report.read_text(encoding="utf-8")
    corpus = StoryCorpus(tmp_path / "cli.db", NoEmbedder())
    try:
        episode = corpus.get(ID)
        assert episode is not None and episode.lines[1].ja == "明日も続ける。"
        assert corpus.count_missing_vectors() == 0
    finally:
        corpus.close()


async def test_manifest_rejects_bad_outcome_and_duplicate_keys(tmp_path: Path):
    root = tmp_path / "csv"
    story(root)
    meta = manifest(tmp_path / "manifest.json", "not-reviewed")
    corpus = StoryCorpus(tmp_path / "corpus.db", NoEmbedder())
    try:
        assert "invalid outcome" in str((await run(root, corpus, meta)).errors)
        manifest(meta)
        meta.write_text(meta.read_text().replace('"version": "original-v1"', '"version":"a", "version":"b"'))
        assert "duplicate JSON key" in str((await run(root, corpus, meta)).errors)
        assert corpus.list_episodes() == []
    finally:
        corpus.close()


def test_gim_defaults_and_legacy_sync_guards(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    for name in ("EIDOLON_CHARACTERS_PATH", "EIDOLON_DATABASE_PATH", "EIDOLON_AFFINITY_AND_GIFTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHAT_LLM_API_KEY", "test")
    monkeypatch.setenv("CHAT_LLM_MODEL", "test")
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://llm.invalid/v1")
    settings = Settings.from_env()
    assert characters_path_from_env() == Path("../characters/gim/characters.toml")
    assert database_path_from_env() == Path("data/eidolon-gim.db")
    assert not settings.affinity_and_gifts
    assert list(load_characters(settings.characters_path)) == ["temari"]
    assert load_world(world_path(settings.characters_path)) is None
    assert main(["story", "sync"]) == 1
    assert main(["world", "sync"]) == 1
    assert "legacy SC" in capsys.readouterr().err
