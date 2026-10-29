"""Her conversations with the user, for the past conversations panel (GLOSSARY.md「当前对话」
「历史对话」): every one, newest first, the first her current one, each with the last thing
in it as the conversation list shows it (her ending it passed over; null while it has none;
marked when it is her reply with a photo she sent) and whether she has ended it. Driven through
the backend's external API, her ending one and hanging up put in the database as recorded
elsewhere, the image service faked at its transport."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

import httpx

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FAKE_JUDGE, FakeImageService, FakeLLM
from tests.test_conversation_events import hang_up
from tests.test_photos import IMAGE, REPLY, asking, photo_events, settled
from tests.test_she_ends_conversation import end
from tests.test_text_turn import send_turn, start_conversation

Answer = Callable[[httpx.Request], Awaitable[httpx.Response]]


async def hers(client: httpx.AsyncClient, character: str = "sora") -> list[dict]:
    res = await client.get("/api/conversations", params={"character_id": character})
    assert res.status_code == 200
    return res.json()


async def test_each_of_her_conversations_comes_with_its_last_message_and_whether_she_ended_it(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(["<ja>また明日</ja><zh>明天见</zh>"]))
    said = await start_conversation(client)
    await send_turn(client, said, "晚安")
    ended = await start_conversation(client)
    at = hang_up(settings.database_path, ended)
    end(settings.database_path, ended)
    current = await start_conversation(client)
    await start_conversation(client, "riku")

    listed = await hers(client)

    assert [c["id"] for c in listed] == [current, ended, said]
    assert [c["ended"] for c in listed] == [False, True, False]
    assert listed[0]["last_message"] is None
    assert listed[1]["last_message"] == {"type": "event", "kind": "hung_up", "created_at": at}
    last = listed[2]["last_message"]
    assert (last["role"], last["text"], last["ja"], last["zh"]) == (
        "character", None, "また明日", "明天见"
    )
    assert last["created_at"]


async def test_her_last_reply_is_marked_only_once_the_photo_she_sent_with_it_is_out(
    make_client: ClientFactory, settings: Settings
):
    client = photographing(make_client, settings)
    sent = await with_photo(client)
    failed = await with_photo(client)
    pending = await with_photo(client, settle=False)

    listed = {c["id"]: c["last_message"] for c in await hers(client)}

    assert listed[sent]["photo"] is True
    assert (listed[sent]["ja"], listed[sent]["zh"]) == ("はい、どうぞ", "给，你看")
    assert "photo" not in listed[failed]
    assert "photo" not in listed[pending]


def photographing(make_client: ClientFactory, settings: Settings) -> httpx.AsyncClient:
    """A client whose turns each ask for a photo she sends, with the deployer's image
    generation and the judge model: the first comes out, the second fails at the image
    service, the third is still being generated."""
    return make_client(
        FakeLLM(REPLY, REPLY, REPLY),
        settings=replace(settings, image=IMAGE, judge=FAKE_JUDGE, affinity_and_gifts=False),
        clients=asking(),
        image_transport=in_turn(FakeImageService().handle, broken, taking_its_time()),
    )


async def with_photo(client: httpx.AsyncClient, settle: bool = True) -> str:
    """A new conversation whose last thing is her reply with a photo; waited on until the
    photo is no longer being generated if `settle`."""
    conversation = await start_conversation(client)
    [photo] = photo_events(await send_turn(client, conversation, "发张自拍给我看看"))
    if settle:
        await settled(client, photo["id"])
    return conversation


def in_turn(*answers: Answer) -> httpx.AsyncBaseTransport:
    """An image service answering each photo asked of it the next way in `answers`."""
    ways = iter(answers)

    async def handle(request: httpx.Request) -> httpx.Response:
        return await next(ways)(request)

    return httpx.MockTransport(handle)


async def broken(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="the image service is down")


def taking_its_time() -> Answer:
    """An image service never answering within the test: the photo stays being generated."""
    held = FakeImageService()
    held.gate = asyncio.Event()
    return held.handle
