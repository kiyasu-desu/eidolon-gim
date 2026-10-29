"""What each document is embedded with besides its text: where it comes from, which
Gemini is told as its title (Qwen is not)."""

from pathlib import Path

from eidolon.characters import Character, parse_facts
from eidolon.corpus import Episode, Line, StoryCorpus
from eidolon.facts import CharacterFacts
from tests.fakes import FakeEmbedder

PARK = Episode(
    "produce_events/100100101", "培育剧情", "練習編", "公園の歌声", frozenset({"sora"}),
    (Line("ソラ", "えっと……"),),
)


async def test_a_passage_is_titled_with_its_card_or_event_and_episode(tmp_path: Path):
    embedder = FakeEmbedder()
    corpus = StoryCorpus(tmp_path / "eidolon.db", embedder)

    await corpus.save([PARK])
    corpus.close()

    assert embedder.titles == ["練習編「公園の歌声」"]


async def test_a_fact_is_titled_with_its_headings(tmp_path: Path):
    embedder = FakeEmbedder()
    sora = Character(
        "sora", "星野ソラ", "", "voice", "sheet", None, "#ffbad6",
        facts=parse_facts("喜欢鸟。\n# 人物关系\n## 雨宮ナギ\n同组合的伙伴。"),
    )
    facts = CharacterFacts(tmp_path / "eidolon.db", embedder, [sora])

    assert await facts.embed_missing() == 2
    facts.close()

    assert embedder.titles == [None, "人物关系 / 雨宮ナギ"]
