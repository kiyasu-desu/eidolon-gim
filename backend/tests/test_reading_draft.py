"""Drafting the readings file (`eidolon reading draft`, GLOSSARY.md「读音」): each
character's full name, surname and given name, read as her sheet's first line has them,
the units and the office's staff as the world setting reads them; phonemes made with
pyopenjtalk. Run again, it fills in the phonemes left empty and adds the characters and
units the file lacks, and leaves every entry that has phonemes as it is."""

import json
from datetime import date
from pathlib import Path

import pytest

from eidolon.reading_draft import to_phonemes
from eidolon.readings import Reading, load_readings
from eidolon.world import Staff, Unit, World, world_path
from tests.conftest import Admin, CharacterConfig

WORLD = World(
    as_of=date(2026, 10, 1),
    office="サンプル事務所ダクション",
    staff=(Staff("架空代表", "かくうだいひょう", "社長", ()),),
    units=(Unit("Sample Stars", "さんぷるすたーず", ("星野空", "晴川ひな"), ()),),
    idols=(),
)


def sheet(name: str, reading: str) -> str:
    return f"# 人设：{name}\n\n## 身份\n你是 示例事务所的偶像{name}（{reading}），16 岁。"


@pytest.fixture
def config(tmp_path: Path) -> CharacterConfig:
    """Sora, Hina (her given name in kana) and Towa (hers a word of its own), and the
    world setting."""
    config = CharacterConfig(tmp_path / "characters")
    config.add("sora", "星野空", sheet("星野空", "ほしの そら"), speakers=["空"])
    config.add("hina", "晴川ひな", sheet("晴川ひな", "はるかわ ひな"), speakers=["ひな"])
    config.add("towa", "架空透", sheet("架空透", "かくう とおる"), speakers=["透"])
    config.write("world.json", json.dumps(WORLD.to_json(), ensure_ascii=False))
    return config


def draft(admin: Admin, config: CharacterConfig) -> tuple[Reading, ...]:
    admin.run("reading", "draft", "--characters", str(config.path))
    return load_readings(config.directory / "readings.toml")


def test_a_first_draft_reads_the_characters_units_and_staff(admin: Admin, config: CharacterConfig):
    readings = draft(admin, config)

    assert [(r.written, r.kana) for r in readings] == [
        ("星野空", "ほしの そら"), ("星野", "ほしの"), ("空", "そら"),
        ("晴川ひな", "はるかわ ひな"), ("晴川", "はるかわ"),
        ("架空透", "かくう とおる"), ("架空", "かくう"),  # not 透 alone: 透明, 透き通る
        ("Sample Stars", "さんぷるすたーず"),
        ("架空代表", "かくうだいひょう"),
    ]
    phonemes = {r.written: r.phonemes for r in readings}
    assert all(phonemes.values())
    # Surname and given name made apart and put together.
    assert phonemes["星野空"] == to_phonemes("ほしの") + to_phonemes("そら")


def test_run_again_it_fills_in_empty_phonemes_adds_who_is_missing_and_leaves_the_rest(
    admin: Admin, config: CharacterConfig
):
    path = config.directory / "readings.toml"
    path.write_text(
        '[[readings]]\nwritten = "星野空"\nkana = "ほしの そら"\nphonemes = "ho0shi1no1so1ra0"\n\n'
        '[[readings]]\nwritten = "架空代表"\nkana = "かくう だいひょう"\nphonemes = ""\n\n'
        '[[readings]]\nwritten = "101"\nkana = "つばさ"\nphonemes = "tsu0ba1sa0"\n',
        encoding="utf-8",
    )

    readings = draft(admin, config)

    assert readings[0] == Reading("星野空", "ほしの そら", "ho0shi1no1so1ra0")  # tuned by hand
    assert readings[1] == Reading("架空代表", "かくう だいひょう", to_phonemes("かくう") + to_phonemes("だいひょう"))
    assert readings[2] == Reading("101", "つばさ", "tsu0ba1sa0")
    # Sora is in the file already, by her full name: her surname and given name, left out
    # by whoever kept it, stay out.
    assert [r.written for r in readings[3:]] == [
        "晴川ひな", "晴川", "架空透", "架空", "Sample Stars"
    ]

    written = path.read_text(encoding="utf-8")
    admin.run("reading", "draft", "--characters", str(config.path))

    assert path.read_text(encoding="utf-8") == written  # word for word


def test_a_character_whose_sheet_does_not_say_how_her_name_is_read_is_reported(
    admin: Admin, config: CharacterConfig
):
    config.add("riku", "青葉リク", "# 人设\n你是青葉リク。", speakers=["リク"])

    out = admin.run("reading", "draft", "--characters", str(config.path))

    assert "青葉リク" in out
    assert "青葉リク" not in {r.written for r in load_readings(config.directory / "readings.toml")}


def test_without_the_world_setting_only_the_characters_are_drafted(admin: Admin, config: CharacterConfig):
    world_path(config.path).unlink()

    readings = draft(admin, config)

    assert "Sample Stars" not in {r.written for r in readings}
    assert readings[0].written == "星野空"


# Phonemes as Fish Audio's documentation makes them (Fine-grained Control → Japanese).


def test_kana_is_read_as_one_word_not_as_a_sentence():
    """In hiragana OpenJTalk takes は for the particle, read わ."""
    assert to_phonemes("はるかわ").startswith("ha")
    assert "wa" not in to_phonemes("なつは")

