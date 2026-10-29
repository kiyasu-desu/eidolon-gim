"""消息列表的摘要：每位角色最新一次对话的最后一句和时间，一次请求拿到。"""

import httpx

from tests.conftest import ClientFactory
from tests.fakes import FakeLLM
from tests.test_text_turn import send_turn, start_conversation


async def latest(client: httpx.AsyncClient) -> dict[str, dict]:
    res = await client.get("/api/conversations/latest")
    assert res.status_code == 200
    return {s["character_id"]: s for s in res.json()}


async def test_each_character_shows_her_newest_conversation_and_its_last_message(
    make_client: ClientFactory,
):
    llm = FakeLLM(["<ja>えっと</ja><zh>哇</zh>"], ["<ja>また明日</ja><zh>明天见</zh>"])
    client = make_client(llm)
    older = await start_conversation(client)
    await send_turn(client, older, "早上好")
    newer = await start_conversation(client)
    await send_turn(client, newer, "晚安")
    await start_conversation(client, "riku")

    summaries = await latest(client)

    sora = summaries["sora"]
    assert sora["conversation_id"] == newer
    last = sora["last_message"]
    assert last["role"] == "character"
    assert (last["ja"], last["zh"]) == ("また明日", "明天见")
    assert last["created_at"]
    # 刚开的新对话还没有话：只给出对话本身和它开始的时间。
    assert summaries["riku"]["last_message"] is None
    assert summaries["riku"]["created_at"]


async def test_a_new_conversation_replaces_the_old_one_in_the_summary(make_client: ClientFactory):
    client = make_client(FakeLLM(["<ja>はい</ja><zh>好</zh>"]))
    await send_turn(client, await start_conversation(client), "你好")
    fresh = await start_conversation(client)

    sora = (await latest(client))["sora"]

    assert sora["conversation_id"] == fresh
    assert sora["last_message"] is None


async def test_other_users_conversations_are_not_shown(make_client: ClientFactory):
    client = make_client(FakeLLM(["<ja>はい</ja><zh>好</zh>"]))
    await send_turn(client, await start_conversation(client), "你好")

    other = make_client(FakeLLM(), user="someone-else")

    assert await latest(other) == {}


async def test_signing_in_is_required(make_client: ClientFactory):
    client = make_client(FakeLLM(), user=None)

    assert (await client.get("/api/conversations/latest")).status_code == 401
