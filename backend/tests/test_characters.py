"""Characters come from configuration: the list, the avatars, the image colours, call
backgrounds, stands and greetings, and each one's character sheet."""

import logging
import re
from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.characters import CharacterConfigError, Fact, load_characters, parse_facts
from eidolon.config import Settings
from tests.conftest import (
    AVATAR, BACKGROUND, KOGANE_SHEET, MANO_SHEET, ALTERNATE_AVATAR, CharacterConfig, ClientFactory,
)
from tests.fakes import FakeLLM
from tests.test_text_turn import send_turn, start_conversation

REPO_CHARACTERS = Path(__file__).parents[2] / "characters"


async def test_character_list_shows_name_intro_avatar_colour_and_background_but_not_the_sheet(
    make_client: ClientFactory,
):
    """It is shown before signing in."""
    client = make_client(FakeLLM(), user=None)

    res = await client.get("/api/characters")

    assert res.status_code == 200
    assert res.json() == [
        {
            "id": "sora",
            "name": "星野ソラ",
            "intro": "Sample Stars 的中心",
            "avatar_url": "/api/characters/sora/avatar",
            "alternate_avatar_url": "/api/characters/sora/alternate-avatar",
            "color": "#ffbad6",
            "background_url": "/api/characters/sora/background",
            "stand": None,  # no stand assets URL is configured
            "display_order": 1,
            "name_zh": None,  # none configured
            "name_kana": None,
            "name_romaji": None,
            "unit": None,
            "unit_reading": None,  # no world setting
            "unit_order": None,
            "greeting": None,  # none configured
            "call_opener": None,
        },
        {
            "id": "riku",
            "name": "青葉リク",
            "intro": "Sample Harmony 的偶像",
            "avatar_url": None,
            "alternate_avatar_url": None,
            "color": "#f84cad",
            "background_url": None,
            "stand": None,
            "display_order": None,
            "name_zh": None,  # none configured
            "name_kana": None,
            "name_romaji": None,
            "unit": None,
            "unit_reading": None,
            "unit_order": None,
            "greeting": None,
            "call_opener": None,
        },
    ]
    assert "えっと" not in res.text


async def test_character_list_is_in_idol_number_order_and_those_without_one_follow_as_configured(
    make_client: ClientFactory, characters: CharacterConfig
):
    """Sora is idol 1 and Riku has no idol number (the fixture)."""
    characters.add("hina", "晴川ヒナ", "sheet", display_order=3)
    characters.add("someone", "誰か", "sheet")
    characters.add("nagi", "雨宮ナギ", "sheet", display_order=2)
    client = make_client(FakeLLM(), user=None)

    listed = (await client.get("/api/characters")).json()

    assert [(c["id"], c["display_order"]) for c in listed] == [
        ("sora", 1), ("nagi", 2), ("hina", 3), ("riku", None), ("someone", None),
    ]


async def test_character_list_gives_the_other_names_she_is_searched_by(
    make_client: ClientFactory, characters: CharacterConfig
):
    characters.add("hina", "晴川ヒナ", "sheet", other_names=("晴川日奈", "はちみや ヒナ", "Hachimiya Hina"))
    client = make_client(FakeLLM(), user=None)

    listed = {c["id"]: c for c in (await client.get("/api/characters")).json()}

    assert [listed["hina"][f] for f in ("name_zh", "name_kana", "name_romaji")] == [
        "晴川日奈", "はちみや ヒナ", "Hachimiya Hina",
    ]


async def test_avatar_is_served_without_a_session_so_img_tags_can_load_it(
    make_client: ClientFactory,
):
    client = make_client(FakeLLM(), user=None)

    res = await client.get("/api/characters/sora/avatar")

    assert res.status_code == 200
    assert res.content == AVATAR
    assert (await client.get("/api/characters/riku/avatar")).status_code == 404
    assert (await client.get("/api/characters/nobody/avatar")).status_code == 404


async def test_alternate_avatar_is_served_without_a_session_like_the_avatar(
    make_client: ClientFactory,
):
    client = make_client(FakeLLM(), user=None)

    res = await client.get("/api/characters/sora/alternate-avatar")

    assert res.status_code == 200
    assert res.content == ALTERNATE_AVATAR
    assert (await client.get("/api/characters/riku/alternate-avatar")).status_code == 404
    assert (await client.get("/api/characters/nobody/alternate-avatar")).status_code == 404


async def test_call_background_is_served_without_a_session_like_the_avatar(
    make_client: ClientFactory,
):
    client = make_client(FakeLLM(), user=None)

    res = await client.get("/api/characters/sora/background")

    assert res.status_code == 200
    assert res.content == BACKGROUND
    assert (await client.get("/api/characters/riku/background")).status_code == 404
    assert (await client.get("/api/characters/nobody/background")).status_code == 404


@pytest.mark.parametrize("picture", ["avatar", "alternate-avatar", "background"])
async def test_avatar_and_background_are_cached_by_the_browser_and_revalidated_by_etag(
    make_client: ClientFactory, picture: str
):
    """The sidebar and the list filter show every avatar on each visit; without this
    they were downloaded again every time and flashed the name's first letter."""
    client = make_client(FakeLLM(), user=None)

    res = await client.get(f"/api/characters/sora/{picture}")

    assert res.headers["cache-control"] == "public, max-age=86400"
    again = await client.get(
        f"/api/characters/sora/{picture}", headers={"if-none-match": res.headers["etag"]}
    )
    assert again.status_code == 304
    assert again.headers["cache-control"] == "public, max-age=86400"
    stale = await client.get(f"/api/characters/sora/{picture}", headers={"if-none-match": '"stale"'})
    assert stale.status_code == 200


@pytest.mark.parametrize(
    ("character", "sheet", "other_sheet"),
    [("sora", MANO_SHEET, KOGANE_SHEET), ("riku", KOGANE_SHEET, MANO_SHEET)],
)
async def test_each_character_talks_with_her_own_character_sheet(
    make_client: ClientFactory, character: str, sheet: str, other_sheet: str
):
    llm = FakeLLM(["<ja>はい</ja><zh>好</zh>"])
    client = make_client(llm)
    conversation_id = await start_conversation(client, character)

    await send_turn(client, conversation_id, "你好")

    system = llm.prompts[0][0]
    assert sheet in system.content
    assert other_sheet not in system.content


async def test_a_character_added_to_the_configuration_can_be_talked_to(
    make_client: ClientFactory, characters: CharacterConfig
):
    characters.add("nagi", "雨宮ナギ", "# 人设\n你是雨宮ナギ。", intro="认真的努力家")
    llm = FakeLLM(["<ja>はい</ja><zh>好</zh>"])
    client = make_client(llm)

    listed = (await client.get("/api/characters")).json()
    conversation_id = await start_conversation(client, "nagi")
    await send_turn(client, conversation_id, "你好")

    assert [c["id"] for c in listed] == ["sora", "riku", "nagi"]
    assert "你是雨宮ナギ。" in llm.prompts[0][0].content


async def test_conversation_with_a_character_removed_from_the_configuration_is_gone(
    make_client: ClientFactory, characters: CharacterConfig
):
    characters.add("nagi", "雨宮ナギ", "# 人设\n你是雨宮ナギ。")
    conversation_id = await start_conversation(make_client(FakeLLM()), "nagi")
    CharacterConfig(characters.directory).add("sora", "星野ソラ", MANO_SHEET)
    client = make_client(FakeLLM())

    res = await client.post(f"/api/conversations/{conversation_id}/turns", json={"text": "你好"})

    assert res.status_code == 404
    assert res.json()["detail"] == "角色不存在"




def test_character_facts_are_split_by_heading(characters: CharacterConfig):
    characters.add(
        "nagi", "雨宮ナギ", "sheet",
        facts="# 档案\n生日是2月27日。\n\n# 人物关系\n\n## 星野ソラ\n同组合的伙伴。\n### 趣事\n一起去看鸟。\n",
    )

    assert load_characters(characters.path)["nagi"].facts == (
        Fact("档案", "档案\n生日是2月27日。"),
        Fact("人物关系 / 星野ソラ", "人物关系 / 星野ソラ\n同组合的伙伴。"),
        Fact("人物关系 / 星野ソラ / 趣事", "人物关系 / 星野ソラ / 趣事\n一起去看鸟。"),
    )


def test_text_before_any_heading_is_an_untitled_fact():
    assert parse_facts("生日是2月27日。\n\n# 档案\n身高155cm。") == (
        Fact(None, "生日是2月27日。"),
        Fact("档案", "档案\n身高155cm。"),
    )


def test_missing_character_sheet_is_reported_with_its_path(tmp_path: Path):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", sheet=None)

    with pytest.raises(CharacterConfigError, match=r"sheets[/\\]sora\.md"):
        load_characters(config.path)


def test_duplicate_character_ids_are_rejected(tmp_path: Path):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a").add("sora", "ソラ", "b")

    with pytest.raises(CharacterConfigError, match="sora"):
        load_characters(config.path)


def test_character_missing_a_required_field_is_rejected(tmp_path: Path):
    config = CharacterConfig(tmp_path)
    config.write("characters.toml", '[[characters]]\nid = "sora"\nname = "星野ソラ"\n')

    with pytest.raises(CharacterConfigError, match="intro、voice_id、sheet、color"):
        load_characters(config.path)


def test_character_id_must_be_safe_to_put_in_a_url(tmp_path: Path):
    config = CharacterConfig(tmp_path)
    config.write("characters.toml", '[[characters]]\nid = "Sora San"\nname = "a"\n'
                 'intro = ""\nvoice_id = "v"\nsheet = "s.md"\ncolor = "#ffbad6"\n')

    with pytest.raises(CharacterConfigError, match="Sora San"):
        load_characters(config.path)


def test_speakers_must_be_a_list_of_names(tmp_path: Path):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")
    config.path.write_text(
        config.path.read_text(encoding="utf-8") + 'speakers = "ソラ"\n', encoding="utf-8"
    )

    with pytest.raises(CharacterConfigError, match="speakers"):
        load_characters(config.path)


def test_two_characters_cannot_share_a_speaker_name(tmp_path: Path):
    config = (
        CharacterConfig(tmp_path)
        .add("sora", "星野ソラ", "a", speakers=["ソラ"])
        .add("sora2", "ソラ", "b", speakers=["ソラ"])
    )

    with pytest.raises(CharacterConfigError, match="ソラ"):
        load_characters(config.path)


def test_missing_configuration_file_is_reported(tmp_path: Path):
    with pytest.raises(CharacterConfigError, match="characters.toml"):
        load_characters(tmp_path / "characters.toml")


@pytest.mark.parametrize("color", ["ffbad6", "#fff", "#ffbad", "#ffbad6ff", "#ggbad6", "pink", ""])
def test_image_colour_must_be_a_hex_rrggbb(tmp_path: Path, color: str):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a", color=color)

    with pytest.raises(CharacterConfigError, match="角色 sora 的 color.*#rrggbb"):
        load_characters(config.path)


def test_image_colour_is_read_in_lower_case(tmp_path: Path):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a", color="#FFBAD6")

    assert load_characters(config.path)["sora"].color == "#ffbad6"


def test_missing_call_background_is_a_warning_and_treated_as_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")
    config.path.write_text(
        config.path.read_text(encoding="utf-8") + 'background = "backgrounds/sora.jpg"\n',
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="eidolon.characters"):
        sora = load_characters(config.path)["sora"]

    assert sora.background is None
    assert "backgrounds" in caplog.text and "sora" in caplog.text


STAND_ASSETS = "https://stand.example/eidolon"






def add_raw(config: CharacterConfig, line: str) -> None:
    config.path.write_text(config.path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")


@pytest.mark.parametrize("value", ['"1"', "0", "1.5", "true"])
def test_display_order_must_be_a_positive_whole_number(tmp_path: Path, value: str):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")
    add_raw(config, f"display_order = {value}")

    with pytest.raises(CharacterConfigError, match="角色 sora 的 display_order"):
        load_characters(config.path)


@pytest.mark.parametrize(
    "value",
    [
        '"1030010010"',
        '"cb/1030010010"',
        '"stand/103001001"',
        '"stand/1030010010/"',
        '"spine/idols/stand/1030010010"',
        "1030010010",
    ],
)
def test_default_outfit_must_name_a_stand_outfit(tmp_path: Path, value: str):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")
    add_raw(config, f"default_outfit = {value}")

    with pytest.raises(CharacterConfigError, match="角色 sora 的 default_outfit.*stand_3d/<slug>"):
        load_characters(config.path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("name_zh", '"  "'), ("name_kana", "1"), ("name_romaji", '"Sakuragi\\rMano"')],
)
def test_other_names_must_each_be_a_line_of_text(tmp_path: Path, field: str, value: str):
    """Not configuring them at all is fine (the list test above)."""
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")
    add_raw(config, f"{field} = {value}")

    with pytest.raises(CharacterConfigError, match=f"角色 sora 的 {field}"):
        load_characters(config.path)








def _jpeg_size(path: Path) -> tuple[int, int]:
    """Width and height from a JPEG's start-of-frame segment, without an imaging library."""
    data = path.read_bytes()
    i = 2
    while i < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2 : i + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7 : i + 9]), int.from_bytes(data[i + 5 : i + 7])
        i += 2 + length
    raise ValueError(f"{path} has no start-of-frame segment")








MANO_GREETING = ("[softly] えっと……はじめまして、星野ソラです", "……初次见面，我是星野ソラ")


def sora_with_greeting(
    characters: CharacterConfig,
    greeting: tuple[str, str] = MANO_GREETING,
    voice_id: str = "sora-voice",
) -> None:
    """Rewrite the configuration with Sora alone, greeting as given."""
    CharacterConfig(characters.directory).add(
        "sora", "星野ソラ", MANO_SHEET, voice_id=voice_id, greeting=greeting
    )


async def listed_greeting(
    make_client: ClientFactory, settings: Settings, assets: str | None = STAND_ASSETS
) -> dict:
    client = make_client(FakeLLM(), settings=replace(settings, stand_assets_url=assets), user=None)
    listed = {c["id"]: c for c in (await client.get("/api/characters")).json()}
    return listed["sora"]["greeting"]


async def test_greeting_is_shown_without_its_delivery_cues_with_its_subtitle_and_where_to_hear_it(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    sora_with_greeting(characters)

    greeting = await listed_greeting(make_client, settings)

    assert greeting["ja"] == "えっと……はじめまして、星野ソラです"
    assert greeting["subtitle"] == "……初次见面，我是星野ソラ"
    assert re.fullmatch(rf"{re.escape(STAND_ASSETS)}/greetings/sora-[0-9a-f]+\.mp3", greeting["audio_url"])


async def test_greeting_has_no_audio_unless_the_stand_assets_are_served(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    sora_with_greeting(characters)

    greeting = await listed_greeting(make_client, settings, assets=None)

    assert greeting == {
        "ja": "えっと……はじめまして、星野ソラです",
        "subtitle": "……初次见面，我是星野ソラ",
        "audio_url": None,
    }


async def test_greeting_audio_moves_when_its_words_or_her_voice_change_but_not_its_subtitle(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    """The address changes with what she says, cues and all, and in what voice, so a
    browser never plays an old one from its cache."""
    sora_with_greeting(characters)
    first = (await listed_greeting(make_client, settings))["audio_url"]
    sora_with_greeting(characters, (MANO_GREETING[0], "初次见面"))
    resubtitled = (await listed_greeting(make_client, settings))["audio_url"]
    sora_with_greeting(characters, ("[happily] えっと……はじめまして、星野ソラです", MANO_GREETING[1]))
    recued = (await listed_greeting(make_client, settings))["audio_url"]
    sora_with_greeting(characters, voice_id="another-voice")
    revoiced = (await listed_greeting(make_client, settings))["audio_url"]

    assert resubtitled == first
    assert len({first, recued, revoiced}) == 3


async def test_greeting_of_a_character_without_a_voice_has_no_audio(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    sora_with_greeting(characters, voice_id="")

    greeting = await listed_greeting(make_client, settings)

    assert greeting["ja"] == "えっと……はじめまして、星野ソラです"
    assert greeting["audio_url"] is None


@pytest.mark.parametrize(
    "lines",
    [
        'greeting = "はじめまして"',
        'greeting_subtitle = "初次见面"',
        'greeting = "[softly]"\ngreeting_subtitle = "初次见面"',
    ],
)
def test_greeting_needs_both_its_words_and_its_subtitle(tmp_path: Path, lines: str):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")
    add_raw(config, lines)

    with pytest.raises(CharacterConfigError, match="角色 sora 的招呼"):
        load_characters(config.path)


def test_greeting_is_optional(tmp_path: Path):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")

    assert load_characters(config.path)["sora"].greeting is None


MANO_CALL_OPENER = (
    "[shyly] あっ、もしもし……ソラです。えっと、今、お電話だいじょうぶですか？",
    "啊，喂……我是ソラ。那个，现在方便接电话吗？",
)


@pytest.mark.parametrize(
    "lines",
    [
        'call_opener = "もしもし"',
        'call_opener_subtitle = "喂"',
        'call_opener = "[shyly]"\ncall_opener_subtitle = "喂"',
    ],
)
def test_call_opener_needs_both_its_words_and_its_subtitle(tmp_path: Path, lines: str):
    """As her greeting does, and said the same way."""
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")
    add_raw(config, lines)

    with pytest.raises(CharacterConfigError, match="角色 sora 的开场白"):
        load_characters(config.path)


def test_call_opener_is_optional(tmp_path: Path):
    config = CharacterConfig(tmp_path).add("sora", "星野ソラ", "a")

    assert load_characters(config.path)["sora"].call_opener is None


def test_call_opener_is_seen_without_its_delivery_cues_apart_from_her_greeting(tmp_path: Path):
    config = CharacterConfig(tmp_path).add(
        "sora", "星野ソラ", "a", greeting=MANO_GREETING, call_opener=MANO_CALL_OPENER
    )

    sora = load_characters(config.path)["sora"]

    assert sora.call_opener is not None and sora.greeting is not None
    assert sora.call_opener.ja == "あっ、もしもし……ソラです。えっと、今、お電話だいじょうぶですか？"
    assert sora.call_opener.subtitle == MANO_CALL_OPENER[1]
    assert sora.greeting.ja == "えっと……はじめまして、星野ソラです"


async def listed_call_opener(
    make_client: ClientFactory, settings: Settings, assets: str | None = STAND_ASSETS
) -> dict:
    client = make_client(FakeLLM(), settings=replace(settings, stand_assets_url=assets), user=None)
    listed = {c["id"]: c for c in (await client.get("/api/characters")).json()}
    return listed["sora"]["call_opener"]


async def test_call_opener_is_listed_without_its_delivery_cues_with_its_subtitle_and_where_to_hear_it(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    CharacterConfig(characters.directory).add(
        "sora", "星野ソラ", MANO_SHEET, voice_id="sora-voice", greeting=MANO_GREETING, call_opener=MANO_CALL_OPENER
    )

    opener = await listed_call_opener(make_client, settings)

    assert opener["ja"] == "あっ、もしもし……ソラです。えっと、今、お電話だいじょうぶですか？"
    assert opener["subtitle"] == "啊，喂……我是ソラ。那个，现在方便接电话吗？"
    assert re.fullmatch(rf"{re.escape(STAND_ASSETS)}/call-openers/sora-[0-9a-f]+\.mp3", opener["audio_url"])
    greeting = await listed_greeting(make_client, settings)
    assert greeting["audio_url"] != opener["audio_url"]


async def test_call_opener_has_no_audio_unless_the_stand_assets_are_served(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    CharacterConfig(characters.directory).add(
        "sora", "星野ソラ", MANO_SHEET, voice_id="sora-voice", call_opener=MANO_CALL_OPENER
    )

    opener = await listed_call_opener(make_client, settings, assets=None)

    assert opener == {
        "ja": "あっ、もしもし……ソラです。えっと、今、お電話だいじょうぶですか？",
        "subtitle": "啊，喂……我是ソラ。那个，现在方便接电话吗？",
        "audio_url": None,
    }
    assert (await listed_greeting(make_client, settings)) is None
