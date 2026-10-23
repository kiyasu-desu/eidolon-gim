"""Windows System.Speech behind bounded, cancellable, hidden PowerShell processes.

Only the installed neutral voice is used. No character voice or external API is implied.
Text and filenames travel as JSON on stdin, never as PowerShell source or shell arguments.
"""

import asyncio
import io
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from collections import deque
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from pipecat.frames.frames import (
    AggregatedTextFrame, CancelFrame, EndFrame, ErrorFrame, Frame, InputAudioRawFrame,
    InterimTranscriptionFrame, InterruptionFrame, LLMFullResponseEndFrame,
    TranscriptionFrame, TTSAudioRawFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from eidolon.config import WindowsSpeechSettings
from eidolon.delivery_cues import without_cues

LOCAL_PROVIDER = "windows-system-speech"
STT_MODEL = "System.Speech.Dictation"
TTS_MODEL = "System.Speech.Synthesis"
MAX_SEGMENT_SECONDS = 20
MAX_QUEUED_SEGMENTS = 4
MAX_TRANSCRIPT_CHARACTERS = 16000


class WindowsSpeechError(RuntimeError):
    """A missing component, failed recognition/synthesis, or a bounded timeout."""


class WindowsSpeech:
    """One subprocess per operation; cancellation waits for its death before cleanup."""

    def __init__(self, settings: WindowsSpeechSettings, *, timeout: float = 45) -> None:
        self.settings = settings
        self.timeout = timeout

    async def _run(self, request: dict[str, Any]) -> dict[str, Any]:
        if sys.platform != "win32":
            raise WindowsSpeechError("本机语音只支持 Windows；请关闭 EIDOLON_LOCAL_SPEECH 或使用远程语音")
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            raise WindowsSpeechError("本机语音找不到 PowerShell（pwsh / powershell）")
        starting = asyncio.create_task(asyncio.create_subprocess_exec(
            executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
            str(Path(__file__).with_suffix(".ps1")),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ))
        process = None
        try:
            async with asyncio.timeout(self.timeout):
                process = await asyncio.shield(starting)
                stdout, stderr = await process.communicate(
                    json.dumps(request, ensure_ascii=False).encode("utf-8")
                )
        except BaseException as error:
            # Cancellation may arrive while the OS is still creating the process.
            # Shield the spawn so we can obtain its handle and terminate it too.
            if process is None:
                try:
                    process = await starting
                except Exception:
                    raise error
            if process.returncode is None:
                process.kill()
            await process.wait()
            if isinstance(error, TimeoutError):
                raise WindowsSpeechError(f"Windows 本机语音超过 {self.timeout:g} 秒，已停止") from None
            raise
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace").strip()[:1000]
            raise WindowsSpeechError(f"Windows 本机语音失败：{detail or 'PowerShell 未正常退出'}")
        try:
            result = json.loads(stdout.decode("utf-8-sig"))
            if not isinstance(result, dict):
                raise ValueError("expected object")
            return result
        except (ValueError, UnicodeError):
            raise WindowsSpeechError("Windows 本机语音返回了无效结果") from None

    async def installed(self) -> dict[str, Any]:
        """The enabled installed voices and recognizers, without configuration secrets."""
        return await self._run({"action": "check"})

    def validate(self, result: dict[str, Any]) -> None:
        """Check the selected components against an installed inventory."""
        configured = self.settings
        if not any(r["language"] == configured.recognition_language for r in result["recognizers"]):
            raise WindowsSpeechError(f"Windows 未安装 {configured.recognition_language} 语音识别器")
        if not any(v["name"] == configured.voice and v["language"] == configured.voice_language
                   for v in result["voices"]):
            raise WindowsSpeechError(
                f"Windows 未安装 {configured.voice_language} 声音「{configured.voice}」；"
                "运行 eidolon speech check 查看已安装组件"
            )

    async def check(self) -> dict[str, Any]:
        """Enumerate components and verify the explicitly configured language and voice."""
        result = await self.installed()
        self.validate(result)
        return result

    async def recognize(self, audio: bytes) -> str:
        # SegmentedSTTService supplies a WAV container, not a headerless PCM stream.
        with tempfile.TemporaryDirectory(prefix="eidolon-stt-") as directory:
            path = Path(directory) / "input.wav"
            path.write_bytes(audio)
            result = await self._run({"action": "stt", "language": self.settings.recognition_language,
                                      "path": str(path)})
        text = result.get("text", "")
        if not isinstance(text, str):
            raise WindowsSpeechError("Windows 语音识别返回了无效文字")
        return text.strip()

    async def synthesize(self, text: str, sample_rate: int) -> bytes:
        with tempfile.TemporaryDirectory(prefix="eidolon-tts-") as directory:
            path = Path(directory) / "output.wav"
            await self._run({"action": "tts", "voice": self.settings.voice, "text": text,
                             "sample_rate": sample_rate, "path": str(path)})
            with wave.open(io.BytesIO(path.read_bytes()), "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, sample_rate):
                    raise WindowsSpeechError("Windows 合成音频不是请求的单声道 16-bit PCM")
                pcm = audio.readframes(audio.getnframes())
        if not pcm:
            raise WindowsSpeechError("Windows 语音合成没有返回音频")
        return pcm


class WindowsSTT(SegmentedSTTService):
    """Silero VAD segments, at most 20 s each and four queued; EOF is finite."""

    def __init__(self, speech: WindowsSpeech) -> None:
        super().__init__(settings=STTSettings(
            model=f"{STT_MODEL}/{speech.settings.recognition_language}",
            language=speech.settings.recognition_language,
        ))
        self.speech = speech
        self._segment_ends: deque[bool] = deque()
        self._transcript = ""

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        final = self._segment_ends.popleft() if self._segment_ends else True
        try:
            text = await self.speech.recognize(audio)
            if text:
                self._transcript = " ".join(part for part in (self._transcript, text) if part)
            if len(self._transcript) > MAX_TRANSCRIPT_CHARACTERS:
                self._transcript = ""
                yield ErrorFrame(error="Windows 连续发言过长，通话已停止", fatal=True)
                return
            if final and not self._user_speaking and not self._segment_ends:
                transcript, self._transcript = self._transcript, ""
                if transcript:
                    yield TranscriptionFrame(transcript, self._user_id, time_now_iso8601(), finalized=True)
            elif self._transcript:
                # A memory boundary is not a user turn boundary. Keep the call
                # informed of hearing while withholding the final turn until VAD stops.
                yield InterimTranscriptionFrame(self._transcript, self._user_id, time_now_iso8601())
        except WindowsSpeechError as error:
            self._transcript = ""
            yield ErrorFrame(error=str(error), fatal=True)

    async def _handle_user_stopped_speaking(self, frame: VADUserStoppedSpeakingFrame):
        await self._queue_audio(frame, final=True)

    async def _queue_audio(self, frame: VADUserStoppedSpeakingFrame, *, final: bool) -> bool:
        if not self.is_usable:
            self._audio_buffer.clear()
            self._user_speaking = False
            return False
        if self._segment_queue.qsize() >= MAX_QUEUED_SEGMENTS:
            self._audio_buffer.clear()
            self._user_speaking = False
            self._transcript = ""
            await self.push_error("Windows 识别处理跟不上输入，通话已停止", fatal=True)
            return False
        self._segment_ends.append(final)
        await super()._handle_user_stopped_speaking(frame)
        return True

    async def process_audio_frame(self, frame: InputAudioRawFrame, direction: FrameDirection):
        await super().process_audio_frame(frame, direction)
        if self._user_speaking and len(self._audio_buffer) >= self.sample_rate * 2 * MAX_SEGMENT_SECONDS:
            self._user_speaking = await self._queue_audio(VADUserStoppedSpeakingFrame(), final=False)

    async def stop(self, frame: EndFrame):
        if self._user_speaking and self._audio_buffer:
            await self._handle_user_stopped_speaking(VADUserStoppedSpeakingFrame())
        await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        self._audio_buffer.clear()
        self._segment_ends.clear()
        self._transcript = ""
        while not self._segment_queue.empty():
            self._segment_queue.get_nowait()


class WindowsTTS(TTSService):
    """Voice complete reply segments in the installed neutral voice, without cues."""

    def __init__(self, speech: WindowsSpeech, sample_rate: int) -> None:
        super().__init__(sample_rate=sample_rate, push_start_frame=True, push_stop_frames=True,
                         settings=TTSSettings(model=f"{TTS_MODEL}/{speech.settings.voice}",
                                              voice=speech.settings.voice,
                                              language=speech.settings.voice_language))
        self.speech = speech
        self._segment: tuple[int, int] | None = None
        self._text = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        from eidolon.call import SegmentCompleteFrame, SegmentTextFrame

        if isinstance(frame, SegmentTextFrame):
            self._segment = (frame.reply, frame.segment)
            self._text += frame.text
            if len(self._text) > 16000:
                self._text = ""
                await self.push_error("Windows 语音片段过长，通话已停止", fatal=True)
            return
        if isinstance(frame, SegmentCompleteFrame) and self._segment == (frame.reply, frame.segment):
            text, self._text = without_cues(self._text), ""
            if text.strip():
                await super().process_frame(AggregatedTextFrame(text, "sentence"), direction)
        elif isinstance(frame, (InterruptionFrame, CancelFrame, LLMFullResponseEndFrame)):
            self._text = ""  # Incomplete segments are never voiced.
            self._segment = None
        await super().process_frame(frame, direction)

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        from eidolon.call import segment_playing

        try:
            text = without_cues(text)
            pcm = await self.speech.synthesize(text, self.sample_rate)
            if self._segment is not None:
                yield segment_playing(*self._segment)
            await self.start_tts_usage_metrics(text)
            # Keep transport chunks small; audio contexts handle playback and interruption.
            size = self.sample_rate // 50 * 2
            for offset in range(0, len(pcm), size):
                yield TTSAudioRawFrame(pcm[offset:offset + size], self.sample_rate, 1,
                                       context_id=context_id)
        except WindowsSpeechError as error:
            yield ErrorFrame(error=str(error), fatal=True)
