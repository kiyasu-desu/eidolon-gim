"""Real Fish connection failures must reach the worker's unusable policy."""

import asyncio

import pytest
from pipecat.frames.frames import ErrorFrame, Frame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker, ProcessorUnusablePolicy
from pipecat.workers.runner import WorkerRunner
from websockets.protocol import State

from eidolon import call
from tests.test_fish_segments import FakeFish, FakeFishSocket, FishUnderTest, Speaker, reply


async def test_persistent_connection_refusal_cancels_the_worker_without_more_input():
    fish = FakeFish(refused=tuple(range(1, 100)))
    tts = FishUnderTest(fish)
    worker = PipelineWorker(
        Pipeline([tts, Speaker(fish)]),
        processor_unusable_policy=ProcessorUnusablePolicy.CANCEL,
        cancel_on_idle_timeout=False,
        enable_rtvi=False,
    )
    unusable = asyncio.Event()
    errors: list[ErrorFrame] = []

    @worker.event_handler("on_pipeline_error")
    async def failed(worker: PipelineWorker, error: ErrorFrame) -> None:
        errors.append(error)
        if error.processor is tts and not tts.is_usable:
            unusable.set()

    @worker.event_handler("on_pipeline_started")
    async def started(worker: PipelineWorker, frame: Frame) -> None:
        await worker.queue_frames(reply(1, ["テストです。"]))

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    try:
        async with asyncio.timeout(3):
            await unusable.wait()
            await running

        assert fish.attempts == 2
        assert errors[-1].processor is tts
        assert not tts.is_usable
        assert tts._spare is None
        assert not fish.sockets
    finally:
        if not running.done():
            await worker.cancel()
            await running


class StalledStartSocket(FakeFishSocket):
    """Connected, but never accepts the session's start request."""

    def __init__(self, fish: FakeFish, number: int, starting: asyncio.Event) -> None:
        super().__init__(fish, number)
        self.starting = starting

    async def send(self, data: bytes) -> None:
        self.starting.set()
        await asyncio.Event().wait()


class StalledStartFish(FakeFish):
    def __init__(self) -> None:
        super().__init__()
        self.starting = asyncio.Event()

    async def connect(self) -> FakeFishSocket:
        self.attempts += 1
        socket = StalledStartSocket(self, self.attempts, self.starting)
        self.sockets.append(socket)
        return socket


async def test_start_timeout_retries_then_ends_and_aborts_both_half_open_sockets(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(call, "FISH_CONNECT_TIMEOUT", 0.03)
    fish = StalledStartFish()
    tts = FishUnderTest(fish)
    errors: list[ErrorFrame] = []
    worker = PipelineWorker(
        Pipeline([tts]), processor_unusable_policy=ProcessorUnusablePolicy.CANCEL,
        cancel_on_idle_timeout=False, enable_rtvi=False,
    )

    @worker.event_handler("on_pipeline_error")
    async def failed(worker: PipelineWorker, error: ErrorFrame) -> None:
        errors.append(error)

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    async with asyncio.timeout(2):
        await runner.run()

    assert fish.attempts == 2
    assert len(errors) == 2
    assert all(isinstance(error.exception, TimeoutError) for error in errors)
    assert all(socket.state is State.CLOSED for socket in fish.sockets)
    assert not tts.is_usable
    assert tts._spare is None


async def test_cancelling_a_half_open_session_aborts_it_without_retry_or_error():
    fish = StalledStartFish()
    tts = FishUnderTest(fish)
    errors: list[ErrorFrame] = []

    @tts.event_handler("on_error")
    async def failed(tts: FishUnderTest, error: ErrorFrame) -> None:
        errors.append(error)

    opening = asyncio.create_task(tts._open())
    try:
        async with asyncio.timeout(1):
            await fish.starting.wait()
        opening.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opening

        assert fish.attempts == 1
        assert fish.sockets[0].state is State.CLOSED
        assert tts.is_usable
        assert errors == []
    finally:
        if not opening.done():
            opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)
