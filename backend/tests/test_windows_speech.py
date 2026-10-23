"""Local provider configuration, process boundary and real Pipecat service contracts.

The process boundary is stubbed here. Opt-in integration tests exercise System.Speech
itself; neither the stubs nor these pipeline checks are browser acceptance evidence.
"""

import asyncio
import io
import json
import os
import sys
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pipecat.frames.frames import (
    CancelFrame, Frame, InputAudioRawFrame, InterruptionFrame, LLMFullResponseEndFrame,
    LLMFullResponseStartFrame, OutputTransportMessageFrame, TranscriptionFrame, TTSAudioRawFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test

import eidolon.windows_speech as windows
from eidolon.__main__ import main
from eidolon.assembly import build
from eidolon.call import SegmentCompleteFrame, SegmentTextFrame, call_speech
from eidolon.config import Settings, SttKey, WindowsSpeechSettings
from eidolon.own_keys import BroughtKeys
from eidolon.service_status import probes
from tests.fakes import FakeLLM, FakeServiceClients, FakeSpeech


def test_windows_is_opt_in_and_has_separate_language_and_voice_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EIDOLON_LOCAL_SPEECH", raising=False)
    assert WindowsSpeechSettings.from_env() is None
    monkeypatch.setenv("EIDOLON_LOCAL_SPEECH", "windows")
    assert WindowsSpeechSettings.from_env() == WindowsSpeechSettings()
    monkeypatch.setenv("EIDOLON_WINDOWS_STT_LANGUAGE", "ja-JP")
    monkeypatch.setenv("EIDOLON_WINDOWS_TTS_VOICE", "Microsoft Huihui Desktop")
    monkeypatch.setenv("EIDOLON_WINDOWS_TTS_LANGUAGE", "zh-CN")
    assert WindowsSpeechSettings.from_env() == WindowsSpeechSettings(
        "ja-JP", "Microsoft Huihui Desktop", "zh-CN"
    )
    monkeypatch.setenv("EIDOLON_LOCAL_SPEECH", "guess")
    with pytest.raises(RuntimeError, match="EIDOLON_LOCAL_SPEECH"):
        WindowsSpeechSettings.from_env()


async def test_admission_factory_and_status_need_no_fake_cloud_keys(settings: Settings):
    configured = replace(settings, soniox_api_key=None, fish_audio_api_key=None)
    for local in (None, WindowsSpeechSettings()):
        backend = build(replace(configured, local_speech=local),
                        clients=FakeServiceClients(FakeLLM()))
        try:
            assert backend.config.has_service("stt") == bool(local)
            assert backend.config.has_service("tts") == bool(local)
            if local is None:
                continue
            keys = backend.own_keys.for_call(BroughtKeys())
            assert keys.stt is local and keys.tts is local and keys.own == frozenset()
            hearing, tts = call_speech(backend.speech, keys, "ignored-character-voice", 24000)
            assert isinstance(hearing.stt, windows.WindowsSTT)
            assert isinstance(tts, windows.WindowsTTS)
            keys.release()
            assert backend.calls.ice_servers("local-user")["iceServers"] == []
            for model, unit in ((windows.STT_MODEL, "seconds"), (windows.TTS_MODEL, "bytes")):
                price = backend.prices.pricing().find(windows.LOCAL_PROVIDER, model, unit)
                assert price is not None and price.price.input == 0
        finally:
            await backend.aclose()


async def test_remote_own_keys_override_each_local_side_and_failure_never_falls_back(settings: Settings):
    remote = FakeSpeech()
    backend = build(replace(settings, soniox_api_key=None, fish_audio_api_key=None,
                            local_speech=WindowsSpeechSettings()),
                    speech=remote, clients=FakeServiceClients(FakeLLM()))
    try:
        remote_key = SttKey("soniox", "real-user-selected-key")
        for brought in (BroughtKeys(stt=remote_key), BroughtKeys(tts="remote-fish"),
                        BroughtKeys(stt=remote_key, tts="remote-fish")):
            keys = backend.own_keys.for_call(brought)
            hearing, tts = call_speech(remote, keys, "character", 16000)
            assert isinstance(hearing.stt, windows.WindowsSTT) == (brought.stt is None)
            assert isinstance(tts, windows.WindowsTTS) == (brought.tts is None)
            keys.release()
        remote.down = True
        keys = backend.own_keys.for_call(BroughtKeys(stt=remote_key))
        with pytest.raises(RuntimeError, match="down"):
            call_speech(remote, keys, "character", 16000)
        keys.release()
    finally:
        await backend.aclose()


async def test_startup_rejects_missing_components_and_status_probes_use_local_provider(
    settings: Settings, monkeypatch: pytest.MonkeyPatch,
):
    remote = FakeSpeech()
    backend = build(replace(settings, soniox_api_key=None, fish_audio_api_key=None,
                            local_speech=WindowsSpeechSettings()),
                    speech=remote, clients=FakeServiceClients(FakeLLM()))
    calls: list[str] = []

    async def check(self: windows.WindowsSpeech) -> dict[str, Any]:
        calls.append("check")
        return {}

    async def synthesize(self: windows.WindowsSpeech, text: str, sample_rate: int) -> bytes:
        calls.append("synthesize")
        return b"\1\0"

    async def unavailable(self: windows.WindowsSpeech) -> dict[str, Any]:
        raise windows.WindowsSpeechError("Windows 未安装 ja-JP 声音")

    monkeypatch.setattr(windows.WindowsSpeech, "check", check)
    monkeypatch.setattr(windows.WindowsSpeech, "synthesize", synthesize)
    try:
        local_probes = probes(backend.config, remote, "", None, None)
        await local_probes["stt"]()
        await local_probes["tts"]()
        assert calls == ["check", "synthesize"] and not remote.checked and not remote.voiced
        monkeypatch.setattr(windows.WindowsSpeech, "check", unavailable)
        with pytest.raises(windows.WindowsSpeechError, match="未安装"):
            await backend.start()
    finally:
        await backend.aclose()


async def test_synthesis_validates_pcm_format_and_removes_temporary_wave(monkeypatch: pytest.MonkeyPatch):
    paths: list[Path] = []
    rates = iter([24000, 16000])

    async def synthesize(self: windows.WindowsSpeech, request: dict[str, Any]) -> dict[str, Any]:
        path = Path(request["path"])
        paths.append(path)
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, next(rates), 0, "NONE", "not compressed"))
            audio.writeframes(b"\1\0" * 100)
        return {}

    monkeypatch.setattr(windows.WindowsSpeech, "_run", synthesize)
    speech = windows.WindowsSpeech(WindowsSpeechSettings())
    assert await speech.synthesize("声。", 24000) == b"\1\0" * 100
    with pytest.raises(windows.WindowsSpeechError, match="PCM"):
        await speech.synthesize("声。", 24000)
    assert all(not path.parent.exists() for path in paths)


class Collector(FrameProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.frames: list[Frame] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        self.frames.append(frame)
        await self.push_frame(frame, direction)


async def test_tts_voices_complete_segments_without_cues_and_announces_before_pcm(monkeypatch: pytest.MonkeyPatch):
    voiced: list[tuple[str, int]] = []

    async def synthesize(self: windows.WindowsSpeech, text: str, sample_rate: int) -> bytes:
        voiced.append((text, sample_rate))
        return b"\1\0" * 1600

    monkeypatch.setattr(windows.WindowsSpeech, "synthesize", synthesize)
    tts = windows.WindowsTTS(windows.WindowsSpeech(WindowsSpeechSettings()), 24000)
    collector = Collector()
    await run_test(Pipeline([tts, collector]), frames_to_send=[
        LLMFullResponseStartFrame(), SegmentTextFrame("[softly] <whisper>内", 1, 0),
        SegmentTextFrame("緒</whisper>だよ。", 1, 0), SegmentCompleteFrame(1, 0),
        SegmentTextFrame("未完成", 1, 1), LLMFullResponseEndFrame(), SleepFrame(0.1),
    ])
    assert voiced == [("内緒だよ。", 24000)]
    output = [f for f in collector.frames if isinstance(f, (TTSAudioRawFrame, OutputTransportMessageFrame))]
    assert isinstance(output[0], OutputTransportMessageFrame)
    assert output[0].message["data"] == {"type": "segment-playing", "reply": 1, "segment": 0}
    audio = [f for f in output if isinstance(f, TTSAudioRawFrame)]
    assert b"".join(f.audio for f in audio) == b"\1\0" * 1600
    assert all(f.sample_rate == 24000 and f.num_channels == 1 for f in audio)


async def test_tts_interruption_cancels_current_synthesis_and_drops_incomplete_text(monkeypatch: pytest.MonkeyPatch):
    cancelled = asyncio.Event()

    async def synthesize(self: windows.WindowsSpeech, text: str, sample_rate: int) -> bytes:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
        return b""

    monkeypatch.setattr(windows.WindowsSpeech, "synthesize", synthesize)
    tts = windows.WindowsTTS(windows.WindowsSpeech(WindowsSpeechSettings()), 16000)
    collector = Collector()
    await run_test(Pipeline([tts, collector]), frames_to_send=[
        LLMFullResponseStartFrame(), SegmentTextFrame("声。", 1, 0), SegmentCompleteFrame(1, 0),
        SleepFrame(0.1), InterruptionFrame(), SleepFrame(0.1), CancelFrame(),
    ], send_end_frame=False)
    assert cancelled.is_set()
    assert not any(isinstance(f, TTSAudioRawFrame) for f in collector.frames)


async def test_segmented_stt_finalizes_multisentence_result_ignores_empty_and_drains_eof(monkeypatch: pytest.MonkeyPatch):
    segments: list[bytes] = []

    async def recognize(self: windows.WindowsSpeech, audio: bytes) -> str:
        segments.append(audio)
        return "第一句。 第二句。" if len(segments) == 1 else ""

    monkeypatch.setattr(windows.WindowsSpeech, "recognize", recognize)
    stt = windows.WindowsSTT(windows.WindowsSpeech(WindowsSpeechSettings()))
    collector = Collector()
    await run_test(Pipeline([stt, collector]), frames_to_send=[
        VADUserStartedSpeakingFrame(), InputAudioRawFrame(b"\1\0" * 1600, 16000, 1),
        VADUserStoppedSpeakingFrame(), SleepFrame(0.05),
        VADUserStartedSpeakingFrame(), InputAudioRawFrame(b"\1\0" * 1600, 16000, 1),
        # Graceful EOF flushes the active segment even without a VAD stop.
    ])
    assert len(segments) == 2
    assert all(audio.startswith(b"RIFF") for audio in segments)
    transcripts = [f for f in collector.frames if isinstance(f, TranscriptionFrame)]
    assert [f.text for f in transcripts] == ["第一句。 第二句。"]
    assert transcripts[0].finalized


async def test_memory_chunks_wait_for_real_vad_stop_before_final_transcript(monkeypatch: pytest.MonkeyPatch):
    results = iter(["前半句", "后半句"])

    async def recognize(self: windows.WindowsSpeech, audio: bytes) -> str:
        return next(results)

    monkeypatch.setattr(windows, "MAX_SEGMENT_SECONDS", 1)
    monkeypatch.setattr(windows.WindowsSpeech, "recognize", recognize)
    stt = windows.WindowsSTT(windows.WindowsSpeech(WindowsSpeechSettings()))
    collector = Collector()
    await run_test(Pipeline([stt, collector]), frames_to_send=[
        VADUserStartedSpeakingFrame(), InputAudioRawFrame(b"\1\0" * 16000, 16000, 1),
        SleepFrame(0.1), InputAudioRawFrame(b"\1\0" * 1600, 16000, 1),
        VADUserStoppedSpeakingFrame(), SleepFrame(0.1),
    ])
    final = [frame for frame in collector.frames if isinstance(frame, TranscriptionFrame)]
    assert [frame.text for frame in final] == ["前半句 后半句"]
    stopped = next(i for i, frame in enumerate(collector.frames)
                   if isinstance(frame, VADUserStoppedSpeakingFrame))
    assert all(collector.frames.index(frame) > stopped for frame in final)


async def test_resumed_speech_keeps_late_transcript_with_the_next_phrase(monkeypatch: pytest.MonkeyPatch):
    results = iter(["前半句", "后半句"])

    async def recognize(self: windows.WindowsSpeech, audio: bytes) -> str:
        await asyncio.sleep(0.05)
        return next(results)

    monkeypatch.setattr(windows.WindowsSpeech, "recognize", recognize)
    stt = windows.WindowsSTT(windows.WindowsSpeech(WindowsSpeechSettings()))
    collector = Collector()
    await run_test(Pipeline([stt, collector]), frames_to_send=[
        VADUserStartedSpeakingFrame(), InputAudioRawFrame(b"\1\0" * 1600, 16000, 1),
        VADUserStoppedSpeakingFrame(), VADUserStartedSpeakingFrame(),
        InputAudioRawFrame(b"\1\0" * 1600, 16000, 1), SleepFrame(0.1),
        VADUserStoppedSpeakingFrame(), SleepFrame(0.1),
    ])
    assert [frame.text for frame in collector.frames if isinstance(frame, TranscriptionFrame)] == [
        "前半句 后半句"
    ]


async def test_segmented_stt_bounds_long_audio_and_cancel_drops_pending(monkeypatch: pytest.MonkeyPatch):
    cancelled = asyncio.Event()
    lengths: list[int] = []

    async def recognize(self: windows.WindowsSpeech, audio: bytes) -> str:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            lengths.append(wav.getnframes())
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
        return ""

    monkeypatch.setattr(windows.WindowsSpeech, "recognize", recognize)
    stt = windows.WindowsSTT(windows.WindowsSpeech(WindowsSpeechSettings()))
    await run_test(stt, frames_to_send=[
        VADUserStartedSpeakingFrame(),
        *[InputAudioRawFrame(b"\1\0" * 16000, 16000, 1) for _ in range(21)],
        SleepFrame(0.1), CancelFrame(),
    ], send_end_frame=False)
    assert lengths == [int(16000 * (windows.MAX_SEGMENT_SECONDS + 0.5))]
    assert cancelled.is_set() and not stt._audio_buffer and stt._segment_queue.empty()


async def test_component_errors_are_readable_and_cli_does_not_need_llm_or_cloud_keys(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    async def inventory(self: windows.WindowsSpeech, request: dict[str, Any]) -> dict[str, Any]:
        return {"voices": [{"name": "Microsoft Haruka Desktop", "language": "ja-JP"}],
                "recognizers": [{"name": "中文", "language": "zh-CN"}]}

    monkeypatch.setattr(windows.WindowsSpeech, "_run", inventory)
    assert await asyncio.to_thread(main, ["speech", "check"]) == 0
    assert "中性声音" in capsys.readouterr().out
    with pytest.raises(windows.WindowsSpeechError, match="语音识别器"):
        await windows.WindowsSpeech(WindowsSpeechSettings(recognition_language="missing")).check()
    with pytest.raises(windows.WindowsSpeechError, match="声音"):
        await windows.WindowsSpeech(WindowsSpeechSettings(voice="missing")).check()


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
async def test_hidden_process_is_killed_and_waited_before_audio_cleanup(monkeypatch: pytest.MonkeyPatch, cancel: bool):
    started = asyncio.Event()

    class Process:
        returncode: int | None = None
        killed = False
        waited = False
        path: Path | None = None

        async def communicate(self, data: bytes):
            request = json.loads(data)
            self.path = Path(request["path"])
            assert self.path.exists()
            started.set()
            await asyncio.Future()

        def kill(self):
            self.killed = True
            self.returncode = -1

        async def wait(self):
            self.waited = True
            return self.returncode

    process = Process()

    async def spawn(*args: Any, **kwargs: Any):
        assert "-File" in args and "-NonInteractive" in args
        assert kwargs["creationflags"] == 0x08000000
        return process

    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.shutil, "which", lambda _: "pwsh")
    monkeypatch.setattr(windows.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(windows.asyncio, "create_subprocess_exec", spawn)
    speech = windows.WindowsSpeech(WindowsSpeechSettings(), timeout=1 if cancel else 0.02)
    task = asyncio.create_task(speech.recognize(b"wave bytes"))
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else windows.WindowsSpeechError):
        await task
    assert process.killed and process.waited
    assert process.path is not None and not process.path.parent.exists()


async def test_unsupported_platform_fails_before_spawning(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(windows.sys, "platform", "linux")
    with pytest.raises(windows.WindowsSpeechError, match="只支持 Windows"):
        await windows.WindowsSpeech(WindowsSpeechSettings()).check()


@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("EIDOLON_TEST_WINDOWS_SPEECH") != "1",
                    reason="opt-in installed Windows System.Speech integration")
async def test_installed_windows_speech_round_trip():
    chinese = windows.WindowsSpeech(WindowsSpeechSettings(voice="Microsoft Huihui Desktop",
                                                        voice_language="zh-CN"))
    await chinese.check()
    pcm = await chinese.synthesize("今天的练习结束了，制作人辛苦了。", 16000)
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)
    recognized = await chinese.recognize(output.getvalue())
    assert "练习" in recognized and "制作人" in recognized
    japanese = windows.WindowsSpeech(WindowsSpeechSettings())
    assert await japanese.synthesize("今日のレッスンは終わりました。", 24000)
