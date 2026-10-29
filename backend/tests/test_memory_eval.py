"""`eidolon eval memory`: the memory eval set's cases run through the memories module as
turns would, each on a scratch database with the memories it starts with written down
through the module. Extraction cases are judged by what the turn wrote down, three runs
each, the majority deciding; recall cases by which memories the turn found, with the
judge model's verdict alongside. The passes are summed up by category."""

import json
from pathlib import Path
from typing import Any, get_args

import pytest

from eidolon.characters import Character, load_characters
from eidolon.judge import JudgeError, JudgeThresholds
from eidolon.llm import LLMError
from eidolon.memory_eval import (
    Category,
    MemoryEvalError,
    MemoryServices,
    check_extraction,
    evaluate,
    load_memory_eval,
    report,
    summarize,
)
from eidolon.rerank import RerankThresholds
from tests.conftest import Admin, CharacterConfig
from tests.fakes import FakeBackgroundLLM, FakeEmbedder, FakeReranker
from tests.test_rerank_eval import ClosableEmbedder, ClosableReranker
from tests.test_shared_memory import memorized

REPO = Path(__file__).parents[2]
HALF = JudgeThresholds(
    needs_retrieval=0.5, recall=0.5, about_producer=0.5, emotion=0.5, out_of_line=0.5,
    manipulation=0.5, photo=0.5,
)
THRESHOLDS = RerankThresholds(references=0.5, memories=0.6)
MODELS = {"background": "fake-llm", "judge": "fake-judge", "embedding": "fake-embedding",
          "rerank": "fake-reranker"}

EVAL = """
[[extraction]]
id = "moved"
category = "supersede"
character = "sora"
memories = [
  { key = "osaka", source = "riku", text = "制作人住在大阪" },
  { key = "cat", source = "sora", text = "制作人养了一只叫小白的猫" },
]
history = [{ user = "最近好忙" }, { ja = "[softly]おつかれさまです", zh = "辛苦了" }]
said = "我上个月搬到东京了"
reply = { ja = "えっと、東京に！", zh = "哇，搬到东京了！" }
must = [["东京", "東京"], "搬"]
must_not = ["很累"]
keeps = ["cat"]

[[extraction]]
id = "tired"
category = "transient"
character = "riku"
said = "今天好累啊"
reply = { ja = "おつかれさまばい", zh = "辛苦啦" }
nothing = true

[[extraction]]
id = "osaka-superseded"
category = "supersede"
character = "sora"
memories = [{ key = "osaka", source = "riku", text = "制作人住在大阪" }]
said = "我搬到东京了"
reply = { ja = "東京ですか！", zh = "东京吗！" }
must = ["东京"]
supersedes = ["osaka"]

[[recall]]
id = "it-cat"
category = "pronoun"
character = "sora"
memories = [
  { key = "cat", source = "sora", text = "制作人养了一只叫小白的猫" },
  { key = "dog", source = "riku", text = "制作人老家养了一只柴犬" },
]
history = [{ user = "回来了" }, { ja = "[happily]猫ちゃん、元気ですか？", zh = "猫咪还好吗？" }]
said = "它昨晚又叫了一夜"
found = ["cat"]
not_found = ["dog"]

[[recall]]
id = "it-cat-unjudged"
category = "pronoun"
character = "sora"
memories = [{ key = "cat", source = "sora", text = "制作人养了一只叫小白的猫" }]
history = [{ ja = "猫ちゃん、元気ですか？", zh = "猫咪还好吗？" }]
said = "它又叫了"
found = ["cat"]

[[recall]]
id = "back-home"
category = "continuity"
character = "riku"
memories = [{ key = "interview", source = "sora", text = "制作人10月8日下午有一场面试" }]
said = "我回来了"
found = ["interview"]
"""


class FakeRetrievalJudge:
    """The judge model, answering what each turn needs by what the user just said: their
    own life for the cat, nothing for the cat unjudged, and failing otherwise."""

    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []

    async def ask(self, state: dict[str, Any], questions: dict[str, dict]) -> dict[str, Any]:
        self.states.append(state)
        about = {"它昨晚又叫了一夜": 0.9, "它又叫了": 0.1}.get(state["制作人最新的一句话"])
        if about is None:
            raise JudgeError("Workers AI 返回 500")
        return {
            "needs_retrieval": {"noul": 0.1}, "recall": {"noul": 0.05},
            "about_producer": {"noul": about},
        }

    async def aclose(self) -> None:
        pass


@pytest.fixture
def config(characters: CharacterConfig) -> dict[str, Character]:
    return load_characters(characters.path)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "memory.toml"
    path.write_text(text, encoding="utf-8")
    return path


def services(background: FakeBackgroundLLM, judge: FakeRetrievalJudge) -> MemoryServices:
    return MemoryServices(
        background_llm=background,
        embedder=FakeEmbedder(),
        reranker=FakeReranker("猫"),
        rerank_thresholds=THRESHOLDS,
        judge_model=judge,
        judge_thresholds=HALF,
    )


async def test_a_run_goes_through_the_memories_module_and_is_summed_up_by_category(
    tmp_path: Path, config: dict[str, Character]
):
    memory_eval = load_memory_eval(write(tmp_path, EVAL), config)
    background = FakeBackgroundLLM(
        # moved: right, then writing down the passing state too, then right again
        memorized("制作人从大阪搬到了东京"),
        memorized("制作人搬到了东京，今天很累"),
        memorized("制作人搬到东京了"),
        # tired: the model fails, then rightly writes nothing, then writes the state down
        LLMError("背景模型返回 502"),
        FakeBackgroundLLM.NOTHING,
        memorized("制作人今天很累"),
        # osaka-superseded: right but for not saying it supersedes Osaka
        *[memorized("制作人搬到了东京")] * 3,
    )
    judge = FakeRetrievalJudge()

    results = await evaluate(memory_eval, config, services(background, judge), tmp_path / "work")

    # The memories a case starts with are written down through the module, then the turn
    # is taken as a conversation takes it.
    first = background.prompts[0][-1].content
    assert "制作人住在大阪" in first and "制作人养了一只叫小白的猫" in first
    assert "制作人：最近好忙" in first and "星野ソラ：辛苦了" in first
    assert "我上个月搬到东京了" in first and "哇，搬到东京了！" in first
    # Each run starts afresh, not with what the run before wrote down.
    assert "制作人从大阪搬到了东京" not in background.prompts[1][-1].content
    assert len(background.prompts) == 9

    moved, tired, superseded = results.extraction
    assert [r.passed for r in moved.runs] == [True, False, True] and moved.passed
    assert moved.runs[0].written == ("制作人从大阪搬到了东京",)
    assert moved.runs[1].problems == ("写下了「很累」",)
    assert [r.passed for r in tired.runs] == [False, True, False] and not tired.passed
    assert tired.runs[0].error is not None and "502" in tired.runs[0].error
    assert tired.runs[2].problems == ("不该写下任何记忆",)
    assert not superseded.passed
    assert superseded.runs[0].problems == ("osaka 没有被取代",)

    # Recall cases are judged as a conversation judges them, the previous reply among
    # what came before, and found through the memories.
    assert judge.states[0]["上文"] == ["制作人：回来了", "星野ソラ：猫ちゃん、元気ですか？"]
    cat, unjudged, back_home = results.recall
    assert cat.passed and cat.found == ("cat",) and cat.judged.need == "memories"
    assert cat.judged.answer is not None and cat.judged.answer.about_producer == 0.9
    assert not unjudged.passed and unjudged.found == () and unjudged.judged.need == "nothing"
    assert unjudged.problems == ("没有想起 cat",)
    # A judge model failing, the turn looks memories up all the same.
    assert back_home.judged.error is not None and "500" in back_home.judged.error
    assert not back_home.passed

    summary = summarize(results, MODELS)
    categories = summary["categories"]
    assert categories["supersede"]["extraction"] == {"cases": 2, "passed": 1}
    assert categories["supersede"]["recall"] == {"cases": 0, "passed": 0}
    assert categories["supersede"]["failed"] == ["osaka-superseded"]
    assert categories["transient"]["extraction"] == {"cases": 1, "passed": 0}
    assert categories["pronoun"]["recall"] == {"cases": 2, "passed": 1}
    assert categories["pronoun"]["passed"] == 1 and categories["pronoun"]["cases"] == 2
    assert categories["continuity"]["recall"] == {"cases": 1, "passed": 0}
    assert categories["duplicate"]["cases"] == 0
    assert summary["total"] == {"cases": 6, "passed": 2}
    assert summary["runs"] == 3 and summary["models"] == MODELS

    text = report(results, summary)
    assert "取代" in text and "代词" in text and "前情" in text
    assert "osaka 没有被取代" in text and "没有想起 cat" in text
    assert "it-cat-unjudged" in text and "nothing" in text and "500" in text

    dumped = json.loads(json.dumps(results.to_json(summary), ensure_ascii=False))
    assert dumped["summary"]["total"] == {"cases": 6, "passed": 2}
    [moved_json] = [c for c in dumped["extraction"] if c["id"] == "moved"]
    assert moved_json["passed"] is True and moved_json["category"] == "supersede"
    assert [r["passed"] for r in moved_json["runs"]] == [True, False, True]
    assert moved_json["runs"][1]["written"] == ["制作人搬到了东京，今天很累"]
    [cat_json] = [c for c in dumped["recall"] if c["id"] == "it-cat"]
    assert cat_json["found"] == ["cat"] and cat_json["judge"]["need"] == "memories"
    assert cat_json["judge"]["probabilities"]["about_producer"] == 0.9


SUPERSEDED = """
[[recall]]
id = "kitten-named"
category = "supersede"
character = "sora"
memories = [
  { key = "kitten", source = "sora", text = "制作人养了一只小猫", superseded_by = "shiro" },
  { key = "shiro", source = "riku", text = "制作人养了一只叫小白的猫" },
]
history = [{ ja = "猫ちゃん、元気ですか？", zh = "猫咪还好吗？" }]
said = "它昨晚又叫了一夜"
found = ["shiro"]
not_found = ["kitten"]
"""


async def test_a_starting_memory_superseded_is_so_before_the_turn(
    tmp_path: Path, config: dict[str, Character]
):
    """Written down through the module, by a turn saying what it supersedes."""
    memory_eval = load_memory_eval(write(tmp_path, SUPERSEDED), config)

    results = await evaluate(
        memory_eval, config, services(FakeBackgroundLLM(), FakeRetrievalJudge()),
        tmp_path / "work",
    )

    [named] = results.recall
    assert named.found == ("shiro",) and named.passed


async def test_memories_found_but_not_told_apart_stop_the_run(
    tmp_path: Path, config: dict[str, Character], monkeypatch: pytest.MonkeyPatch
):
    """Rather than every recall case failing as having found nothing."""
    monkeypatch.setattr(
        "eidolon.memory._memories_prompt",
        lambda memories, character, timezone, opening: "\n".join(f"* {m.text}" for m in memories),
    )
    recall_only = EVAL[EVAL.index("[[recall]]"):]
    memory_eval = load_memory_eval(write(tmp_path, recall_only), config)

    with pytest.raises(MemoryEvalError, match="_found"):
        await evaluate(
            memory_eval, config, services(FakeBackgroundLLM(), FakeRetrievalJudge()),
            tmp_path / "work",
        )


def test_an_extraction_is_judged_by_its_keywords_and_what_it_supersedes(
    tmp_path: Path, config: dict[str, Character]
):
    moved = load_memory_eval(write(tmp_path, EVAL), config).extraction[0]

    assert check_extraction(moved, ["制作人从大阪搬到了東京"], set()) == []
    # Every group must be in some memory, any of its keywords will do.
    assert check_extraction(moved, ["制作人住在东京"], set()) == ["没有写下「搬」"]
    # What it keeps must not be superseded; what it supersedes must be (were it asked to).
    assert check_extraction(moved, ["制作人搬到了东京"], {"cat"}) == ["cat 被取代了"]
    superseding = load_memory_eval(write(tmp_path, EVAL), config).extraction[2]
    assert check_extraction(superseding, ["制作人搬到了东京"], {"osaka"}) == []


CASE = """
[[recall]]
id = "a"
category = "pronoun"
character = "sora"
memories = [{ key = "cat", source = "sora", text = "制作人养了猫" }]
history = [{ ja = "猫ちゃん", zh = "猫咪" }]
said = "它叫了"
found = ["cat"]
"""

EXTRACTION = """
[[extraction]]
id = "b"
category = "transient"
character = "sora"
said = "好累"
reply = { ja = "おつかれさまです", zh = "辛苦了" }
nothing = true
"""


@pytest.mark.parametrize(
    "text, error",
    [
        (CASE + CASE, "用例 a 重复"),
        (CASE.replace('category = "pronoun"', 'category = "trivia"'), "category"),
        (CASE.replace('character = "sora"', 'character = "rin"'), "rin"),
        (CASE.replace('found = ["cat"]', 'found = ["dog"]'), "dog"),
        (CASE.replace('found = ["cat"]', 'not_found = ["cat"]\nfound = ["cat"]'), "cat"),
        (CASE.replace('found = ["cat"]', ""), "found"),
        (CASE.replace('said = "它叫了"\n', ""), "said"),
        (CASE.replace('source = "sora"', 'source = "rin"'), "rin"),
        (CASE.replace(', text = "制作人养了猫"', ""), "text"),
        (CASE.replace('[{ key = "cat", source = "sora", text = "制作人养了猫" }]',
                      '[{ key = "cat", source = "sora", text = "制作人养了猫" },'
                      ' { key = "cat", source = "sora", text = "制作人养了狗" }]'), "cat"),
        (CASE.replace('[{ key = "cat", source = "sora", text = "制作人养了猫" }]',
                      '[{ key = "cat", source = "sora", text = "制作人养了猫" },'
                      ' { key = "kitty", source = "sora", text = "制作人养了猫" }]'), "制作人养了猫"),
        (CASE.replace('text = "制作人养了猫" }', 'text = "制作人养了猫", superseded_by = "dog" }'),
         "dog"),
        # What supersedes a memory is written down after it.
        (CASE.replace('[{ key = "cat", source = "sora", text = "制作人养了猫" }]',
                      '[{ key = "kitten", source = "sora", text = "制作人养了小猫" },'
                      ' { key = "cat", source = "sora", text = "制作人养了猫",'
                      ' superseded_by = "kitten" }]'), "kitten"),
        # Recall is looked up after the character's previous reply.
        (CASE.replace('history = [{ ja = "猫ちゃん", zh = "猫咪" }]', 'history = [{ user = "嗯" }]'),
         "上一条回复"),
        (CASE.replace('history = [{ ja = "猫ちゃん", zh = "猫咪" }]', ""), "上一条回复"),
        (CASE.replace('{ ja = "猫ちゃん", zh = "猫咪" }', '{ boss = "x" }'), "history"),
        (EXTRACTION.replace('reply = { ja = "おつかれさまです", zh = "辛苦了" }\n', ""), "reply"),
        (EXTRACTION.replace("nothing = true", ""), "检查"),
        (EXTRACTION.replace("nothing = true", 'nothing = true\nmust = ["累"]'), "nothing"),
        (EXTRACTION.replace("nothing = true", 'nothing = true\nmust_nto = ["累"]'), "must_nto"),
        (CASE.replace('text = "制作人养了猫" }', 'text = "制作人养了猫", source_character = "sora" }'),
         "source_character"),
        (EXTRACTION.replace("nothing = true", "must = [[]]"), "must"),
        ("[[recall", "格式"),
    ],
)
def test_a_malformed_set_is_refused(
    tmp_path: Path, config: dict[str, Character], text: str, error: str
):
    with pytest.raises(MemoryEvalError, match=error):
        load_memory_eval(write(tmp_path, text), config)


def test_a_continuity_case_may_begin_the_conversation(
    tmp_path: Path, config: dict[str, Character]
):
    text = CASE.replace('category = "pronoun"', 'category = "continuity"').replace(
        'history = [{ ja = "猫ちゃん", zh = "猫咪" }]', ""
    )

    [case] = load_memory_eval(write(tmp_path, text), config).recall

    assert case.history == ()


def test_the_committed_set_covers_every_category():
    characters = load_characters(REPO / "characters" / "gim" / "characters.toml")
    memory_eval = load_memory_eval(REPO / "backend" / "eval" / "memory.toml", characters)

    cases = [*memory_eval.extraction, *memory_eval.recall]
    for category in get_args(Category):
        assert sum(c.category == category for c in cases) >= 5, category
    # The previous reply talks of the cat, the user of 「它」.
    assert any(
        c.category == "pronoun" and c.said.startswith("它")
        and any("猫" in (m.zh or "") for m in c.history if m.role == "character")
        for c in memory_eval.recall
    )
    assert sum(c.category == "proper-noun" for c in memory_eval.recall) >= 5


@pytest.mark.parametrize(
    "unset, missing",
    [
        ("CHAT_LLM_API_KEY", "CHAT_LLM_API_KEY"),
        ("SILICONFLOW_API_KEY", "SILICONFLOW_API_KEY"),
        ("JEV_API_KEY", "JEV_API_KEY"),
    ],
)
def test_the_command_needs_the_services_memory_runs_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    unset: str, missing: str,
):
    deployed(monkeypatch)
    monkeypatch.delenv(unset)
    admin = Admin(tmp_path / "eidolon.db", capsys)

    err = admin.fails(
        "eval", "memory", "--file", str(REPO / "backend" / "eval" / "memory.toml"),
        "--characters", str(REPO / "characters" / "gim" / "characters.toml"),
    )

    assert missing in err and "记忆评测" in err


def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment of a deployment with memory on: the chat model writing down
    memories, SiliconFlow embedding and reranking, and Jev judging."""
    for name in ("BACKGROUND_LLM_BASE_URL", "BACKGROUND_LLM_API_KEY", "BACKGROUND_LLM_MODEL",
                 "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "RERANK_MODEL", "JUDGE_PROVIDER",
                 "JEV_MODEL", "RERANK_MEMORY_MIN_RELEVANCE", "RERANK_MIN_RELEVANCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test")
    monkeypatch.setenv("JEV_API_KEY", "jev-key")


def test_the_command_runs_the_set_on_the_deployers_services(
    tmp_path: Path, characters: CharacterConfig, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    deployed(monkeypatch)
    background = FakeBackgroundLLM(*[memorized("制作人搬到了东京")] * 3)
    monkeypatch.setattr("eidolon.llm.providers.open_llm", lambda settings: background)
    monkeypatch.setattr("eidolon.embedding.open_embedder", lambda *_: ClosableEmbedder())
    monkeypatch.setattr(
        "eidolon.rerank.SiliconFlowReranker", lambda *_: ClosableReranker({"猫": 0.9})
    )
    monkeypatch.setattr("eidolon.judge.open_judge", lambda *_: FakeRetrievalJudge())
    cases = write(tmp_path, EVAL.split("[[extraction]]\nid = \"tired\"")[0] + CASE)
    results = tmp_path / "baseline.json"
    admin = Admin(tmp_path / "eidolon.db", capsys)

    out = admin.run(
        "eval", "memory", "--file", str(cases), "--characters", str(characters.path),
        "--json", str(results),
    )

    assert "背景模型：deepseek-chat" in out and "取代" in out
    dumped = json.loads(results.read_text(encoding="utf-8"))
    assert dumped["summary"]["total"] == {"cases": 2, "passed": 2}
    assert dumped["summary"]["models"]["background"] == "deepseek-chat"
    # Nothing is left behind of the scratch databases, nor written to the deployment's.
    assert not (tmp_path / "eidolon.db").exists()
