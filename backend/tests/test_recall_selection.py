"""Replay the real spoken recall ranking with synthetic story content only."""

from pathlib import Path
import threading
from unittest.mock import Mock, patch

import pytest

from eidolon.characters import Character
from eidolon.corpus import Episode, ImportFormat, Line, StoryCorpus
from eidolon.references import Reference
from eidolon.retrieval import ReferenceSources, Retrieval, RetrievalJudge
from tests.fakes import FakeEmbedder, KeywordReranker


SPOKEN = (
    "还记得那次在公园练歌，被当成唱歌幽灵，我四处道歉那次吗？\n"
    "后来演出前，你说了些关于自己什么的话。\n还记得的话，具体说说。"
)
CONTINUOUS = (
    "还记得那次在公园练歌，被当成唱歌幽灵，我四处道歉那次吗？"
    "后来演出前你说了些关于自己什么的话？还记得的话具体说说。"
)
# Captured from voice-rag-acceptance/retrieval.jsonl, first recall-selection.
# Keep the scores/order, never the private transcripts.
SCORES = (0.051204610615968704, 0.043188534677028656,
          0.03726555034518242, 0.03164442256093025)
DETAIL = "演出前确认了客席观众，也谈到歌曲与本人印象的反差。"
CHARACTER = Character("test", "测试角色", "", "", "", None, "#ffffff")


async def recalled(
    tmp_path: Path, query: str,
    formats: tuple[ImportFormat, ...], scores: tuple[float, ...] = SCORES,
) -> str:
    embedder = FakeEmbedder()
    corpus = StoryCorpus(tmp_path / "story.db", embedder)
    episodes = [
        Episode(
            f"synthetic-{i}", "测试", f"source-{i}", f"episode-{i}",
            frozenset({CHARACTER.id}),
            (Line("测试角色", DETAIL if i == 3 else f"条件情境・未确认实际触发：synthetic-{i}"),),
            format,
        )
        for i, format in enumerate(formats)
    ]
    try:
        await corpus.save(episodes)
        sources = ReferenceSources(embedder, [], corpus, None)
        retrieval = Retrieval(
            Mock(spec=RetrievalJudge), sources,
            KeywordReranker({e.id: score for e, score in zip(episodes, scores, strict=True)}),
            lambda: 0.02,
        )
        story = [Reference("episode", e.id, e.id, 0.5) for e in episodes]

        metadata_threads: set[int] = set()
        imported_from = corpus.imported_from

        def observed_format(episode_id: str) -> ImportFormat | None:
            metadata_threads.add(threading.get_ident())
            return imported_from(episode_id)

        with patch.object(corpus, "imported_from", side_effect=observed_format):
            prompt = await retrieval._recall(CHARACTER, query, query, story, [])
        assert threading.get_ident() not in metadata_threads, "metadata reads blocked the event loop"
        return prompt
    finally:
        corpus.close()


async def test_spoken_recall_keeps_a_relevant_confirmed_episode(tmp_path: Path):
    for label, query in [("asr-merged", SPOKEN), ("continuous", CONTINUOUS)]:
        prompt = await recalled(
            tmp_path, query, ("gim-conditional-csv",) * 3 + ("gim-csv",),
        )
        assert DETAIL in prompt, label
        assert prompt.count("\n## ") == 3, label
        assert prompt.index("/「episode-0」") < prompt.index("/「episode-1」") < prompt.index("/「episode-3」"), label
        assert "/「episode-2」" not in prompt, label
        assert "条件情境・未确认实际触发" in prompt, label
        assert "条件反应资料，不是已经确认的正式经历" in prompt, label


@pytest.mark.parametrize("formats,scores", [
    (("gim-conditional-csv",) * 4, SCORES),
    (("gim-csv",) * 4, SCORES),
    (("gim-csv",) + ("gim-conditional-csv",) * 2 + ("gim-csv",), SCORES),
    (("gim-conditional-csv",) * 3 + ("gim-csv",), SCORES[:3] + (0.019,)),
], ids=["conditional-only", "confirmed-only",
        "canon-already-selected", "canon-under-threshold"])
async def test_other_recalls_keep_the_top_three(
    tmp_path: Path, formats: tuple[ImportFormat, ...], scores: tuple[float, ...],
):
    confirmed_formats: tuple[ImportFormat, ...] = ("csv", "json", "gim-csv")
    variants: list[tuple[ImportFormat, ...]] = [formats]
    if formats == ("gim-csv",) * 4:
        variants = [(format, format, format, format) for format in confirmed_formats]
    for variant in variants:
        prompt = await recalled(tmp_path, SPOKEN, variant, scores)
        assert prompt.count("\n## ") == 3, variant
        assert all(f"/「episode-{i}」" in prompt for i in range(3)), variant
        assert DETAIL not in prompt, variant


async def test_a_fabricated_event_below_threshold_recalls_nothing(tmp_path: Path):
    prompt = await recalled(
        tmp_path, "那次一起驾驶飞船去月球演出呢？",
        ("gim-conditional-csv",) * 3 + ("gim-csv",), (0.0003,) * 4,
    )

    assert "没有想起" in prompt
    assert "\n## " not in prompt
    assert DETAIL not in prompt
