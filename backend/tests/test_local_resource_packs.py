"""Resource switches cross the same API as ordinary conversations and memories."""

from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.config import Settings
from eidolon.corpus import Episode, Line, StoryCorpus
from tests.conftest import ClientFactory, sign_in_as
from tests.fakes import (
    FakeBackgroundLLM,
    FakeEmbedder,
    FakeJudge,
    FakeLLM,
    FakeReranker,
    context_of,
)
from tests.test_shared_memory import CAT, memorized
from tests.test_text_turn import send_turn, start_conversation

MARKER = "portable-story-marker"
REPLY = ["<ja>はい</ja><zh>好的</zh>"]


@pytest.mark.parametrize(
    "models,stories", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_packs_are_independent_and_switching_preserves_user_history_and_memory(
    make_client: ClientFactory,
    settings: Settings,
    tmp_path: Path,
    models: bool,
    stories: bool,
):
    root = tmp_path / "models"
    model = root / "sora"
    model.mkdir(parents=True)
    (model / "model.json").write_text('{"meshes":[]}', encoding="utf-8")
    (model / "animations.json").write_text('{"clips":[]}', encoding="utf-8")
    embedder = FakeEmbedder()
    corpus = StoryCorpus(settings.story_path, embedder)
    await corpus.save(
        [
            Episode(
                "synthetic",
                "local",
                "test",
                "Synthetic",
                frozenset({"sora"}),
                (Line("speaker", MARKER),),
                "gim-csv",
            )
        ]
    )
    corpus.close()
    configured = replace(
        settings, model_root=root, models_enabled=models, stories_enabled=stories
    )
    llm = FakeLLM(REPLY)
    client = make_client(
        llm,
        settings=configured,
        embedder=embedder,
        reranker=FakeReranker(),
        retrieval_judge=FakeJudge(),
        background_llm=FakeBackgroundLLM(memorized(CAT)),
    )
    character = next(
        c for c in (await client.get("/api/characters")).json() if c["id"] == "sora"
    )
    assert (character["stand"] is not None) == models
    assert (await client.get("/api/characters/sora/stand/model.json")).status_code == (
        200 if models else 404
    )
    conversation = await start_conversation(client)
    events = await send_turn(client, conversation, MARKER)
    assert events[-1]["type"] == "done"
    assert (MARKER in context_of(llm.prompts[-1])) == stories
    assert [m["text"] for m in (await client.get("/api/memories")).json()] == [CAT]

    next_llm = FakeLLM(REPLY)
    restarted = make_client(
        next_llm,
        user=None,
        settings=replace(
            configured, models_enabled=not models, stories_enabled=not stories
        ),
        embedder=embedder,
        reranker=FakeReranker(),
        retrieval_judge=FakeJudge("memories"),
    )
    sign_in_as(restarted, client)
    assert conversation in str(
        (
            await restarted.get("/api/conversations", params={"character_id": "sora"})
        ).json()
    )
    assert [m["text"] for m in (await restarted.get("/api/memories")).json()] == [CAT]
    await send_turn(restarted, conversation, "小白叫什么")
    assert CAT in context_of(next_llm.prompts[-1])
    assert (
        await restarted.get("/api/characters/sora/stand/model.json")
    ).status_code == (404 if models else 200)


async def test_missing_packs_do_not_create_story_files_or_block_text_turns(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
):
    legacy = StoryCorpus(settings.database_path, FakeEmbedder())
    await legacy.save(
        [
            Episode(
                "legacy",
                "local",
                "old",
                "Old",
                frozenset({"sora"}),
                (Line("speaker", MARKER),),
                "gim-csv",
            )
        ]
    )
    legacy.close()
    missing = tmp_path / "unmounted/stories.db"
    llm = FakeLLM(REPLY)
    client = make_client(
        llm,
        settings=replace(
            settings,
            story_database_path=missing,
            model_root=tmp_path / "unmounted-models",
        ),
        embedder=FakeEmbedder(),
        reranker=FakeReranker(),
        retrieval_judge=FakeJudge(),
    )
    assert all(c["stand"] is None for c in (await client.get("/api/characters")).json())
    assert (await send_turn(client, await start_conversation(client), MARKER))[-1][
        "type"
    ] == "done"
    assert not missing.parent.exists()
    assert MARKER not in context_of(llm.prompts[-1])
