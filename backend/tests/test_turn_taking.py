"""The rules for taking turns during a call (GLOSSARY.md「回合」「补充」「打断」「只看文字」),
as `TurnTaking` has them: what `CallTurns` should do next, event by event.

Each case is a call's events, reported as `CallTurns` would, each with what it is told
to do then. Neither Pipecat nor the engine is needed, nor any waiting: how long a
follow-on may take is `CallTurns`'s to time, so here it simply comes to nothing.
"""

from collections.abc import Callable, Sequence

import pytest

from eidolon.turn_taking import (
    ClearVoice,
    Command,
    DropReply,
    DropTurn,
    FlushVoice,
    QueueTurn,
    Reply,
    Spoke,
    StopReply,
    TurnTaking,
    Voice,
    WaitForFollowOn,
)

Event = Callable[[TurnTaking], Sequence[Command]]
Step = tuple[Event, list[Command]]
"""An event, and what `CallTurns` is told to do on it."""


def turn(text: str) -> Event:
    """The next turn is taken up, the user having said `text`."""
    return lambda taking: taking.turn_started(text)


def says(text: str) -> Event:
    """What the user said is transcribed."""
    return lambda taking: taking.user_said(text)


def types(text: str) -> Event:
    """The user sends what they typed."""
    return lambda taking: taking.user_typed(text)


def ja(text: str, segment: int = 0) -> Event:
    """Some of the Japanese of the reply's segment `segment` is shown."""
    return lambda taking: taking.reply_delta("ja", text, segment)


def zh(text: str, segment: int = 0) -> Event:
    """Some of the subtitle of the reply's segment `segment` is shown."""
    return lambda taking: taking.reply_delta("zh", text, segment)


def complete(segment: int) -> Event:
    """The reply's segment `segment` is complete."""
    return lambda taking: taking.segment_complete(segment)


def text_only(on: bool) -> Event:
    """The user switches text only (「只看文字」) on or off."""
    return lambda taking: taking.text_only_switched(on)


TALKS: Event = TurnTaking.user_started_talking
HEARD: Event = TurnTaking.user_heard
COMPLETE: Event = complete(0)
RECORDED: Event = TurnTaking.reply_recorded
ENDED: Event = TurnTaking.reply_ended
DROPPED: Event = TurnTaking.reply_dropped
MISSED: Event = TurnTaking.follow_on_missed
VOICE_STARTS: Event = TurnTaking.voice_started
VOICE_STOPS: Event = TurnTaking.voice_stopped
CALL_ENDING: Event = TurnTaking.call_ending
HUNG_UP_ON: Event = TurnTaking.hung_up_on

REPLYING: list[Step] = [(turn("早上好"), [Reply("早上好", voiced=True, number=1)])]
"""A turn is being replied to, voiced; nothing of the reply is out yet."""
SPEAKING: list[Step] = [*REPLYING, (ja("えっと"), [Voice("えっと", 1, 0)]), (VOICE_STARTS, [])]
"""The character has started speaking the reply; no segment of it is complete yet."""
INTERRUPTIBLE: list[Step] = [*SPEAKING, (zh("哇"), []), (COMPLETE, [FlushVoice(1, 0)])]
"""The character has started speaking the reply, and it has a complete segment."""
RECORDED_AND_HEARD: list[Step] = [
    *REPLYING, (ja("えっと"), [Voice("えっと", 1, 0)]), (zh("哇"), []),
    (COMPLETE, [FlushVoice(1, 0)]), (RECORDED, []), (ENDED, []), (VOICE_STARTS, []),
]
"""The reply is recorded and over, and its voice is still playing."""


def run(
    steps: list[Step], *, starts_text_only: bool = False, spoke: bool = False
) -> TurnTaking:
    """Report each step's event, checking what `CallTurns` is told to do on it; when the
    character spoke (`Spoke`) is only checked if `spoke` says so."""
    taking = TurnTaking(text_only=starts_text_only)
    for number, (event, commands) in enumerate(steps):
        told = list(event(taking))
        if not spoke:
            told = [command for command in told if command != Spoke()]
        assert told == commands, f"step {number}"
    return taking


FOLLOW_ONS = [
    pytest.param(
        [
            *REPLYING,
            (TALKS, [DropReply()]),
            (DROPPED, [WaitForFollowOn()]),
            (says("在吗"), [Reply("早上好\n在吗", voiced=True, number=2)]),
        ],
        id="what is said before she speaks drops the reply and joins the turn on a new line",
    ),
    pytest.param(
        [
            (turn("一"), [Reply("一", voiced=True, number=1)]),
            (TALKS, [DropReply()]),
            (says("二"), []),
            (DROPPED, [Reply("一\n二", voiced=True, number=2)]),
            (types("三"), [DropReply(), ClearVoice()]),
            (DROPPED, [Reply("一\n二\n三", voiced=True, number=3)]),
            (TALKS, [DropReply()]),
            (DROPPED, [WaitForFollowOn()]),
            (says("四"), [Reply("一\n二\n三\n四", voiced=True, number=4)]),
        ],
        id="any number of follow-ons join the turn",
    ),
    pytest.param(
        [*SPEAKING, (TALKS, [DropReply()])],
        id="speaking but with nothing complete yet she is followed on",
    ),
    pytest.param(
        [
            *REPLYING,
            (TALKS, [DropReply()]),
            (DROPPED, [WaitForFollowOn()]),
            (MISSED, [Reply("早上好", voiced=True, number=2)]),
        ],
        id="a follow-on that comes to nothing has the turn replied to again as it was",
    ),
    pytest.param(
        [
            *REPLYING,
            (TALKS, [DropReply()]),
            (DROPPED, [WaitForFollowOn()]),
            (says("  "), [Reply("早上好", voiced=True, number=2)]),
        ],
        id="a follow-on transcribed blank has the turn replied to again as it was",
    ),
    pytest.param(
        [
            *REPLYING,
            (TALKS, [DropReply()]),
            (HEARD, []),
            (DROPPED, [WaitForFollowOn()]),
            (HEARD, [WaitForFollowOn()]),
            (TALKS, [WaitForFollowOn()]),
            (says("在吗"), [Reply("早上好\n在吗", voiced=True, number=2)]),
            (MISSED, []),
            (HEARD, []),
        ],
        id="hearing the user again waits afresh for the follow-on",
    ),
    pytest.param(
        [
            *REPLYING,
            (TALKS, [DropReply()]),
            (DROPPED, [WaitForFollowOn()]),
            (types("在吗"), [Reply("早上好\n在吗", voiced=True, number=2)]),
        ],
        id="what is typed while waiting for a follow-on is the follow-on",
    ),
    pytest.param(
        [
            *REPLYING,
            (TALKS, [DropReply()]),
            (TALKS, [DropReply()]),
            (DROPPED, [WaitForFollowOn()]),
        ],
        id="starting to talk again while the reply is being dropped drops it all the same",
    ),
]


@pytest.mark.parametrize("steps", FOLLOW_ONS)
def test_follow_ons(steps: list[Step]):
    run(steps)


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [(turn("早上好"), [Reply("早上好", voiced=False, number=1)]), (ja("えっと"), []), (TALKS, [DropReply()])],
            id="its first line shown but nothing complete yet",
        ),
        pytest.param(
            [
                (turn("早上好"), [Reply("早上好", voiced=False, number=1)]), (ja("えっと"), []), (zh("哇"), []),
                (COMPLETE, []), (TALKS, [StopReply()]), (says("在吗"), [QueueTurn("在吗")]),
            ],
            id="its first line shown and a segment complete",
        ),
    ],
)
def test_text_only_a_reply_is_spoken_once_its_first_line_is_shown(steps: list[Step]):
    run(steps, starts_text_only=True)


INTERRUPTIONS = [
    pytest.param(
        [
            *INTERRUPTIBLE,
            (TALKS, [StopReply()]),
            (ja("今日"), []),
            (says("在吗"), [QueueTurn("在吗")]),
        ],
        id="what is said stops the reply, which is voiced no further, and is the next turn",
    ),
    pytest.param(
        [*INTERRUPTIBLE, (TALKS, [StopReply()]), (says("  "), [])],
        id="an interruption that comes to nothing takes no turn",
    ),
    pytest.param(
        [
            *REPLYING, (ja("えっと"), [Voice("えっと", 1, 0)]), (zh("哇"), []), (COMPLETE, [FlushVoice(1, 0)]),
            (RECORDED, []),
            (TALKS, [StopReply()]),
            (ENDED, []),
            (says("在吗"), [QueueTurn("在吗")]),
        ],
        id="once the reply is recorded she has spoken",
    ),
    pytest.param(
        [*RECORDED_AND_HEARD, (types("在吗"), [ClearVoice(), QueueTurn("在吗")])],
        id="what is typed while a recorded reply is still heard stops her voice",
    ),
    pytest.param(
        [*RECORDED_AND_HEARD, (TALKS, []), (says("在吗"), [QueueTurn("在吗")])],
        id="what is said between replies is the next turn",
    ),
    pytest.param(
        [
            *INTERRUPTIBLE,
            (types("在吗"), [StopReply(), ClearVoice(), QueueTurn("在吗")]),
            (RECORDED, []),
            (ENDED, []),
            (turn("在吗"), [Reply("在吗", voiced=True, number=2)]),
            (types("还在吗"), [DropReply(), ClearVoice()]),
            (DROPPED, [Reply("在吗\n还在吗", voiced=True, number=3)]),
        ],
        id="of two sent straight after each other the first interrupts, the second follows on",
    ),
]


@pytest.mark.parametrize("steps", INTERRUPTIONS)
def test_interruptions(steps: list[Step]):
    run(steps)


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [
                *REPLYING,
                (ja("えっと"), [Voice("えっと", 1, 0)]),
                (types("在吗"), [DropReply(), ClearVoice()]),
                (DROPPED, [Reply("早上好\n在吗", voiced=True, number=2)]),
                (VOICE_STARTS, []),
                (VOICE_STOPS, []),
                (ja("えっと"), [Voice("えっと", 2, 0)]),
                (zh("哇"), []),
                (COMPLETE, [FlushVoice(2, 0)]),
                (TALKS, [DropReply()]),
            ],
            id="the voice of a dropped reply starting late does not count for the next",
        ),
        pytest.param(
            [
                *REPLYING, (ja("えっと"), [Voice("えっと", 1, 0)]), (zh("哇"), []), (COMPLETE, [FlushVoice(1, 0)]),
                (TALKS, [DropReply()]),
                (VOICE_STARTS, []),
                (DROPPED, [WaitForFollowOn()]),
                (says("在吗"), [Reply("早上好\n在吗", voiced=True, number=2)]),
            ],
            id="the voice of a reply being dropped starting late does not make it spoken",
        ),
        pytest.param(
            [
                *RECORDED_AND_HEARD,
                (turn("在吗"), [Reply("在吗", voiced=True, number=2)]),
                (ja("今日も"), [Voice("今日も", 2, 0)]),
                (zh("今天也"), []),
                (COMPLETE, [FlushVoice(2, 0)]),
                (TALKS, [StopReply()]),
            ],
            id="a reply voiced while the last one is still heard is spoken once it is on its way",
        ),
        pytest.param(
            [
                *RECORDED_AND_HEARD,
                (VOICE_STOPS, []),
                (turn("在吗"), [Reply("在吗", voiced=True, number=2)]),
                (ja("今日も"), [Voice("今日も", 2, 0)]),
                (zh("今天也"), []),
                (COMPLETE, [FlushVoice(2, 0)]),
                (TALKS, [DropReply()]),
            ],
            id="a reply voiced once the last one has been heard waits for her voice to start",
        ),
    ],
)
def test_when_the_character_starts_speaking(steps: list[Step]):
    run(steps)


def test_switching_to_text_only_leaves_the_reply_in_progress_voiced():
    run([
        *REPLYING,
        (text_only(True), []),
        (ja("えっと"), [Voice("えっと", 1, 0)]),
        (RECORDED, []),
        (ENDED, []),
        (turn("在吗"), [Reply("在吗", voiced=False, number=2)]),
        (ja("今日も"), []),
        (text_only(False), []),
        (ja("今日も"), []),
        (RECORDED, []),
        (ENDED, []),
        (turn("还在吗"), [Reply("还在吗", voiced=True, number=3)]),
    ])


def test_each_segment_goes_to_tts_under_its_reply_and_is_voiced_in_full_once_complete():
    run([
        *REPLYING,
        (ja("えっと"), [Voice("えっと", 1, 0)]),
        (ja("、おはよう"), [Voice("、おはよう", 1, 0)]),
        (zh("哇，早上好"), []),
        (complete(0), [FlushVoice(1, 0)]),
        (ja("今日も", 1), [Voice("今日も", 1, 1)]),
        (zh("今天也", 1), []),
        (complete(1), [FlushVoice(1, 1)]),
        (RECORDED, []),
        (ENDED, []),
        (turn("在吗"), [Reply("在吗", voiced=True, number=2)]),
        (ja("うん"), [Voice("うん", 2, 0)]),
    ])


def test_replies_are_numbered_whether_voiced_or_not_and_nothing_unvoiced_is_flushed():
    run([
        *REPLYING,
        (TALKS, [DropReply()]),
        (DROPPED, [WaitForFollowOn()]),
        (text_only(True), []),
        (MISSED, [Reply("早上好", voiced=False, number=2)]),
        (ja("えっと"), []),
        (complete(0), []),
        (RECORDED, []),
        (ENDED, []),
        (text_only(False), []),
        (turn("在吗"), [Reply("在吗", voiced=True, number=3)]),
        (zh("嗯"), []),
        (complete(0), []),  # a segment with no Japanese has nothing to voice
    ])


def test_what_is_left_of_an_interrupted_reply_is_not_voiced():
    run([
        *INTERRUPTIBLE,
        (ja("今日", 1), [Voice("今日", 1, 1)]),
        (TALKS, [StopReply()]),
        (complete(1), []),
    ])


def test_blank_input_is_not_taken_up():
    run([(says("  "), []), (types(""), []), *REPLYING, (types(" "), []), (says(""), [])])


def test_once_the_call_is_ending_nothing_is_taken_up_and_her_last_reply_stays_voiced():
    taking = run([
        *RECORDED_AND_HEARD,
        (CALL_ENDING, []),
        (TALKS, []),
        (says("在吗"), []),
        (types("还在吗"), []),
        (turn("在吗"), []),
    ])

    assert taking.ending


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [*RECORDED_AND_HEARD, (HUNG_UP_ON, [])],
            id="idle, her last reply stays voiced",
        ),
        pytest.param(
            [*INTERRUPTIBLE, (HUNG_UP_ON, [StopReply()]), (ja("今日", 1), []), (complete(1), [])],
            id="a reply she has started speaking stops, voiced no further",
        ),
        pytest.param(
            [*SPEAKING, (HUNG_UP_ON, [DropTurn()]), (DROPPED, [])],
            id="one with nothing complete yet is dropped, turn and all",
        ),
        pytest.param(
            [*REPLYING, (TALKS, [DropReply()]), (DROPPED, [WaitForFollowOn()]),
             (HUNG_UP_ON, [DropTurn()]), (MISSED, [])],
            id="so is a turn waiting for a follow-on",
        ),
    ],
)
def test_hung_up_on_from_outside_the_call_nothing_more_is_taken_up(steps: list[Step]):
    taking = run([
        *steps,
        (HUNG_UP_ON, []),
        (TALKS, []),
        (says("在吗"), []),
        (types("还在吗"), []),
        (turn("在吗"), []),
    ])

    assert taking.ending


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [
                (turn("早上好"), [Reply("早上好", voiced=True, number=1)]),
                (VOICE_STARTS, []),
                (VOICE_STOPS, []),
                (ja("えっと"), [Voice("えっと", 1, 0)]),
                (VOICE_STARTS, [Spoke()]),
                (VOICE_STOPS, []),
                (VOICE_STARTS, []),
            ],
            id="once some of the reply has gone to TTS, as her voice starts, only once",
        ),
        pytest.param(
            [
                (turn("早上好"), [Reply("早上好", voiced=True, number=1)]),
                (ja("えっと"), [Voice("えっと", 1, 0)]),
                (VOICE_STARTS, [Spoke()]),
                (RECORDED, []),
                (ENDED, []),
                (turn("在吗"), [Reply("在吗", voiced=True, number=2)]),
                (ja("今日も"), [Voice("今日も", 2, 0), Spoke()]),
                (ja("、"), [Voice("、", 2, 0)]),
            ],
            id="as its first words go to TTS while the last reply's voice is still playing",
        ),
        pytest.param(
            [
                (text_only(True), []),
                (turn("早上好"), [Reply("早上好", voiced=False, number=1)]),
                (ja("えっと"), [Spoke()]),
                (zh("哇"), []),
                (VOICE_STARTS, []),
            ],
            id="as the first line of a reply only shown appears",
        ),
        pytest.param(
            [
                (turn("早上好"), [Reply("早上好", voiced=True, number=1)]),
                (ja("えっと"), [Voice("えっと", 1, 0)]),
                (zh("哇"), []),
                (COMPLETE, [FlushVoice(1, 0)]),
                (RECORDED, []),
                (ENDED, []),
                (VOICE_STARTS, [Spoke()]),
            ],
            id="not as the reply is recorded, but as its voice starts afterwards",
        ),
        pytest.param(
            [
                (turn("早上好"), [Reply("早上好", voiced=True, number=1)]),
                (ja("えっと"), [Voice("えっと", 1, 0)]),
                (VOICE_STARTS, [Spoke()]),
                (TALKS, [DropReply()]),
                (DROPPED, [WaitForFollowOn()]),
                (VOICE_STOPS, []),
                (says("在吗"), [Reply("早上好\n在吗", voiced=True, number=2)]),
                (VOICE_STARTS, []),  # the dropped reply's, starting late
                (VOICE_STOPS, []),
                (ja("えっと"), [Voice("えっと", 2, 0)]),
                (VOICE_STARTS, [Spoke()]),
            ],
            id="once for each reply, a reply given afresh after a follow-on again",
        ),
    ],
)
def test_the_character_is_said_to_have_spoken_each_reply_as_she_starts_speaking_it(
    steps: list[Step],
):
    run(steps, spoke=True)
