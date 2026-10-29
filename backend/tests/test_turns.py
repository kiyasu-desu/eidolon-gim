"""The turn protocol, driven through the conversation engine's interface.

Every turn opens with `user` and closes with `done` or `error`, whether it arrives as a
text turn or during a call; the SSE and call tests only cover how each carries it.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import pytest

from eidolon.config import Settings
from eidolon.engine import MAX_INPUT_LENGTH
from eidolon.llm import ToolCall
from eidolon.own_keys import BroughtKeys
from eidolon.reply_format import Segment, SegmentComplete, SpeechDelta
from eidolon.store import Conversation, Store
from tests.fakes import (
    HANG,
    FakeBackgroundLLM,
    FakeEmbedder,
    FakeJudge,
    FakeLLM,
    FakeReranker,
    build_faked,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
REPLY = ["<ja>えっと、</ja><zh>哇，</zh>"]


class Turns:
    """A conversation with Sora and the engine that takes its turns."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store = Store(settings.database_path)
        user = self._store.create_user("producer")
        self.conversation: Conversation = self._store.create_conversation(user.id, "sora")

    async def take(
        self,
        llm: FakeLLM,
        text: str,
        *,
        in_house: bool = False,
        stop_after: int | None = None,
        **services: Any,
    ) -> list[dict]:
        """Take one turn; returns its events as they go out on the wire, and with
        `in_house` also those that stay on the server. With `stop_after`, the turn is told
        to stop a moment after that segment is complete, by when it is waiting on the
        model or a tool. Any other keyword is a script for the deployer's models or an
        outside service to use (see `fakes.build_faked`)."""
        backend = build_faked(self._settings, llm, clock=lambda: NOW, **services)
        stop = asyncio.Event()
        events = []
        try:
            llms = backend.own_keys.for_turn(BroughtKeys()).llms
            async for event in backend.engine.turn(self.conversation, text, llms, stop=stop):
                events.append(event)
                if isinstance(event, SegmentComplete) and event.segment == stop_after:
                    asyncio.get_running_loop().call_later(0.05, stop.set)
        finally:
            await backend.aclose()
        return [
            asdict(e) for e in events if in_house or not isinstance(e, SegmentComplete | SpeechDelta)
        ]

    def record(self) -> list[tuple]:
        return [(m.role, m.text, m.ja) for m in self._store.list_messages(self.conversation.id)]

    def close(self) -> None:
        self._store.close()


@pytest.fixture
def turns(settings: Settings) -> Iterator[Turns]:
    turns = Turns(settings)
    yield turns
    turns.close()


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


async def test_input_longer_than_the_limit_is_rejected_without_reaching_the_model(turns: Turns):
    llm = FakeLLM(REPLY)

    events = await turns.take(llm, "啊" * (MAX_INPUT_LENGTH + 1))

    assert types(events) == ["user", "error"]
    assert events[-1]["message"] == f"这句话太长了，最多 {MAX_INPUT_LENGTH} 字。"
    assert llm.prompts == []
    assert turns.record() == []


async def test_blank_input_is_rejected_without_reaching_the_model(turns: Turns):
    llm = FakeLLM(REPLY)

    events = await turns.take(llm, " \n\t")

    assert events == [{"type": "user", "text": ""}, {"type": "error", "message": "没有收到要说的话。"}]
    assert llm.prompts == []
    assert turns.record() == []


async def test_a_turn_opens_with_what_the_user_said_and_closes_with_the_recorded_reply(
    turns: Turns,
):
    events = await turns.take(FakeLLM(REPLY), "  早上好\n")

    assert types(events) == ["user", "delta", "delta", "done"]
    assert events[0]["text"] == "早上好"
    assert events[-1]["message"]["ja"] == "えっと、"
    assert turns.record() == [("user", "早上好", None), ("character", None, "えっと、")]


async def test_chinese_dialogue_is_rewritten_before_speech_recording_and_the_next_turn(turns: Turns):
    llm = FakeLLM(
        ["<ja>[shyly] えっ……那个，テン", "，听到这话，脸就有点热……</ja><zh>テン脸有点热。</zh>"],
        ["<ja>[shyly] えっ……テン、顔が熱くなった……</ja>"],
        ["<ja>うん……</ja><zh>嗯……</zh>"],
    )
    events = await turns.take(llm, "继续聊吧", in_house=True)

    assert types(events)[-1] == "done"
    assert events[-1]["message"]["ja"] == "えっ……テン、顔が熱くなった……"
    speech = "".join(e["text"] for e in events if e["type"] == "speech-delta")
    assert speech == "[shyly]えっ……テン、顔が熱くなった……"
    assert turns.record()[-1][2] == "[shyly] えっ……テン、顔が熱くなった……"
    await turns.take(llm, "嗯")
    assert len(llm.prompts) == 3
    assert llm.tools[1] == []
    assert any("<ja>[shyly] えっ……テン、顔が熱くなった……</ja>" in m.content
               for m in llm.prompts[2] if m.role == "assistant")
    assert not any("那个，テン，听到这话" in m.content for m in llm.prompts[2])


async def test_legacy_chinese_is_only_context_not_an_assistant_example(turns: Turns, settings: Settings):
    old = "那个……テン，明天也会去……"
    store = Store(settings.database_path)
    try:
        store.add_turn(turns.conversation.id, "明天见", [Segment(old, "明天也会去。")])
        llm = FakeLLM(["<ja>また明日……</ja><zh>明天见……</zh>"])
        events = await turns.take(llm, "记得约定吗")

        assert events[-1]["type"] == "done"
        assert len(llm.prompts) == 1  # old mistakes do not cause a translation request every turn
        assert any(m.role == "system" and "previous_dialogue_meaning" in m.content
                   and "明天也会去" in m.content for m in llm.prompts[0])
        assert not any(m.role == "assistant" and old in m.content for m in llm.prompts[0])
        assert store.list_messages(turns.conversation.id)[1].ja == old
    finally:
        store.close()


async def test_correction_failure_never_speaks_or_records_the_rejected_chinese(turns: Turns):
    llm = FakeLLM(
        ["<ja>你好</ja><zh>你好</zh>"], ["<ja>还是中文</ja>"], ["<ja>还是中文</ja>"],
    )
    events = await turns.take(llm, "你好", in_house=True)
    assert types(events) == ["user", "error"]
    assert len(llm.prompts) == 3
    assert turns.record() == []


async def test_a_corrected_tool_round_does_not_feed_the_original_chinese_back_to_the_model(turns: Turns):
    llm = FakeLLM(
        ["<ja>我想回忆一下</ja><zh>我想回忆一下。</zh>",
         ToolCall("recall", "recall_story", {"query": "公園"})],
        ["<ja>思い出してみるね。</ja>"],
        ["<ja>覚えてるよ。</ja><zh>记得哦。</zh>"],
    )
    events = await turns.take(
        llm, "还记得公园吗", retrieval_judge=FakeJudge(answer="nothing"),
        embedder=FakeEmbedder(), reranker=FakeReranker(), background_llm=FakeBackgroundLLM(),
    )
    assert events[-1]["type"] == "done"
    assert len(llm.prompts) == 3
    recalled = next(m for m in llm.prompts[2] if m.tool_calls)
    assert recalled.content == "<ja>思い出してみるね。</ja><zh>我想回忆一下。</zh>"
    assert recalled.tool_calls[0].id == "recall"


async def test_reach_outs_use_the_same_language_check(settings: Settings, turns: Turns):
    llm = FakeLLM(
        ["<ja>今天也会好好练习</ja><zh>今天也会好好练习。</zh>"],
        ["<ja>今日も頑張るね。</ja>"],
    )
    backend = build_faked(settings, llm, clock=lambda: NOW)
    try:
        segments = await backend.engine.reach_out(turns.conversation, llm)
        assert segments == [Segment("今日も頑張るね。", "今天也会好好练习。")]
        assert len(llm.prompts) == 2
    finally:
        await backend.aclose()


async def test_stopping_during_correction_keeps_only_earlier_complete_segments(
    settings: Settings, turns: Turns,
):
    closed = asyncio.Event()

    class TrackedLLM(FakeLLM):
        async def stream_with(self, key, messages, tools=(), *, forbid_calls=False):
            correction = bool(self.prompts)
            try:
                async for part in super().stream_with(key, messages, tools, forbid_calls=forbid_calls):
                    yield part
            finally:
                if correction:
                    closed.set()

    llm = TrackedLLM(
        ["<ja>うん。</ja><zh>嗯。</zh><ja>你好</ja><zh>你好</zh>"], [HANG],
    )
    backend = build_faked(settings, llm, clock=lambda: NOW)
    stop = asyncio.Event()
    events = []

    async def take():
        llms = backend.own_keys.for_turn(BroughtKeys()).llms
        async for event in backend.engine.turn(turns.conversation, "你好", llms, stop=stop):
            events.append(asdict(event))

    task = asyncio.create_task(take())
    try:
        async with asyncio.timeout(2):
            while len(llm.prompts) < 2:
                await asyncio.sleep(0)
            stop.set()
            await task
        await asyncio.wait_for(closed.wait(), timeout=1)
        assert events[-1]["type"] == "done"
        assert events[-1]["message"]["ja"] == "うん。"
        assert turns.record()[-1][2] == "うん。"
    finally:
        task.cancel()
        await backend.aclose()


async def test_a_segment_is_complete_once_its_subtitle_closes_the_next_opens_or_the_model_stops(
    turns: Turns,
):
    llm = FakeLLM(["<ja>一</ja>", "<zh>一</zh>", "<ja>二</ja>", "<ja>三</ja><zh>三"])

    events = await turns.take(llm, "早上好", in_house=True)

    assert [(e["type"], e.get("segment")) for e in events[1:]] == [
        ("delta", 0), ("speech-delta", 0), ("delta", 0), ("segment-complete", 0),
        ("delta", 1), ("speech-delta", 1), ("segment-complete", 1),
        ("delta", 2), ("speech-delta", 2), ("delta", 2), ("segment-complete", 2),
        ("done", None),
    ]


@pytest.mark.parametrize(
    "llm",
    [FakeLLM(), FakeLLM(["  \n"])],  # the model call fails; the model says nothing
    ids=["model fails", "empty reply"],
)
async def test_a_failed_turn_closes_with_an_error_and_leaves_no_record(
    turns: Turns, llm: FakeLLM, caplog: pytest.LogCaptureFixture
):
    events = await turns.take(llm, "在吗")

    assert types(events)[0] == "user"
    assert events[-1] == {"type": "error", "message": "角色暂时无法回复，请稍后再试。"}
    assert turns.record() == []
    assert "turn failed" in caplog.text  # what went wrong stays in the server log


async def test_a_turn_told_to_stop_is_recorded_with_only_its_complete_segments(turns: Turns):
    memory = FakeBackgroundLLM()
    llm = FakeLLM(["<ja>えっと</ja><zh>哇</zh><ja>今日", "も</ja>", HANG])

    events = await turns.take(
        llm, "早上好", stop_after=0,
        background_llm=memory, retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker(),
    )

    assert events[-1]["type"] == "done"
    assert (events[-1]["message"]["ja"], events[-1]["message"]["zh"]) == ("えっと", "哇")
    assert turns.record() == [("user", "早上好", None), ("character", None, "えっと")]
    assert len(memory.prompts) == 1  # what the user revealed is written down as ever


async def test_a_turn_told_to_stop_in_its_tool_round_is_recorded_with_its_complete_segments(
    turns: Turns,
):
    llm = FakeLLM(
        ["<ja>ええと</ja><zh>嗯</zh>", ToolCall("call_1", "recall_story", {"query": "公園"})],
        ["<ja>公園で</ja><zh>在公园</zh>", "<ja>歌", HANG],
    )

    events = await turns.take(
        llm, "那次在公园怎么了？", stop_after=1,
        retrieval_judge=FakeJudge(answer="nothing"), embedder=FakeEmbedder(), reranker=FakeReranker(),
        background_llm=FakeBackgroundLLM(),
    )

    assert len(llm.prompts) == 2  # the tool was called and the model asked again
    assert events[-1]["type"] == "done"
    assert turns.record()[-1] == ("character", None, "ええと公園で")


class HangingEmbedder(FakeEmbedder):
    """Never answers the query `hang_on`, as a service that has stopped responding."""

    def __init__(self, hang_on: str) -> None:
        super().__init__()
        self._hang_on = hang_on

    async def embed_query(self, text: str) -> list[float]:
        if text == self._hang_on:
            await asyncio.Event().wait()
        return await super().embed_query(text)


async def test_a_turn_told_to_stop_while_a_tool_runs_is_recorded_with_its_complete_segments(
    turns: Turns,
):
    llm = FakeLLM(
        ["<ja>ええと</ja><zh>嗯</zh>", ToolCall("call_1", "recall_story", {"query": "鳩の歌"})]
    )

    events = await turns.take(
        llm, "那次和鸽子唱歌怎么了？", stop_after=0,
        retrieval_judge=FakeJudge(answer="nothing"), embedder=HangingEmbedder("鳩の歌"),
        reranker=FakeReranker(), background_llm=FakeBackgroundLLM(),
    )

    assert len(llm.prompts) == 1  # the model was not asked again
    assert events[-1]["type"] == "done"
    assert turns.record()[-1] == ("character", None, "ええと")
