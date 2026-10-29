"""Voicing the greetings (`eidolon greeting upload`, GLOSSARY.md「招呼」): each greeting the
character configuration has is voiced in her voice on the deployer's Fish Audio key, as
mp3, and put in the stands' bucket where `/api/characters` says it is; only those the
bucket lacks, her old ones deleted once the new one is up. One that cannot be voiced or
put is reported and the rest go on. No turn, no run record, no one's limit. Checked
against a fake Fish Audio and a fake bucket that keeps what it is sent."""

from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from eidolon.activity import ActivityLog
from eidolon.characters import load_characters
from eidolon.config import FishAudioModel, Settings
from eidolon.greetings import FishAudioSettings, GreetingReport, greeting_path, upload_greetings
from eidolon.readings import load_readings, readings_path
from eidolon.s3 import S3Error, S3Settings
from tests.conftest import KOGANE_SHEET, MANO_SHEET, Admin, CharacterConfig, ClientFactory
from tests.fakes import START, FakeFishAudio, FakeLLM
from tests.test_s3 import FakeBucket

ASSETS = "https://stand.example"
MANO = ("[softly] えっと……はじめまして、星野ソラです", "……初次见面，我是星野ソラ")
KOGANE = ("うちが青葉リクばい！", "我就是青叶陆哦！")
MEGURU = ("はじめまして！晴川ヒナだよ！", "初次见面！我是八宫ヒナ！")
STAND_FILE = "spine/idols/stand/1030010010/data.png"
READINGS = (("星野ソラ", "sa0ku1ra1gi0ma1no0"), ("ソラ", "ma1no0"), ("283", "tsu0ba1sa1"))


class Deployment:
    """The character configuration, the deployer's Fish Audio and the stands' bucket,
    which already has a stand in it."""

    def __init__(self, characters: CharacterConfig) -> None:
        self.characters = characters
        self.fish = FakeFishAudio()
        self.storage = FakeBucket()
        self.storage.objects[STAND_FILE] = (b"stand", {})
        self.refused_puts: set[str] = set()
        """Characters whose greetings the bucket refuses to take."""
        self.configure()

    def configure(
        self,
        sora: tuple[str, str] = MANO,
        riku: tuple[str, str] | None = KOGANE,
        riku_voice: str = "riku-voice",
        sora_opener: tuple[str, str] | None = None,
    ) -> None:
        """Sora and Riku with greetings (unless `riku` is None), Nagi without one;
        Sora with a call opener if `sora_opener` is given. More can be added to `config`."""
        self.config = CharacterConfig(self.characters.directory).add(
            "sora", "星野ソラ", MANO_SHEET, voice_id="sora-voice", greeting=sora, call_opener=sora_opener
        ).add(
            "riku", "青葉リク", KOGANE_SHEET, voice_id=riku_voice, greeting=riku
        ).add("nagi", "雨宮ナギ", "sheet", voice_id="nagi-voice")

    def write_readings(self, *readings: tuple[str, str]) -> None:
        """The readings file has `readings`, each a name as written and its phonemes."""
        self.characters.write("readings.toml", "".join(
            f'[[readings]]\nwritten = "{written}"\nkana = "かな"\nphonemes = "{phonemes}"\n'
            for written, phonemes in readings
        ))

    async def upload(self, model: FishAudioModel = "s2.1-pro-free") -> GreetingReport:
        """As `eidolon greeting upload` does it, voicing with `model`."""
        characters = load_characters(self.characters.path, require_sheets=False)
        return await upload_greetings(
            characters.values(),
            S3Settings("http://storage.test", "stands", "key-id", "secret"),
            FishAudioSettings("deployer-fish-key", model),
            load_readings(readings_path(self.characters.path)),
            transport=httpx.MockTransport(self._handle),
        )

    def paths(self) -> dict[str, str | None]:
        """Where each character's greeting is, as the configuration is now."""
        characters = load_characters(self.characters.path, require_sheets=False)
        return {c.id: greeting_path(c) for c in characters.values()}

    def greetings(self) -> list[str]:
        return sorted(key for key in self.storage.objects if key.startswith("greetings/"))

    def call_openers(self) -> list[str]:
        return sorted(key for key in self.storage.objects if key.startswith("call-openers/"))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == FakeFishAudio.HOST:
            return self.fish.handle(request)
        if request.method == "PUT" and any(f"/greetings/{id}-" in request.url.path for id in self.refused_puts):
            return httpx.Response(403, text="<Error><Code>AccessDenied</Code></Error>")
        return self.storage.handle(request)


@pytest.fixture
def deployment(characters: CharacterConfig) -> Deployment:
    return Deployment(characters)


async def audio_urls(make_client: ClientFactory, settings: Settings) -> dict[str, str | None]:
    """Where `/api/characters` says each character's greeting is."""
    client = make_client(FakeLLM(), settings=replace(settings, stand_assets_url=ASSETS), user=None)
    listed = (await client.get("/api/characters")).json()
    return {c["id"]: c["greeting"] and c["greeting"]["audio_url"] for c in listed}


async def call_opener_url(make_client: ClientFactory, settings: Settings) -> str:
    """Where `/api/characters` says Sora's call opener is."""
    client = make_client(FakeLLM(), settings=replace(settings, stand_assets_url=ASSETS), user=None)
    listed = {c["id"]: c for c in (await client.get("/api/characters")).json()}
    return listed["sora"]["call_opener"]["audio_url"].removeprefix(f"{ASSETS}/")


def said(fish: FakeFishAudio) -> list[str]:
    return [request["text"] for request in fish.requests]


async def test_a_greeting_is_given_paired_tags_only_by_a_model_that_reads_them(
    deployment: Deployment,
):
    deployment.configure(sora=("<whisper>はじめまして</whisper>", MANO[1]), riku=None)
    await deployment.upload()
    deployment.storage.objects.clear()
    await deployment.upload("drama-3")

    assert said(deployment.fish) == ["はじめまして", "<whisper>はじめまして</whisper>"]
    assert [r["model"] for r in deployment.fish.requests] == ["s2.1-pro-free", "drama-3"]


async def test_each_greeting_is_voiced_in_her_voice_and_put_where_the_character_list_says(
    deployment: Deployment, make_client: ClientFactory, settings: Settings
):
    report = await deployment.upload()

    # In her voice, delivery cues and all, on the deployer's key, as mp3.
    first, second = deployment.fish.requests
    assert first["reference_id"] == "sora-voice"
    assert first["text"].startswith("[softly]") and first["text"].endswith("えっと……はじめまして、星野ソラです")
    assert first["format"] == "mp3"
    assert (first["key"], first["model"]) == ("deployer-fish-key", "s2.1-pro-free")
    assert (second["reference_id"], second["text"]) == ("riku-voice", KOGANE[0])
    # Where the character list says it is.
    urls = await audio_urls(make_client, settings)
    assert urls["nagi"] is None  # she has no greeting
    sora, riku = (url.removeprefix(f"{ASSETS}/") for url in (urls["sora"], urls["riku"]))  # pyright: ignore[reportOptionalMemberAccess]
    assert deployment.greetings() == sorted([sora, riku])
    body, headers = deployment.storage.objects[sora]
    assert body == FakeFishAudio.audio(first["text"], "sora-voice")
    assert headers["content-type"] == "audio/mpeg"
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert report.voiced == ["星野ソラ", "青葉リク"]
    assert report.failed == []
    assert report.exit_code == 0


async def test_every_greeting_is_voiced_with_the_readings_as_its_pronunciation_dictionary(
    deployment: Deployment,
):
    """All of them, those her greeting does not use too; she is told to say her words as
    they are written."""
    deployment.write_readings(*READINGS)

    await deployment.upload()

    whole = [{"items": [
        {"key": written, "value": phonemes, "case_sensitive": True} for written, phonemes in READINGS
    ]}]
    first, second = deployment.fish.requests
    assert first["pronunciation_dictionary"] == whole
    assert second["pronunciation_dictionary"] == whole
    assert first["text"].endswith("はじめまして、星野ソラです")
    assert second["text"] == KOGANE[0]


async def test_without_readings_greetings_are_voiced_with_no_pronunciation_dictionary(
    deployment: Deployment,
):
    await deployment.upload()

    assert all("pronunciation_dictionary" not in request for request in deployment.fish.requests)


async def test_a_greeting_is_voiced_again_once_a_reading_it_uses_changes(deployment: Deployment):
    """Its address is of the readings it uses too: one whose name is read anew is at an
    address no browser has cached. One that uses none is where it always was."""
    before = deployment.paths()
    deployment.write_readings(*READINGS)
    read = deployment.paths()

    assert read["sora"] != before["sora"]
    assert read["riku"] == before["riku"]
    await deployment.upload()
    deployment.fish.requests.clear()

    deployment.write_readings(("星野ソラ", "sa0ku1ra1gi1ma1no0"), *READINGS[1:])  # tuned by hand
    report = await deployment.upload()

    assert deployment.paths()["sora"] not in (read["sora"], before["sora"])
    assert [r["reference_id"] for r in deployment.fish.requests] == ["sora-voice"]
    assert report.voiced == ["星野ソラ"]
    assert report.deleted == [read["sora"]]

    # Readings her greeting does not use change: nothing is voiced again.
    deployment.write_readings(("星野ソラ", "sa0ku1ra1gi1ma1no0"), ("ソラ", "ma0no1"), ("283", "tsu1ba0sa0"))
    deployment.fish.requests.clear()
    report = await deployment.upload()

    assert report.voiced == []
    assert deployment.fish.requests == []


async def test_only_the_greetings_the_bucket_lacks_are_voiced(deployment: Deployment):
    await deployment.upload()
    deployment.fish.requests.clear()
    deployment.storage.puts.clear()

    report = await deployment.upload()

    assert deployment.fish.requests == []
    assert deployment.storage.puts == []
    assert report.voiced == []
    assert report.unchanged == 2

    deployment.configure(riku=("うちがリクばい！", KOGANE[1]))
    report = await deployment.upload()

    assert said(deployment.fish) == ["うちがリクばい！"]
    assert report.voiced == ["青葉リク"]
    assert report.unchanged == 1


async def test_a_new_subtitle_alone_voices_nothing(deployment: Deployment):
    await deployment.upload()
    deployment.fish.requests.clear()
    deployment.configure(sora=(MANO[0], "初次见面"))

    await deployment.upload()

    assert deployment.fish.requests == []


async def test_her_old_greeting_is_deleted_once_the_new_one_is_up(
    deployment: Deployment, make_client: ClientFactory, settings: Settings
):
    # Another character whose identifier starts with hers: hers is not Sora's to delete.
    sora_2 = ("sora-2", "星野ソラ（二）", "sheet")
    deployment.config.add(*sora_2, voice_id="sora-2-voice", greeting=MEGURU)
    await deployment.upload()
    old = await audio_urls(make_client, settings)

    deployment.configure(sora=("[happily] はじめまして！", MANO[1]), riku_voice="new-riku-voice")
    deployment.config.add(*sora_2, voice_id="sora-2-voice", greeting=MEGURU)
    report = await deployment.upload()

    new = await audio_urls(make_client, settings)
    assert deployment.greetings() == sorted(
        url.removeprefix(f"{ASSETS}/")  # pyright: ignore[reportOptionalMemberAccess]
        for url in (new["sora"], new["riku"], old["sora-2"])
    )
    assert sorted(report.deleted) == sorted(
        url.removeprefix(f"{ASSETS}/") for url in (old["sora"], old["riku"])  # pyright: ignore[reportOptionalMemberAccess]
    )
    assert STAND_FILE in deployment.storage.objects


async def test_an_old_greeting_left_behind_is_deleted_on_the_next_run(deployment: Deployment):
    """As when deleting it failed after the new one went up."""
    await deployment.upload()
    left_behind = "greetings/riku-0123456789ab.mp3"
    deployment.storage.objects[left_behind] = (b"an old one", {})

    report = await deployment.upload()

    assert report.deleted == [left_behind]
    assert left_behind not in deployment.storage.objects


async def test_a_greeting_taken_out_of_the_configuration_is_deleted(deployment: Deployment):
    """As when her greeting, or she, is taken out: the bucket is public, and nothing
    points at it any more."""
    await deployment.upload()
    riku = next(key for key in deployment.greetings() if key.startswith("greetings/riku-"))
    deployment.configure(riku=None)

    report = await deployment.upload()

    assert report.deleted == [riku]
    assert [key.split("-")[0] for key in deployment.greetings()] == ["greetings/sora"]
    assert STAND_FILE in deployment.storage.objects


async def test_one_that_fails_is_reported_and_the_rest_go_on(deployment: Deployment):
    deployment.configure(riku_voice="")  # Riku has no voice
    deployment.config.add("hina", "晴川ヒナ", "sheet", voice_id="hina-voice", greeting=MEGURU)
    deployment.config.add("towa", "架空トワ", "sheet", voice_id="towa-voice", greeting=("ふふっ", "呵呵"))
    deployment.fish.refuses["sora-voice"] = 402
    deployment.refused_puts.add("hina")

    report = await deployment.upload()

    failed = dict(report.failed)
    assert sorted(failed) == sorted(["晴川ヒナ", "青葉リク", "星野ソラ"])
    assert "音色" in failed["青葉リク"]
    assert "402" in failed["星野ソラ"]
    assert "403" in failed["晴川ヒナ"]
    assert report.voiced == ["架空トワ"]
    assert [key.split("-")[0] for key in deployment.greetings()] == ["greetings/towa"]
    assert report.exit_code != 0


MANO_OPENER = (
    "[shyly] あっ、もしもし……ソラです。えっと、今、お電話だいじょうぶですか？",
    "啊，喂……我是ソラ。那个，现在方便接电话吗？",
)


async def test_her_call_opener_is_voiced_in_her_voice_and_put_where_the_character_list_says(
    deployment: Deployment, make_client: ClientFactory, settings: Settings
):
    """GLOSSARY.md「开场白」: as her greeting is, with the same readings, at an address apart
    from the greetings'."""
    deployment.write_readings(*READINGS)
    deployment.configure(sora_opener=MANO_OPENER)

    report = await deployment.upload()

    opener = next(r for r in deployment.fish.requests if "もしもし" in r["text"])
    assert opener["reference_id"] == "sora-voice"
    assert opener["text"].startswith("[shyly]") and opener["text"].endswith("お電話だいじょうぶですか？")
    assert opener["pronunciation_dictionary"] == deployment.fish.requests[0]["pronunciation_dictionary"]
    path = await call_opener_url(make_client, settings)
    assert deployment.call_openers() == [path]
    assert path.startswith("call-openers/sora-")
    body, headers = deployment.storage.objects[path]
    assert body == FakeFishAudio.audio(opener["text"], "sora-voice")
    assert headers["content-type"] == "audio/mpeg"
    assert len(deployment.greetings()) == 2  # hers and Riku's, where they were
    assert sorted(report.voiced) == sorted(["星野ソラ", "青葉リク", "星野ソラ的开场白"])
    assert report.exit_code == 0


async def test_her_call_opener_and_her_greeting_are_voiced_again_each_by_its_own_words(
    deployment: Deployment,
):
    deployment.configure(sora_opener=MANO_OPENER)
    await deployment.upload()
    greetings, (old_opener,) = deployment.greetings(), deployment.call_openers()
    deployment.fish.requests.clear()

    report = await deployment.upload()

    assert deployment.fish.requests == []
    assert report.unchanged == 3

    deployment.configure(sora_opener=("[shyly] もしもし、ソラです", MANO_OPENER[1]))
    report = await deployment.upload()

    (text,) = said(deployment.fish)
    assert text.startswith("[shyly]") and text.endswith("もしもし、ソラです")
    assert report.voiced == ["星野ソラ的开场白"]
    assert report.deleted == [old_opener]
    assert deployment.greetings() == greetings
    (new_opener,) = deployment.call_openers()
    assert new_opener != old_opener

    # Her greeting changes: her call opener stays where it is.
    deployment.configure(sora=("はじめまして", MANO[1]), sora_opener=("[shyly] もしもし、ソラです", MANO_OPENER[1]))
    report = await deployment.upload()

    assert report.voiced == ["星野ソラ"]
    assert deployment.call_openers() == [new_opener]


async def test_her_call_opener_moves_when_her_voice_or_a_reading_it_uses_changes(deployment: Deployment):
    deployment.configure(sora_opener=MANO_OPENER)
    await deployment.upload()
    (first,) = deployment.call_openers()

    deployment.write_readings(*READINGS)  # ソラ is read
    await deployment.upload()
    (read,) = deployment.call_openers()

    assert read != first


async def test_a_call_opener_taken_out_of_the_configuration_is_deleted_and_her_greeting_kept(
    deployment: Deployment,
):
    deployment.configure(sora_opener=MANO_OPENER)
    await deployment.upload()
    (opener,) = deployment.call_openers()
    greetings = deployment.greetings()

    deployment.configure()
    report = await deployment.upload()

    assert report.deleted == [opener]
    assert deployment.call_openers() == []
    assert deployment.greetings() == greetings


async def test_a_call_opener_without_a_voice_is_reported_as_hers(deployment: Deployment):
    deployment.configure(sora_opener=MANO_OPENER)
    deployment.config.add(
        "hina", "晴川ヒナ", "sheet", voice_id="", call_opener=("もしもし！", "喂！")
    )

    report = await deployment.upload()

    assert [name for name, _ in report.failed] == ["晴川ヒナ的开场白"]
    assert report.exit_code != 0


async def test_a_bucket_that_cannot_be_listed_is_an_error_before_anything_is_voiced(deployment: Deployment):
    deployment.storage.down = True

    with pytest.raises(S3Error, match="503"):
        await deployment.upload()

    assert deployment.fish.requests == []


async def test_voicing_the_greetings_leaves_no_run_record(
    deployment: Deployment, make_client: ClientFactory, settings: Settings
):
    """Greetings are not turns: nothing about them is recorded, and no one's limit counts
    them."""
    make_client(FakeLLM())  # the deployment's database, as the server leaves it

    await deployment.upload()

    activity = ActivityLog(settings.database_path, lambda: START)
    try:
        assert activity.since(START - timedelta(days=365)) == ([], [])
    finally:
        activity.close()


def test_uploading_without_the_bucket_or_fish_audio_exits_1(
    admin: Admin, deployment: Deployment, monkeypatch: pytest.MonkeyPatch
):
    for name in ("ENDPOINT", "BUCKET", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.delenv(f"EIDOLON_STAND_S3_{name}", raising=False)
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "deployer-fish-key")

    code, _, err = admin.invoke("greeting", "upload", "--characters", str(deployment.characters.path))

    assert code == 1
    assert "EIDOLON_STAND_S3_ENDPOINT" in err

    for name, value in {
        "ENDPOINT": "https://storage.example", "BUCKET": "stands", "ACCESS_KEY_ID": "key-id",
        "SECRET_ACCESS_KEY": "secret",
    }.items():
        monkeypatch.setenv(f"EIDOLON_STAND_S3_{name}", value)
    monkeypatch.delenv("FISH_AUDIO_API_KEY")

    code, _, err = admin.invoke("greeting", "upload", "--characters", str(deployment.characters.path))

    assert code == 1
    assert "FISH_AUDIO_API_KEY" in err
