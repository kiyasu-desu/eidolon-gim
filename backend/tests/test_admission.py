"""Letting a turn or call begin and settling it once it is over, through `Admissions`
alone: whose keys it runs on, its activity record, its use of the limit and the deployer's
lease, each of them looked at as the admin and the limiter see them.

All of it is real, on a fresh database, but the deployer, which counts its leases, and the
speech services the user's own keys are tried on; the user is allowed one turn and one
call an hour.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from eidolon.activity import ActivityLog, Result
from eidolon.admission import Admissions
from eidolon.config import EXEMPTING_SERVICES, ChatModelSettings, LLMSettings, SttKey, UsageLimits
from eidolon.own_keys import (
    BroughtKeys,
    CallsUnavailable,
    DeployerKeys,
    DeployerLease,
    OwnKeys,
)
from eidolon.store import Store
from eidolon.usage import OverLimit, UsageKind, UsageLimiter
from tests.fakes import FakeBackgroundLLM, FakeClock, FakeLLM, FakeLLMService, FakeSpeech

MY_LLM = ChatModelSettings(
    LLMSettings("https://llm.example.com/v1", "sk-my-own-llm-cccc", "my-model")
)
ALL_OWN = BroughtKeys(MY_LLM, "my-own-fish", SttKey("soniox", "my-own-soniox"))
"""The user's own LLM and speech keys, which their calls are exempt on."""


class CountingDeployer:
    """The deployer's keys, counting how many times they were leased and let go."""

    def __init__(self) -> None:
        self.keys = DeployerKeys(
            FakeLLM(), FakeBackgroundLLM(), SttKey("soniox", "deployer-soniox"), "deployer-fish"
        )
        self.leased = 0
        self.released = 0

    def lease(self) -> DeployerLease:
        self.leased += 1
        return DeployerLease(self.keys, self._release)

    def _release(self) -> None:
        self.released += 1


class Deployment:
    """A user allowed one turn and one call an hour, and everything letting them begin."""

    def __init__(self, path: Path) -> None:
        self.clock = FakeClock()
        self.store = Store(path)
        self.user = self.store.create_user("producer").id
        self.usage = UsageLimiter(
            path, UsageLimits(turns_per_hour=1, calls_per_hour=1), self.clock
        )
        self.activity = ActivityLog(path, self.clock)
        self.deployer = CountingDeployer()
        self.llm_service = FakeLLMService()
        self.speech = FakeSpeech()

    def admissions(self) -> Admissions:
        return Admissions(
            self.usage, self.activity, self.own_keys(), cooldown_until=lambda *_: None
        )

    def own_keys(self) -> OwnKeys:
        return OwnKeys(
            self.llm_service, self.deployer, self.activity, self.speech,
            exempting=lambda: frozenset(EXEMPTING_SERVICES),
        )

    def counted(self, kind: UsageKind = "turn") -> bool:
        """Whether this hour's turn, or call, is used up, that is, the last one counted."""
        try:
            self.usage.take(self.user, kind).give_back()
        except OverLimit:
            return True
        return False

    def turns_taken(self) -> int:
        """Uses of the limit kept for the admin, counting or not."""
        return self.usage.last_day(self.user).total.turns

    def calls_taken(self) -> int:
        return self.usage.last_day(self.user).total.calls

    def records(self) -> list[tuple[Result, bool]]:
        """Each of the user's records: how it turned out, and whether on their own keys."""
        return [
            (r.result, r.own_keys)
            for r in self.activity.of_user(self.user, self.clock() - timedelta(hours=1))
        ]

    def close(self) -> None:
        self.activity.close()
        self.usage.close()
        self.store.close()


@pytest.fixture
def deployment(tmp_path: Path) -> Iterator[Deployment]:
    deployment = Deployment(tmp_path / "eidolon.db")
    yield deployment
    deployment.close()


@pytest.mark.parametrize(
    ("result", "counted"),
    [("success", True), ("failed", False), ("rejected", False), ("left", True)],
)
def test_a_turn_counts_when_it_succeeded_or_was_left_and_is_given_back_otherwise(
    deployment: Deployment, result: Result, counted: bool
):
    admission = deployment.admissions().turn(deployment.user, "sora", BroughtKeys())

    admission.settle(result)

    assert deployment.counted() is counted
    assert admission.counts(result) is counted
    assert deployment.records() == [(result, False)]
    assert deployment.deployer.released == 1


def test_a_turn_over_the_limit_is_refused_recorded_rejected_and_lets_go_of_its_lease(
    deployment: Deployment,
):
    admissions = deployment.admissions()
    admissions.turn(deployment.user, "sora", BroughtKeys()).settle("success")

    with pytest.raises(OverLimit):
        admissions.turn(deployment.user, "sora", BroughtKeys())

    assert deployment.turns_taken() == 1
    assert deployment.records() == [("success", False), ("rejected", False)]
    assert deployment.deployer.released == 2


def test_a_turn_bringing_an_own_llm_does_not_count_and_leases_nothing(deployment: Deployment):
    admissions = deployment.admissions()

    for _ in range(2):  # over the limit, were they counted
        admission = admissions.turn(deployment.user, "sora", BroughtKeys(llm=MY_LLM))
        assert admission.exempt
        assert not any(admission.counts(r) for r in ("success", "failed", "rejected", "left"))
        admission.settle("success")

    assert not deployment.counted()
    assert deployment.turns_taken() == 2  # kept for the admin all the same
    assert deployment.records() == [("success", True), ("success", True)]
    assert deployment.deployer.leased == 0


def test_a_turn_settled_twice_is_settled_once(deployment: Deployment):
    admission = deployment.admissions().turn(deployment.user, "sora", BroughtKeys())

    admission.settle("failed")
    admission.settle("success")

    assert not deployment.counted()
    assert deployment.records() == [("failed", False)]
    assert deployment.deployer.released == 1


@pytest.mark.parametrize(
    ("result", "counted"), [("not_connected", False), ("success", True), ("failed", True)]
)
def test_a_call_counts_once_it_connected_and_is_given_back_otherwise(
    deployment: Deployment, result: Result, counted: bool
):
    admission = deployment.admissions().call(deployment.user, "sora", BroughtKeys())

    admission.settle(result, None if result == "not_connected" else 12.5, "hung_up")

    assert deployment.counted("call") is counted
    assert admission.counts(result) is counted
    assert deployment.records() == [(result, False)]
    assert deployment.deployer.released == 1


def test_a_call_over_the_limit_is_refused_recorded_rejected_and_lets_go_of_its_lease(
    deployment: Deployment,
):
    admissions = deployment.admissions()
    admissions.call(deployment.user, "sora", BroughtKeys()).settle("success", 3.0, "hung_up")

    with pytest.raises(OverLimit):
        admissions.call(deployment.user, "sora", BroughtKeys())

    assert deployment.calls_taken() == 1
    assert deployment.records() == [("success", False), ("rejected", False)]
    assert deployment.deployer.released == 2


def test_a_call_without_keys_for_speech_is_unavailable_and_not_recorded(
    deployment: Deployment,
):
    deployment.deployer.keys = DeployerKeys(FakeLLM(), FakeBackgroundLLM())

    with pytest.raises(CallsUnavailable):
        deployment.admissions().call(deployment.user, "sora", BroughtKeys())

    assert deployment.calls_taken() == 0
    assert deployment.records() == []
    assert deployment.deployer.leased == deployment.deployer.released


def test_a_call_on_the_users_own_keys_alone_does_not_count(deployment: Deployment):
    admissions = deployment.admissions()

    for _ in range(2):  # over the limit, were they counted
        admission = admissions.call(deployment.user, "sora", ALL_OWN)
        assert admission.exempt
        assert not any(admission.counts(r) for r in ("success", "failed", "not_connected"))
        admission.settle("success", 3.0, "hung_up")

    assert not deployment.counted("call")
    assert deployment.calls_taken() == 2  # kept for the admin all the same
    assert deployment.records() == [("success", True), ("success", True)]
