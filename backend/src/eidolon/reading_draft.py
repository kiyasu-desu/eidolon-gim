"""Drafting the readings file (`eidolon reading draft`, `readings`).

The first draft has each character's full name, her surname and her given name, those
with kanji in them, read as the first line of her sheet has it, `月村手毬（つきむら てまり）`:
the surname is what her name has ahead of her given name, which is the first of her
`speakers`. Then the units and the office's staff, as the world setting reads them. A name
already in the file is not drafted again; nor is a given name that is a word of its own
(`COMMON_WORDS`), which Fish Audio would misread wherever the word comes up, as it
matches keys anywhere they appear.

Run again on the file, it adds the characters, units and staff it lacks (by full name:
her surname or given name taken out of it stays out), fills in phonemes left empty, and
leaves every entry that has them as it is, so pitch digits tuned by hand stay. To change
how a name is read, change its kana, empty its phonemes and run it again. The file is
written anew each time: comments other than its heading are not kept.

The phonemes are made with pyopenjtalk as Fish Audio's documentation does it
(Fine-grained Control → Japanese), each part of the kana on its own and in katakana:
OpenJTalk reads hiragana as a sentence, はやかわ with the particle は, read わ.
pyopenjtalk is in the development dependencies only: the server does not need it.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from eidolon.characters import Character
from eidolon.readings import Reading
from eidolon.world import World

COMMON_WORDS = frozenset({"透"})
"""Names that are words of their own, not drafted alone: 透 is in 透明 and 透き通る."""

_KANJI = re.compile(r"[一-鿿々]")
_KANA = "ぁ-んァ-ヶー"

HEADING = """\
# 读音（GLOSSARY.md「读音」）：角色名、组合名、事务所名在角色的声音里怎么念。每次请求 Fish Audio
# 都把 phonemes 不为空的全部条目放进请求的 pronunciation_dictionary（readings.py）。
#
# written：原文写法，Fish Audio 按字面子串、区分大小写匹配，所以别收会和普通词撞上的写法
#   （「透」など）。kana：读音；用空格隔开的每一段分别转成音素再拼起来，人设里的名字在姓和名
#   之间空一格。phonemes：发给 Fish Audio 的音素串。
#
# 改读音：改 kana，把 phonemes 清空成 ""，在 backend 下运行 `uv run eidolon reading draft`
# 补上音素（已有音素的条目不动）；然后重启后端，再运行 `eidolon greeting upload`。
# 这个命令会重写整个文件，开头这段以外的注释不保留。
"""


@dataclass
class DraftReport:
    added: list[str] = field(default_factory=list)
    """What was drafted afresh."""
    filled: list[str] = field(default_factory=list)
    """What had its phonemes filled in."""
    unread: list[str] = field(default_factory=list)
    """The characters whose sheets do not say how their names are read."""


def draft_readings(
    existing: Sequence[Reading], characters: Iterable[Character], world: World | None
) -> tuple[list[Reading], DraftReport]:
    """The readings `existing` has, their phonemes filled in, then those of the characters,
    units and staff it lacks."""
    report = DraftReport()
    readings = {r.written: r for r in existing}

    def add(written: str, kana: str) -> None:
        if written not in readings:
            readings[written] = Reading(written, kana, "")
            report.added.append(written)

    for character in characters:
        if not _KANJI.search(character.name) or character.name in readings:
            continue
        drafted = _name_readings(character)
        if drafted is None:
            report.unread.append(character.name)
            continue
        for written, kana in drafted:
            add(written, kana)
    if world is not None:
        for unit in world.units:
            if unit.reading:
                add(unit.name, unit.reading)
        for staff in world.staff:
            if staff.reading:
                add(staff.name, staff.reading)

    for written, reading in readings.items():
        if not reading.phonemes and reading.kana:
            readings[written] = replace(reading, phonemes=to_phonemes(reading.kana))
            if written not in report.added:
                report.filled.append(written)
    return list(readings.values()), report


def _name_readings(character: Character) -> list[tuple[str, str]] | None:
    """Her full name, surname and given name with their kana, those with kanji in them,
    not words of their own; None if her sheet does not say how her name is read."""
    match = re.search(
        rf"{re.escape(character.name)}（([{_KANA}]+)[ 　]([{_KANA}]+)）", character.sheet
    )
    if match is None:
        return None
    surname_kana, given_kana = match.groups()
    drafted = [(character.name, f"{surname_kana} {given_kana}")]
    given = character.speakers[0] if character.speakers else ""
    if given and given != character.name and character.name.endswith(given):
        surname = character.name.removesuffix(given)
        for written, kana in ((surname, surname_kana), (given, given_kana)):
            if _KANJI.search(written) and written not in COMMON_WORDS:
                drafted.append((written, kana))
    return drafted


def write_readings(path: Path, readings: Iterable[Reading]) -> None:
    entries = [
        "[[readings]]\n"
        f"written = {_string(r.written)}\nkana = {_string(r.kana)}\nphonemes = {_string(r.phonemes)}\n"
        for r in readings
    ]
    path.write_text(
        HEADING + "".join(f"\n{entry}" for entry in entries), encoding="utf-8", newline="\n"
    )


def _string(value: str) -> str:
    """`value` as a TOML basic string: JSON's escapes are TOML's."""
    return json.dumps(value, ensure_ascii=False)


_VOWELS = "aiueoAIUEON"


def to_phonemes(kana: str) -> str:
    """`kana` as Fish Audio's phonemes, OpenJTalk's romaji with pitch digits, each part
    (apart by spaces) on its own."""
    return "".join(_romaji(_katakana(part)) for part in kana.split())


def _katakana(kana: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in kana)


def _romaji(word: str) -> str:
    """Fish Audio's `japanese_to_romaji_with_accent`, as its documentation has it."""
    import pyopenjtalk  # a development dependency

    labels = pyopenjtalk.extract_fullcontext(word)
    text = ""
    level = -1
    for index, label in enumerate(labels):
        phoneme = _field(r"\-([^\+]*)\+", label)
        if phoneme in ("sil", "pau"):
            continue
        text += phoneme
        a1 = int(_field(r"/A:(\-?[0-9]+)\+", label))
        a2 = int(_field(r"\+(\d+)\+", label))
        a3 = int(_field(r"\+(\d+)/", label))
        following = labels[index + 1]
        a2_next = (
            -1 if _field(r"\-([^\+]*)\+", following) in ("sil", "pau")
            else int(_field(r"\+(\d+)\+", following))
        )
        if a3 == 1 and a2_next == 1:
            if level >= 0:
                text += str(level)
            level = -1
        elif a1 == 0 and a2_next == a2 + 1:
            level = 0
            text += "1"
        elif a2 == 1 and a2_next == 2:
            level = 1
            text += "0"
        elif phoneme in _VOWELS:
            if level < 0:
                level = 0
            text += str(level)
    return text


def _field(pattern: str, label: str) -> str:
    match = re.search(pattern, label)
    assert match is not None, label
    return match.group(1)
