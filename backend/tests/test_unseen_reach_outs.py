"""Unseen reach-outs (GLOSSARY.md「没看过的搭话」): each line of the conversation list says
whether her newest conversation has a reach-out the user has not seen; reading a conversation's
record, current or past, on any device, has the user see every reach-out in it, before the
record is given back.

Reach-outs are made as `test_reach_outs.py` makes them: the last contact set back in the
database, the reach-outs' tick taken by hand. Whether one in a past conversation is seen shows
nowhere outside, the list going by her newest conversation alone, so that is read in the
database."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import httpx

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FakeRandom
from tests.test_reach_outs import (
    MIDDLE,
    REACH_OUT,
    backend_of,
    last_contact,
    reach_outs,
    record,
    settings,  # noqa: F401  reach-outs on in `.env`
    talked,
)
from tests.test_text_turn import send_turn, start_conversation


async def unseen(client: httpx.AsyncClient) -> dict[str, bool]:
    """Whose line in the conversation list has an unseen reach-out."""
    res = await client.get("/api/conversations/latest")
    assert res.status_code == 200
    return {s["character_id"]: s["unseen_reach_out"] for s in res.json()}


def seen_in(database: Path, conversation: str) -> list[bool]:
    with sqlite3.connect(database) as db:
        rows = db.execute(
            "SELECT seen FROM reach_outs WHERE conversation_id = ? ORDER BY id", (conversation,)
        ).fetchall()
    return [bool(seen) for (seen,) in rows]


async def test_her_line_has_one_unseen_till_her_conversation_is_read_and_no_other_is_touched(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, sora = await talked(
        make_client, ["<ja>はい</ja><zh>好</zh>"], REACH_OUT, REACH_OUT,
        random=FakeRandom(MIDDLE, MIDDLE),
    )
    riku = await start_conversation(client, "riku")
    await send_turn(client, riku, "你好")
    for conversation in (sora, riku):
        last_contact(settings.database_path, conversation, clock.now - timedelta(hours=28))
    assert await unseen(client) == {"sora": False, "riku": False}

    await backend_of(client).reach_outs.run_due()
    assert await unseen(client) == {"sora": True, "riku": True}

    [said] = reach_outs(await record(client, sora))  # given back as it is seen

    assert said["type"] == "reach_out"
    assert await unseen(client) == {"sora": False, "riku": True}


async def test_a_new_conversation_she_has_not_reached_out_in_has_none_unseen(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, conversation = await talked(
        make_client, REACH_OUT, random=FakeRandom(MIDDLE)
    )
    last_contact(settings.database_path, conversation, clock.now - timedelta(hours=28))
    await backend_of(client).reach_outs.run_due()
    assert await unseen(client) == {"sora": True}

    await start_conversation(client)

    assert await unseen(client) == {"sora": False}


async def test_reading_a_past_conversation_has_its_reach_outs_seen(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, past = await talked(make_client, REACH_OUT, random=FakeRandom(MIDDLE))
    last_contact(settings.database_path, past, clock.now - timedelta(hours=28))
    await backend_of(client).reach_outs.run_due()
    await start_conversation(client)  # elsewhere, its record not read here
    assert seen_in(settings.database_path, past) == [False]

    await record(client, past)

    assert seen_in(settings.database_path, past) == [True]
