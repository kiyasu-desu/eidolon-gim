"""The local GIM roster uses the existing text conversation and record path."""

from dataclasses import replace
from pathlib import Path

from eidolon.config import Settings
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import FakeLLM, system_of
from tests.test_text_turn import send_turn, start_conversation

GIM_CHARACTERS = Path(__file__).resolve().parents[2] / "characters/gim/characters.toml"


async def test_temari_text_turn_has_no_old_world_and_survives_reopen(
    make_client: ClientFactory, settings: Settings,
):
    prototype = replace(
        settings,
        characters_path=GIM_CHARACTERS,
        affinity_and_gifts=False,
        reach_outs=False,
    )
    llm = FakeLLM(["<ja>こんにちは。</ja><zh>你好。</zh>"])
    client = make_client(llm, settings=prototype, voice_configured=False)

    roster = (await client.get("/api/characters")).json()
    assert [(character["id"], character["name"], character["stand"]) for character in roster] == [
        (
            "temari",
            "月村手毬",
            {
                "default_outfit": {
                    "id": "stand_3d/ttmr-default",
                    "url": "/api/characters/temari/stand/",
                },
                "outfits_url": None,
            },
        )
    ]
    conversation_id = await start_conversation(client, "temari")
    events = await send_turn(client, conversation_id, "你好，手毬")
    assert events[-1]["type"] == "done"
    prompt = system_of(llm.prompts[0])
    assert "初星学园" in prompt
    assert "283" not in prompt
    assert "闪耀色彩" not in prompt
    assert "櫻木真乃" not in prompt

    reopened = make_client(FakeLLM(), settings=prototype, voice_configured=False)
    listed = (await reopened.get("/api/conversations", params={"character_id": "temari"})).json()
    messages = (await reopened.get(f"/api/conversations/{conversation_id}/messages")).json()
    assert [conversation["id"] for conversation in listed] == [conversation_id]
    assert [(message["role"], message["text"], message["ja"], message["zh"])
            for message in messages] == [
        ("user", "你好，手毬", None, None),
        ("character", None, "こんにちは。", "你好。"),
    ]


async def test_temari_exposes_her_3d_stand_without_an_enza_id_and_serves_model_assets(
    make_client: ClientFactory, settings: Settings, tmp_path: Path,
):
    model_dir = tmp_path / "stand-3d"
    (model_dir / "textures").mkdir(parents=True)
    (model_dir / "model.json").write_text('{"meshes":[]}', encoding="utf-8")
    (model_dir / "animations.json").write_text('{"clips":[]}', encoding="utf-8")
    (model_dir / "textures" / "t_face.png").write_bytes(b"\x89PNG\r\n\x1a\nface")
    (model_dir / "textures" / "reflection-body.rgb9e5.bin").write_bytes(b"\x00\x01\x02\x03")
    (model_dir / "secret.txt").write_text("do not serve", encoding="utf-8")

    chars = CharacterConfig(tmp_path / "chars").add(
        "temari",
        "月村手毬",
        "# 人设\n你是月村手毬。",
        intro="初星学园偶像科一年级",
        color="#2f80ed",
        voice_id="temari-voice",
    )
    chars.path.write_text(
        chars.path.read_text(encoding="utf-8")
        + 'default_outfit = "stand_3d/ttmr-default"\n'
        + 'stand_model = "../stand-3d"\n',
        encoding="utf-8",
    )

    prototype = replace(
        settings,
        characters_path=chars.path,
        affinity_and_gifts=False,
        reach_outs=False,
    )
    client = make_client(FakeLLM(), settings=prototype, user=None)

    roster = (await client.get("/api/characters")).json()
    assert roster[0]["stand"] == {
        "default_outfit": {
            "id": "stand_3d/ttmr-default",
            "url": "/api/characters/temari/stand/",
        },
        "outfits_url": None,
    }

    model_res = await client.get("/api/characters/temari/stand/model.json")
    assert model_res.status_code == 200
    assert model_res.json() == {"meshes": []}
    assert model_res.headers["cache-control"] == "public, max-age=86400"

    revalidated = await client.get(
        "/api/characters/temari/stand/model.json",
        headers={"if-none-match": model_res.headers["etag"]},
    )
    assert revalidated.status_code == 304

    anim_res = await client.get("/api/characters/temari/stand/animations.json")
    assert anim_res.status_code == 200
    assert anim_res.json() == {"clips": []}

    tex_res = await client.get("/api/characters/temari/stand/textures/t_face.png")
    assert tex_res.status_code == 200
    assert tex_res.content == b"\x89PNG\r\n\x1a\nface"
    assert tex_res.headers["content-type"] == "image/png"
    reflection_res = await client.get("/api/characters/temari/stand/textures/reflection-body.rgb9e5.bin")
    assert reflection_res.status_code == 200
    assert reflection_res.content == b"\x00\x01\x02\x03"
    assert reflection_res.headers["content-type"] == "application/octet-stream"

    assert (await client.get("/api/characters/temari/stand/secret.txt")).status_code == 404
    assert (await client.get("/api/characters/temari/stand/textures/missing.png")).status_code == 404
    assert (await client.get("/api/characters/temari/stand/textures/..%2Fsecret.txt")).status_code == 404
