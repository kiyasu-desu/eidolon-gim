"""The gift catalog (GLOSSARY.md「礼物」) comes from configuration beside the characters':
checked as the backend starts, read by signed-in users without who likes what, and each
gift with its illustration in the frontend's static files. Each character's liked gifts
are in her character configuration, checked against the catalog as the backend starts."""

import tomllib
from collections import Counter
from pathlib import Path

import pytest

from eidolon.gift_catalog import GIFTS_FILE

from tests.conftest import REPO_GIFTS, CharacterConfig, ClientFactory
from tests.fakes import FakeLLM

REPO_ILLUSTRATIONS = Path(__file__).parents[2] / "frontend" / "public" / "gifts"


def gift(id: str, rarity: str = "common", category: str = "food", retired: bool = False) -> str:
    entry = f'[[gifts]]\nid = "{id}"\nname = "{id}"\ncategory = "{category}"\nrarity = "{rarity}"\n'
    return entry + ("retired = true\n" if retired else "")


ONE_OF_EACH_RARITY = gift("cake") + gift("cocoa", "uncommon") + gift("plush", "rare")


async def test_the_catalog_lists_every_gift_with_its_category_rarity_and_whether_retired(
    make_client: ClientFactory,
):
    client = make_client(FakeLLM())

    res = await client.get("/api/gifts/catalog")

    assert res.status_code == 200
    catalog = res.json()
    assert len(catalog) == 19
    assert all(set(g) == {"id", "name", "category", "rarity", "retired"} for g in catalog)
    assert Counter(g["rarity"] for g in catalog) == {"common": 9, "uncommon": 7, "rare": 3}
    assert {"id": "pudding", "name": "布丁", "category": "food", "rarity": "common",
            "retired": False} in catalog
    assert not any(g["retired"] for g in catalog)


async def test_a_retired_gift_is_still_listed_as_retired(
    make_client: ClientFactory, characters: CharacterConfig
):
    characters.write(GIFTS_FILE, ONE_OF_EACH_RARITY + gift("candy", retired=True))
    client = make_client(FakeLLM())

    catalog = (await client.get("/api/gifts/catalog")).json()

    assert [(g["id"], g["retired"]) for g in catalog] == [
        ("cake", False), ("cocoa", False), ("plush", False), ("candy", True),
    ]


@pytest.mark.parametrize(
    ("catalog", "named"),
    [
        (ONE_OF_EACH_RARITY + gift("cake"), "cake"),
        (ONE_OF_EACH_RARITY + gift("Big Cake"), "Big Cake"),
        ('gifts = ["cake"]\n', "cake"),
        (ONE_OF_EACH_RARITY + gift("bread", category="bakery"), "bakery"),
        (ONE_OF_EACH_RARITY + gift("bread", rarity="legendary"), "legendary"),
        (gift("cake") + gift("cocoa", "uncommon") + gift("plush", "rare", retired=True), "rare"),
        ('[[gifts]]\nid = "cake"\nname = "蛋糕"\ncategory = "food"\n' + gift("x", "uncommon"), "rarity"),
        (ONE_OF_EACH_RARITY.replace('name = "cake"', "name = 3"), "name"),
        (ONE_OF_EACH_RARITY + gift("bread") + 'retired = "yes"\n', "retired"),
        ("[[gifts]\n", GIFTS_FILE),
    ],
)
def test_a_broken_catalog_keeps_the_backend_from_starting(
    make_client: ClientFactory, characters: CharacterConfig, catalog: str, named: str
):
    characters.write(GIFTS_FILE, catalog)

    with pytest.raises(RuntimeError, match=named):
        make_client(FakeLLM())


def test_a_missing_catalog_keeps_the_backend_from_starting(
    make_client: ClientFactory, characters: CharacterConfig
):
    (characters.directory / GIFTS_FILE).unlink()

    with pytest.raises(RuntimeError, match=GIFTS_FILE):
        make_client(FakeLLM())


HIORI_SHEET = "# 人设\n你是雨宮ナギ。"


@pytest.mark.parametrize(
    ("liked", "named"),
    [
        (("cake", "macaron"), "macaron"),
        (("cake", "cocoa", "plush", "candy"), "最多 3 件"),
        (("plush", "jewelry"), "稀有"),
        (("cake", "cake"), "重复"),
        (None, "liked_gifts"),
    ],
)
def test_wrong_liked_gifts_keep_the_backend_from_starting(
    make_client: ClientFactory,
    characters: CharacterConfig,
    liked: tuple[str, ...] | None,
    named: str,
):
    characters.add("nagi", "雨宮ナギ", HIORI_SHEET, liked_gifts=liked)

    with pytest.raises(RuntimeError, match=named):
        make_client(FakeLLM())


def test_liked_gifts_must_be_a_list_of_gift_ids(
    make_client: ClientFactory, characters: CharacterConfig
):
    characters.add("nagi", "雨宮ナギ", HIORI_SHEET, liked_gifts=None)
    characters.path.write_text(
        characters.path.read_text(encoding="utf-8") + 'liked_gifts = "cake"\n', encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="liked_gifts"):
        make_client(FakeLLM())




def _webp_size(path: Path) -> tuple[int, int]:
    """Width and height from a WebP's header, without an imaging library."""
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError(f"{path} is not a WebP")
    chunk = data[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
    if chunk == b"VP8 ":
        return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF)
    raise ValueError(f"{path} has an unknown WebP chunk {chunk!r}")


def test_repository_gifts_each_have_their_illustration_and_nothing_else_is_there():
    """No gift goes without its illustration (there is no icon to fall back on), each 512px
    and a few tens of KB as the gifts page loads them all at once; the CREDITS aside, a file
    no gift names is one left behind."""
    ids = {g["id"] for g in tomllib.loads(REPO_GIFTS.read_text(encoding="utf-8"))["gifts"]}
    files = {p.name for p in REPO_ILLUSTRATIONS.iterdir()} - {"CREDITS.md"}

    assert files == {f"{id}.webp" for id in ids}
    wrong = {id: _oversized(REPO_ILLUSTRATIONS / f"{id}.webp") for id in ids}
    assert {id: w for id, w in wrong.items() if w} == {}


def test_the_reset_card_illustration_is_sized_as_the_gifts_are():
    """The reset card is no gift, but it is drawn beside them in a draw's results, and has
    no icon to fall back on either; the CREDITS aside, nothing else is there."""
    folder = REPO_ILLUSTRATIONS.parent / "reset-card"

    assert {p.name for p in folder.iterdir()} == {"reset-card.webp", "CREDITS.md"}
    assert _oversized(folder / "reset-card.webp") is None


def _oversized(path: Path) -> tuple[tuple[int, int], int] | None:
    """An illustration's size and bytes, unless it is 512px and within 64 KB."""
    size, weight = _webp_size(path), path.stat().st_size
    return None if size == (512, 512) and weight <= 64 * 1024 else (size, weight)
