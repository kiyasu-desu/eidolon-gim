"""Hot words: the names a call's speech recognition is told to listen out for, so that 灯織,
手毬, 初星学園 or 月村 said in a call are written as they are, not as something else that
sounds the same.

They are made once, as the server starts, from what is already kept: every way of writing
in the readings file (`readings`); each character's Chinese name (`name_zh`), and her
Chinese given name, the Chinese name without as many characters at its start as her
Japanese surname has (月村手毬 → 手毬), her Japanese surname being the
reading that starts her full name without being it; and the names of the world setting's
units. Lone surnames (田中, 鈴木) and single characters (巡) are left out: they would have
ordinary words heard as names. So are words the services take none of, as Alibaba Cloud
Model Studio (阿里云百炼) says (any but ASCII: more than 15 characters; ASCII: more than 7
words), with a warning.

Every call carries the same words, on the deployer's key or the user's own (see
`call.SpeechServices`).
"""

import logging
from collections.abc import Iterable

from eidolon.characters import Character
from eidolon.readings import Reading
from eidolon.world import World

log = logging.getLogger(__name__)

MAX_CHARACTERS = 15
"""The most characters a word with any but ASCII in it may have."""
MAX_WORDS = 7
"""The most words, split at spaces, a word all in ASCII may have."""


def hot_words(
    readings: Iterable[Reading], characters: Iterable[Character], world: World | None
) -> tuple[str, ...]:
    """The hot words, each once, in the order they are found: the readings first, then
    the Chinese names, then the units."""
    readings, characters = tuple(readings), tuple(characters)
    surnames = {
        r.written
        for r in readings
        for c in characters
        if c.name.startswith(r.written) and c.name != r.written
    }
    found = [r.written for r in readings]
    for character in characters:
        if not character.name_zh:
            continue
        found.append(character.name_zh)
        surname_length = max(
            (len(s) for s in surnames if character.name.startswith(s)), default=None
        )
        if surname_length is not None:
            found.append(character.name_zh[surname_length:])
    if world is not None:
        found.extend(unit.name for unit in world.units)

    words: dict[str, None] = {}
    too_long: list[str] = []
    for word in (w.strip() for w in found):
        if len(word) <= 1 or word in surnames or word in words:
            continue
        if _fits(word):
            words[word] = None
        elif word not in too_long:
            too_long.append(word)
    if too_long:
        log.warning(
            "hot words too long for speech recognition, left out: %s (at most %d characters,"
            " or %d words in ASCII)",
            "、".join(too_long), MAX_CHARACTERS, MAX_WORDS,
        )
    return tuple(words)


def _fits(word: str) -> bool:
    """Whether the services take `word` as a hot word."""
    if word.isascii():
        return len(word.split()) <= MAX_WORDS
    return len(word) <= MAX_CHARACTERS
