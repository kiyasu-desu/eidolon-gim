"""The character's voice stops at once when she is interrupted.

A websocket TTS interrupted mid-speech reconnects, so that what the service has yet to
send of the old reply is dropped. Fish Audio takes a second or so to; the interruption,
and the server messages behind it, must not wait for that.
"""

import asyncio
from collections.abc import AsyncGenerator

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TTSAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import InterruptibleTTSService
from pipecat.tests.utils import SleepFrame, run_test

from eidolon.call import FishTTS, InterruptsFirst, SpeechServices

CONNECTION = 0.3
"""How long, in seconds, the fake service takes to connect, and to disconnect."""


class SlowSocketTTS(InterruptibleTTSService):
    """Stands in for Fish Audio's websocket TTS: connects when set up and disconnects
    when the call ends, as Fish Audio does, taking `CONNECTION` to do either; logs what
    happens to its connection and what it voices."""

    def __init__(self, log: list[str]) -> None:
        super().__init__(
            sample_rate=16000, settings=TTSSettings(model=None, voice=None, language=None)
        )
        self.log = log
        self.connected = False

    async def setup(self, setup: FrameProcessorSetup) -> None:
        await super().setup(setup)
        await self._connect()

    async def _connect(self) -> None:
        await asyncio.sleep(CONNECTION)
        self.connected = True
        self.log.append("connected")

    async def _disconnect(self) -> None:
        if self.connected:
            await asyncio.sleep(CONNECTION)
            self.connected = False
            self.log.append("disconnected")

    async def _connect_websocket(self) -> None:
        pass

    async def _disconnect_websocket(self) -> None:
        pass

    async def _receive_messages(self) -> None:
        pass

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        self.log.append(f"voiced {text.strip()}")
        yield TTSAudioRawFrame(b"\0\0" * 160, self.sample_rate, 1, context_id=context_id)


class QuickToStopTTS(InterruptsFirst, SlowSocketTTS):
    """The fake service, stopping at once when interrupted as Fish Audio does in calls."""


class Speaker(FrameProcessor):
    """Where the transport's output would be: logs the interruptions and server
    messages that reach it."""

    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self.log.append("interrupted")
        elif isinstance(frame, RTVIServerMessageFrame):
            self.log.append(frame.data["type"])
        await self.push_frame(frame, direction)


async def run(*frames: Frame, settle: float = CONNECTION * 3) -> list[str]:
    """Run the frames through, spaced out, and end the call `settle` seconds later;
    returns the log, from once the service has connected until the call has ended."""
    log: list[str] = []
    spaced: list[Frame] = []
    for frame in frames:
        spaced += [frame, SleepFrame(0.05)]
    async with asyncio.timeout(10):
        await run_test(
            Pipeline([QuickToStopTTS(log), Speaker(log)]),
            frames_to_send=[*spaced, SleepFrame(settle)],
        )
    assert log[0] == "connected"
    return log[1:]


def reply(text: str) -> list[Frame]:
    return [LLMFullResponseStartFrame(), TextFrame(text), LLMFullResponseEndFrame()]


async def test_interrupting_her_while_she_speaks_is_passed_on_before_reconnecting_and_she_speaks_again_once_reconnected():
    log = await run(
        BotStartedSpeakingFrame(),
        InterruptionFrame(),
        RTVIServerMessageFrame(data={"type": "done"}),
        *reply("次のこと。"),
    )

    assert log == [
        "interrupted", "done", "disconnected", "connected", "voiced 次のこと。", "disconnected"
    ]



async def test_interrupting_her_again_while_reconnecting_still_leaves_her_a_voice():
    log = await run(
        BotStartedSpeakingFrame(),
        InterruptionFrame(),
        *reply("二。"),  # waits for the reconnection, and is interrupted waiting
        InterruptionFrame(),
        *reply("三。"),
        settle=CONNECTION * 6,
    )

    assert log[-2:] == ["voiced 三。", "disconnected"]

async def test_interrupting_her_when_she_is_not_speaking_does_not_reconnect():
    log = await run(InterruptionFrame(), *reply("次のこと。"))

    assert log == ["interrupted", "voiced 次のこと。", "disconnected"]


async def test_hanging_up_while_reconnecting_leaves_the_service_disconnected():
    log = await run(BotStartedSpeakingFrame(), InterruptionFrame(), settle=0)
    await asyncio.sleep(CONNECTION * 3)

    assert log == ["interrupted", "disconnected"]


def test_the_character_speaks_through_fish_audio_stopping_at_once():
    tts = SpeechServices().tts("fish-key", "s2.1-pro-free", "sora-voice", 16000, own=False)

    assert isinstance(tts, FishTTS)
