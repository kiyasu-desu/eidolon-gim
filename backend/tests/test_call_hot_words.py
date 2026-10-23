"""Hot words (spec retrieval-and-hotwords, ticket 04): the names a call's speech recognition
is told to listen out for, made once as the server starts from the readings file, the
characters' Chinese names and the world setting's units, and given to every call, on the
deployer's key or the user's own: Alibaba Cloud Model Studio (阿里云百炼) as the task's
`vocabulary`, each at weight 4 but those in Latin letters at 50, Soniox as its context's
`terms`."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from pipecat.frames.frames import ErrorFrame
from pipecat.services.soniox.stt import SonioxContextObject
from pipecat.services.stt_service import STTService
from pipecat.tests.utils import SleepFrame, run_test

from eidolon.assembly import Backend
from eidolon.bailian import BailianSTTService
from eidolon.config import DEFAULT_BAILIAN_STT_MODEL, Settings, SttKey
from eidolon.own_keys import BroughtKeys
from eidolon.world import Idol, Unit, World
from tests.conftest import CharacterConfig
from tests.fakes import FakeCatalog, FakeDashScope, build_faked

READINGS = [
    "櫻木真乃", "櫻木", "真乃",
    "有栖川夏葉", "有栖川", "夏葉",
    "八宮めぐる", "八宮",
    "田中摩美々", "田中", "摩美々",
    "黛冬優子", "黛", "冬優子",
    "月岡恋鐘", "恋鐘",  # her surname not among them
    "L'Antica", "illumination STARS", "283プロ", "283", "天井社長",
    "放課後クライマックスガールズ大集合スペシャル",  # 21 characters
    "The Straylight Story Of Three Girls In Rain",  # 8 words
]

CHARACTERS = [  # id, name, name_zh
    ("mano", "櫻木真乃", "樱木真乃"),
    ("natsuha", "有栖川夏葉", "有栖川夏叶"),
    ("meguru", "八宮めぐる", "八宫巡"),
    ("mamimi", "田中摩美々", "田中摩美美"),
    ("fuyuko", "黛冬優子", "黛冬优子"),
    ("kogane", "月岡恋鐘", "月冈恋钟"),
]

UNITS = ["illumination STARS", "L'Antica", "放課後クライマックスガールズ"]

HOT_WORDS = {
    # every way of writing in the readings file, but lone surnames (櫻木, 有栖川, 八宮, 田中,
    # 黛) and those too long (TOO_LONG)
    "櫻木真乃", "真乃", "有栖川夏葉", "夏葉", "八宮めぐる", "田中摩美々", "摩美々",
    "黛冬優子", "冬優子", "月岡恋鐘", "恋鐘",
    "L'Antica", "illumination STARS", "283プロ", "283", "天井社長",
    # Chinese full names, and given names but where the surname is not known (Kogane)
    # or one character is left (八宫巡 → 巡)
    "樱木真乃", "有栖川夏叶", "夏叶", "八宫巡", "田中摩美美", "摩美美", "黛冬优子", "冬优子",
    "月冈恋钟",
    # units in the world setting
    "放課後クライマックスガールズ",
}

TOO_LONG = ["放課後クライマックスガールズ大集合スペシャル", "The Straylight Story Of Three Girls In Rain"]

DEPLOYERS_DASHSCOPE = "sk-deployers-dashscope"
MY_DASHSCOPE = "sk-my-own-dashscope"
MY_SONIOX = "soniox-my-own-key"


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    """Six idols with their Chinese names, the readings file and the world setting beside
    them."""
    config = CharacterConfig(tmp_path / "characters")
    for id, name, name_zh in CHARACTERS:
        config.add(id, name, f"# 人设\n你是{name}。", other_names=(name_zh, "かな", "Romaji"))
    config.write("readings.toml", "\n".join(
        f'[[readings]]\nwritten = {json.dumps(w, ensure_ascii=False)}\nkana = ""\nphonemes = ""\n'
        for w in READINGS
    ))
    world = World(
        as_of=date(2026, 10, 1),
        office="283プロダクション",
        staff=(),
        units=tuple(Unit(name, None, (), ()) for name in UNITS),
        idols=tuple(Idol(name, "", None, None, ()) for _, name, _ in CHARACTERS),
    )
    config.write("world.json", json.dumps(world.to_json(), ensure_ascii=False))
    return config


@pytest.fixture
async def started(settings: Settings) -> AsyncIterator[Backend]:
    """The backend as the server starts it, its speech services real, with the deployer's
    DashScope key."""
    async with backend(
        replace(settings, stt_provider="bailian", dashscope_api_key=DEPLOYERS_DASHSCOPE)
    ) as started:
        yield started


@asynccontextmanager
async def backend(settings: Settings) -> AsyncIterator[Backend]:
    """The backend `settings` describe, its speech services real."""
    built = build_faked(settings, catalog_transport=FakeCatalog().transport())
    try:
        yield built
    finally:
        await built.aclose()


async def hear(stt: STTService) -> list[ErrorFrame]:
    """Run speech recognition for a moment; the errors it reported."""
    _, up = await run_test(stt, frames_to_send=[SleepFrame(0.3)])
    return [f for f in up if isinstance(f, ErrorFrame)]


@pytest.mark.parametrize(
    "brought",
    [BroughtKeys(), BroughtKeys(stt=SttKey("bailian", MY_DASHSCOPE, "beijing"))],
    ids=["deployers-key", "own-key"],
)
async def test_a_call_heard_by_alibaba_cloud_model_studio_asks_for_the_hot_words_the_latin_ones_at_50(
    started: Backend, dashscope: FakeDashScope, brought: BroughtKeys
):
    dashscope.keys[DEPLOYERS_DASHSCOPE] = "beijing"
    dashscope.keys[MY_DASHSCOPE] = "beijing"
    keys = started.own_keys.for_call(brought)
    assert isinstance(keys.stt, SttKey)

    errors = await hear(started.speech.stt(keys.stt, own="stt" in keys.own).stt)
    keys.release()

    assert errors == []
    [task] = dashscope.tasks
    parameters = task.run_task["payload"]["parameters"]
    assert parameters["vocabulary"] == {
        word: 50 if word in ("L'Antica", "illumination STARS") else 4 for word in HOT_WORDS
    }
    assert parameters["language_hints"] == ["zh", "ja"]
    assert "vocabulary_id" not in parameters
    assert "context" not in task.run_task["payload"]["input"]


async def test_no_more_than_50_latin_hot_words_are_asked_for_at_50(dashscope: FakeDashScope):
    dashscope.keys[DEPLOYERS_DASHSCOPE] = "beijing"
    latin = [f"Unit {i}" for i in range(51)]

    await hear(BailianSTTService(
        api_key=DEPLOYERS_DASHSCOPE, model=DEFAULT_BAILIAN_STT_MODEL, region="beijing",
        hot_words=latin,
    ))

    [task] = dashscope.tasks
    assert task.run_task["payload"]["parameters"]["vocabulary"] == {
        **{word: 50 for word in latin[:50]}, latin[50]: 4
    }


async def test_words_too_long_for_the_services_are_said_to_be_skipped_as_the_server_starts(
    settings: Settings, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING, logger="eidolon.hot_words"):
        async with backend(settings):
            pass

    assert all(word in caplog.text for word in TOO_LONG)


@pytest.mark.parametrize(
    "brought", [BroughtKeys(), BroughtKeys(stt=SttKey("soniox", MY_SONIOX))],
    ids=["deployers-key", "own-key"],
)
async def test_a_call_heard_by_soniox_is_given_the_same_hot_words_as_its_contexts_terms(
    settings: Settings, brought: BroughtKeys
):
    async with backend(settings) as started:  # on the deployer's Soniox key
        keys = started.own_keys.for_call(brought)
        assert isinstance(keys.stt, SttKey)
        stt = started.speech.stt(keys.stt, own="stt" in keys.own).stt
        keys.release()

    assert keys.stt.provider == "soniox"
    context = stt._settings.context  # pyright: ignore[reportAttributeAccessIssue]
    assert isinstance(context, SonioxContextObject)
    assert context.terms is not None
    assert sorted(context.terms) == sorted(HOT_WORDS)
    assert context.text is None and context.general is None
