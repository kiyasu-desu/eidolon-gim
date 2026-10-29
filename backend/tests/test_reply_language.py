"""Language checks at the point where dialogue becomes visible and audible."""

import pytest

from eidolon.llm import LLMError
from eidolon.reply_format import PhotoTagged, Segment, SegmentComplete, SegmentDelta, SpeechDelta
from eidolon.reply_language import JapaneseReply, contains_chinese, history_reply, rewrite_japanese
from tests.fakes import FakeLLM


def test_chinese_detection_does_not_confuse_shared_kanji_names_or_cues_with_chinese():
    for line in (
        "[shyly] えっ……那个，テン，听到这话，脸就有点热……",
        "[gently] 那……テン，明天也會，好好去的……",
        "えっと……睡不着了……",
    ):
        assert contains_chinese(line), line
    for line in (
        "[embarrassed] テン、明日も頑張る……",
        "<whisper>会いたい</whisper>、没頭してた……着替えるね。",
        "架空テン", "了解", "一", "練習", "謝謝祭", "東京都千代田区",
    ):
        assert not contains_chinese(line), line


async def test_bad_dialogue_is_held_then_rewritten_before_display_speech_or_persistence():
    llm = FakeLLM(["<ja>[shyly] あの……テン、聞いて顔が熱くなった……</ja>"])
    parser = JapaneseReply(lambda line: rewrite_japanese(llm, line))

    assert [e async for e in parser.feed("<photo>garden</photo><ja>[shyly] えっ……")] == [
        PhotoTagged("garden")
    ]
    assert [e async for e in parser.feed("那个，テン，听到这话，脸就有点热……</ja>")] == []
    events = [e async for e in parser.feed("<zh>听到这话，テン脸有点热。</zh>")]

    assert parser.complete == [Segment(
        "[shyly] あの……テン、聞いて顔が熱くなった……", "听到这话，テン脸有点热。"
    )]
    shown = "".join(e.text for e in events if isinstance(e, SegmentDelta) and e.lang == "ja")
    spoken = "".join(e.text for e in events if isinstance(e, SpeechDelta))
    assert shown == "あの……テン、聞いて顔が熱くなった……"
    assert spoken == "[shyly]あの……テン、聞いて顔が熱くなった……"
    assert events[-1] == SegmentComplete(0)

    assert [e async for e in parser.feed("<ja>うん……")] == []
    final = [e async for e in parser.feed("またね。</ja><zh>再见。</zh>")]
    assert final == [
        SegmentDelta(1, "ja", "うん……"), SpeechDelta(1, "うん……"),
        SegmentDelta(1, "ja", "またね。"), SpeechDelta(1, "またね。"),
        SegmentDelta(1, "zh", "再见。"), SegmentComplete(1),
    ]
    assert len(llm.prompts) == 1  # normal Japanese does not cause another model call


async def test_missing_japanese_is_rewritten_and_correction_failures_never_escape():
    llm = FakeLLM(["Here is your Japanese translation."], ["<ja>こんにちは。</ja>"])
    parser = JapaneseReply(lambda line: rewrite_japanese(llm, line))
    events = [e async for e in parser.feed("<ja>  </ja><zh>你好。</zh>")]
    assert parser.complete == [Segment("こんにちは。", "你好。")]
    assert any(isinstance(e, SpeechDelta) and e.text == "こんにちは。" for e in events)
    assert len(llm.prompts) == 2

    failing = FakeLLM(["<ja>那个，你好</ja>"], ["<ja>还是中文</ja>"])
    rejected = JapaneseReply(lambda line: rewrite_japanese(failing, line))
    with pytest.raises(LLMError):
        _ = [e async for e in rejected.feed("<ja>你好</ja><zh>你好</zh>")]
    assert rejected.complete == []
    assert len(failing.prompts) == 2


def test_legacy_errors_become_semantic_notes_without_mutating_the_record_or_losing_photos():
    segments = [Segment("えっ……", "诶……"), Segment("那个，明天也会去", "那个，明天也会去")]
    note = history_reply(segments, "garden", photo_failed=True)
    assert note.role == "system"
    assert "明天也会去" in note.content
    assert "<ja>" not in note.content
    assert '"photo": "garden"' in note.content
    assert '"photo_failed": true' in note.content
    assert segments[1].ja == "那个，明天也会去"
    normal = history_reply([Segment("[shyly] えっ……", "诶……")])
    assert normal.role == "assistant"
    assert normal.content == "<ja>[shyly] えっ……</ja><zh>诶……</zh>"
