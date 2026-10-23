"""Original scripts: exercise ADV control flow, not copyrighted game dialogue."""

import csv
import json
from pathlib import Path

import pytest

from eidolon.characters import load_characters
from eidolon.corpus import StoryCorpus
from eidolon.gim_adv import AdvParseError, AdvProjectionError, ConditionResolution, parse_adv
from eidolon.gim_story_import import import_gim_directory
from tests.fakes import FakeEmbedder


SOURCE = "adv_original_branches.txt"
CHOICES = """[choicegroup choices=[choice text=Rest here] choices=[choice text=Walk on]]
[branchgroup type=Choice groupLength=2]
[branch groupLength=2]
[message name={user} text=Let us rest]
[message name=手毬 text=The shade is cool]
[branch]
[message name=手毬 text=We return together]
"""


def test_empty_branch_does_not_capture_shared_tail_and_ids_are_physical():
    script = parse_adv("\n" + CHOICES, SOURCE)
    assert script.nodes[-1].line == 8
    assert script.nodes[1].children[1].children == []
    assert script.nodes[1].children[0].option_text == "Rest here"
    rows = script.csv_rows()
    assert rows[-1][2] == "We return together"
    assert rows[-2][1] == "手毬"
    assert "互斥分支・未确认选择" in rows[-2][2]
    assert "Rest here" in rows[-2][2]
    assert SOURCE + ":L3/Choice#1" in rows[-2][2]
    assert not any("Let us rest" in row[2] for row in rows)
    assert script.to_dict() == json.loads(json.dumps(script.to_dict()))


def test_nested_condition_consumes_nodes_not_lines_and_rejects_projection():
    script = parse_adv("""[choicegroup choices=[choice text=Stay]]
[branchgroup type=Choice groupLength=1]
[branch groupLength=2]
[branchgroup type=Condition groupLength=2]
[branch groupLength=1]
[message name=手毬 text=First alternative]
[branch groupLength=1]
[message name=手毬 text=Other alternative]
[message name=手毬 text=Still within the choice]
[message name=手毬 text=Shared ending]
""", SOURCE)
    choice = script.nodes[1].children[0]
    assert len(choice.children) == 2
    condition = choice.children[0]
    assert condition.to_dict()["predicate"] is None
    assert condition.to_dict()["predicate_status"] == "unknown"
    assert condition.children[1].branch_index == 2
    with pytest.raises(AdvProjectionError, match="unknown runtime predicate"):
        script.csv_rows()
    assert script.csv_rows(common_only=True)[-1][2] == "Shared ending"
    assert len(script.csv_rows(common_only=True)) == 4  # header, info, select, shared


def test_multiple_choices_inner_narration_and_complete_spaced_controls():
    text = r'''[choicegroup choices=[choice text="A quiet rest"]]
[branchgroup type=Choice groupLength=1]
[branch groupLength=4]
[message name=制作人 text=Discard me]
[message name=プロデューサー text=Discard me too]
[message name=手毬 text=The  <r\=かぜ>wind</r> is <em\=>cool</em> isInner=true]
[narration text="A  soft breeze"]
[choicegroup choices=[choice text=Continue]]
[branchgroup type=Choice groupLength=1]
[branch]
[narration text=The path ends]
'''
    rows = parse_adv(text, SOURCE).csv_rows()
    assert [r[2] for r in rows if r[0] == "select"] == ["A quiet rest", "Continue"]
    reactions = [r[2] for r in rows if "未确认选择" in r[2]]
    assert len(reactions) == 2
    assert reactions[0].endswith("（The  <r=かぜ>wind</r> is <em>cool</em>）")
    assert reactions[1].endswith("A  soft breeze")
    assert rows[-1][2] == "The path ends"


def test_nested_choice_reaction_retains_each_mutually_exclusive_option():
    script = parse_adv("""[choicegroup choices=[choice text=Outer option]]
[branchgroup type=Choice groupLength=1]
[branch groupLength=2]
[choicegroup choices=[choice text=Inner option]]
[branchgroup type=Choice groupLength=1]
[branch groupLength=1]
[message name=手毬 text=Nested reaction]
[message name=手毬 text=Shared tail]
""", SOURCE)
    row = script.csv_rows()[-2]
    assert "Outer option" in row[2] and "Inner option" in row[2]
    assert row[2].count("/Choice#1") == 2
    assert script.csv_rows()[-1][2] == "Shared tail"


@pytest.mark.parametrize("text", [
    "[branch]",
    "[branchgroup type=Surprise groupLength=0]",
    "[branchgroup type=Condition groupLength=1]",
    "[branchgroup type=Condition groupLength=1]\n[message text=Invalid child]",
    "[branchgroup type=Condition groupLength=-1]",
    "[choicegroup choices=[choice text=A]]\n[branchgroup type=Choice groupLength=0]",
    "[choicegroup choices=[choice text=A]]",
    "[choicegroup]\n[branchgroup type=Choice groupLength=0]",
    "[branchgroup type=Choice groupLength=1]\n[branch]",
    "[branchgroup type=Condition groupLength=1]\n[branch groupLength=2]\n[message text=Only one]",
    "[message text=Unclosed",
])
def test_ambiguous_or_truncated_control_flow_is_rejected(text: str):
    with pytest.raises(AdvParseError):
        parse_adv(text, SOURCE)


async def test_projection_survives_real_import_cast_passage_split_and_recall(tmp_path: Path):
    # Enough separate messages to cross passage boundaries: every reaction needs its label.
    reactions = "\n".join(f"[message name=手毬 text=Reaction {n} {'風' * 440}]" for n in range(5))
    script = parse_adv(f"""[message name=手毬 text=Common introduction]
[choicegroup choices=[choice text=Try this path]]
[branchgroup type=Choice groupLength=1]
[branch groupLength=6]
[message name={{user}} text=This must never become a recalled choice]
{reactions}
[message name=手毬 text=Common ending]
""", SOURCE)
    root = tmp_path / "source"
    root.mkdir()
    with (root / "fixture.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(script.csv_rows())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "source_url": "https://example.invalid/original", "version": "fixture-v1",
        "usage_conditions": "Original test fixture", "episodes": {SOURCE: "canon"},
    }), encoding="utf-8")
    characters = load_characters(Path(__file__).resolve().parents[2] / "characters/gim/characters.toml")
    corpus = StoryCorpus(tmp_path / "corpus.db", FakeEmbedder())
    try:
        report = await import_gim_directory(root, corpus, characters.values(), manifest=manifest)
        assert not report.has_errors
        assert report.imported == 1
        assert report.embedded_passages >= 2
        episode = corpus.get(f"gim/{SOURCE}")
        assert episode is not None
        assert episode.cast == {"temari"}
        assert len(episode.lines) == 7
        assert episode.lines[-1].ja == "Common ending"
        assert all("未确认选择" in line.ja for line in episode.lines[1:-1])
        passages = await corpus.search("風", "temari", limit=10)
        assert passages
        for passage in passages:
            assert "This must never" not in passage.text
            if "Reaction" in passage.text:
                assert "Try this path" in passage.text
                assert "互斥分支・未确认选择" in passage.text
    finally:
        corpus.close()


CONDITIONAL = """[message name={user} text=Producer introduction]
[message name=手毬 text=Scenario introduction]
[branchgroup type=Condition groupLength=2]
[branch groupLength=2]
[message name=制作人 text=Producer success]
[message name=手毬 text=Conditional success]
[branch groupLength=2]
[message name=プロデューサー text=Producer failure]
[message name=手毬 text=Conditional failure]
[narration text=Shared scenario tail]
"""


@pytest.mark.parametrize("key,labels,evidence", [
    (f"{SOURCE}:L2", ("Success", "Failure"), "External fixture mapping"),
    (f"{SOURCE}:L3", ("Only one",), "External fixture mapping"),
    (f"{SOURCE}:L3", ("Success", "  "), "External fixture mapping"),
    (f"{SOURCE}:L3", ("Success", "Failure"), "  "),
])
def test_unverified_condition_resolution_is_rejected(key: str, labels: tuple[str, ...], evidence: str):
    script = parse_adv(CONDITIONAL, SOURCE)
    with pytest.raises(AdvProjectionError):
        script.csv_rows(condition_resolutions={key: ConditionResolution(labels, evidence)})


def test_empty_context_is_rejected_and_unused_resolution_cannot_be_hidden():
    script = parse_adv(CONDITIONAL, SOURCE)
    with pytest.raises(AdvProjectionError):
        script.csv_rows(common_only=True, context="  ")
    with pytest.raises(AdvProjectionError):
        script.csv_rows(common_only=True, condition_resolutions={
            "unknown": ConditionResolution(("Option",), "Evidence"),
        })


async def test_evidenced_conditions_and_scenario_context_survive_real_import(tmp_path: Path):
    script = parse_adv(CONDITIONAL, SOURCE)
    original_graph = script.to_dict()
    with pytest.raises(AdvProjectionError, match="unknown runtime predicate"):
        script.csv_rows(context="Original scenario")
    rows = script.csv_rows(context="Fixture event variant; runtime threshold unknown", condition_resolutions={
        f"{SOURCE}:L3": ConditionResolution(
            ("Fixture challenge succeeded", "Fixture challenge failed"),
            "Original test metadata maps this group to two outcomes in this order",
        ),
    })
    assert script.to_dict() == original_graph
    assert script.nodes[2].to_dict()["predicate_status"] == "unknown"
    assert not any("Producer" in row[2] for row in rows)
    assert all("条件情境・未确认实际触发" in row[2] for row in rows[2:])
    assert "Condition#1" in rows[3][2] and "Fixture challenge succeeded" in rows[3][2]
    assert "Condition#2" in rows[4][2] and "Fixture challenge failed" in rows[4][2]
    root = tmp_path / "csv"
    root.mkdir()
    with (root / "conditional.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(rows)
    meta = tmp_path / "manifest.json"
    meta.write_text(json.dumps({
        "source_url": "https://example.invalid/fixture", "version": "test-v1",
        "usage_conditions": "Original conditional fixture", "episodes": {SOURCE: "canon"},
    }), encoding="utf-8")
    characters = load_characters(Path(__file__).resolve().parents[2] / "characters/gim/characters.toml")
    corpus = StoryCorpus(tmp_path / "db.sqlite", FakeEmbedder())
    try:
        report = await import_gim_directory(root, corpus, characters.values(), manifest=meta)
        assert not report.has_errors
        episode = corpus.get(f"gim/{SOURCE}")
        assert episode is not None and episode.cast == {"temari"}
        assert len(episode.lines) == 4
        assert all("条件情境・未确认实际触发" in line.ja for line in episode.lines)
        assert episode.lines[-1].ja.endswith("Shared scenario tail")
        recalled = await corpus.search("Conditional success", "temari")
        assert recalled and all("条件情境・未确认实际触发" in p.text for p in recalled)
        assert "未确认实际触发" in recalled[0].text and "Fixture challenge succeeded" in recalled[0].text
        assert "Producer" not in recalled[0].text
    finally:
        corpus.close()
