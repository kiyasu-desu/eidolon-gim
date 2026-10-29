"""Managing users in the admin console: admins list and search the users, look one up,
and ban or unban them with a note only admins see. A ban signs the user out everywhere,
keeps them from signing in and hangs up their calls; no admin can be banned there. The
admin console never shows what anyone said, what was remembered of them or their
producer profile."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import ANY

import httpx
import pytest

from eidolon.config import Settings
from tests.conftest import (
    SITE,
    ClientFactory,
    agree_to_terms,
    github_identity,
    google_identity,
    sign_in_with,
)
from tests.fakes import START, FakeClock, FakeIdentityProvider, FakeLLM, FakeLLMService
from tests.test_delete_account import memory_client, use_everything
from tests.test_shared_memory import CAT
from tests.test_text_turn import send_turn

ADMIN = ("github", "9001")


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, admins=frozenset({ADMIN}))


async def admin_client(
    make_client: ClientFactory, github: FakeIdentityProvider, **services
) -> httpx.AsyncClient:
    client = make_client(FakeLLM(), user=None, **services)
    await sign_in_with(client, github, github_identity(ADMIN[1], name="boss", email="boss@example.com"))
    await agree_to_terms(client)
    return client


@asynccontextmanager
async def admin_beside(
    client: httpx.AsyncClient, github: FakeIdentityProvider
) -> AsyncIterator[httpx.AsyncClient]:
    """The admin, signed in in another browser on the backend `client` is on, so that what
    they change in the admin console holds for its next turn."""
    transport = client._transport
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=SITE
    ) as admin:
        await sign_in_with(admin, github, github_identity(ADMIN[1], name="boss"))
        await agree_to_terms(admin)
        yield admin


async def github_user(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    subject: str,
    name: str,
    email: str,
    **services,
) -> httpx.AsyncClient:
    client = make_client(FakeLLM(), user=None, **services)
    await sign_in_with(client, github, github_identity(subject, name=name, email=email))
    await agree_to_terms(client)
    return client


async def users(admin: httpx.AsyncClient, **params) -> dict:
    res = await admin.get("/api/admin/users", params=params)
    assert res.status_code == 200, res.text
    return res.json()


async def find(admin: httpx.AsyncClient, name: str) -> dict:
    [user] = [u for u in (await users(admin))["users"] if u["name"] == name]
    return user


async def details(admin: httpx.AsyncClient, user_id: str) -> dict:
    res = await admin.get(f"/api/admin/users/{user_id}")
    assert res.status_code == 200, res.text
    return res.json()


async def test_admins_see_each_users_sign_in_methods_activity_and_ban_not_their_own_keys(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    google: FakeIdentityProvider,
):
    clock = FakeClock()
    admin = await admin_client(make_client, github, clock=clock)
    octo = await github_user(make_client, github, "1001", "octo", "octo@example.com", clock=clock)
    await sign_in_with(octo, google, google_identity("g-1001", "Octo G", email="g@example.com"), link=True)
    clock.advance(hours=2)
    await octo.get("/api/account")  # a session in use is renewed hourly

    listed = await find(admin, "octo")
    found = await details(admin, listed["id"])

    assert listed == {
        "id": listed["id"],
        "name": "octo",
        "sign_in_methods": [
            {"provider": "github", "subject": "1001", "display_name": "octo",
             "email": "octo@example.com"},
            {"provider": "google", "subject": "g-1001", "display_name": "Octo G",
             "email": "g@example.com"},
        ],
        "created_at": listed["created_at"],
        "last_active_at": (START.replace(hour=14)).isoformat(),
        "banned": False,
        "is_admin": False,  # nor whether they brought their own keys: the server never knows
        "limits": None,  # test_user_limits.py sets them
        "usage_24h": {"turns": 0, "calls": 0},  # test_user_recent_usage.py takes some
    }
    # test_user_recent_usage.py takes the usage over 24 hours, 7 and 30 days.
    assert found == listed | {"banned_at": None, "ban_note": None, "usage": ANY}
    assert (await find(admin, "boss"))["is_admin"] is True
    # Not to anyone else, nor about someone who is not there.
    assert (await octo.get("/api/admin/users")).status_code == 404
    assert (await octo.get(f"/api/admin/users/{listed['id']}")).status_code == 404
    assert (await admin.get("/api/admin/users/nobody")).status_code == 404
    assert (await admin.post("/api/admin/users/nobody/ban", json={})).status_code == 404


async def test_the_list_comes_in_pages_newest_first_and_finds_users_by_name_email_or_id(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    for subject, name in [("1", "sora-fan"), ("2", "riku-fan"), ("3", "nagi-fan")]:
        await github_user(make_client, github, subject, name, f"{name}@mail.example.com")
    nagi = await find(admin, "nagi-fan")

    first = await users(admin, limit=2)
    second = await users(admin, limit=2, offset=2)

    assert first["total"] == second["total"] == 4
    assert [u["name"] for u in first["users"] + second["users"]] == [
        "nagi-fan", "riku-fan", "sora-fan", "boss",
    ]
    for query, names in [
        ("RIKU", ["riku-fan"]),  # name, in any case
        ("sora-fan@mail", ["sora-fan"]),  # email
        (nagi["id"], ["nagi-fan"]),  # user id
        ("-fan", ["nagi-fan", "riku-fan", "sora-fan"]),
        ("%", []),  # taken as it is, not as a pattern
    ]:
        found = await users(admin, q=query)
        assert [u["name"] for u in found["users"]] == names, query
        assert found["total"] == len(names), query


async def test_a_ban_keeps_the_user_out_with_its_note_until_lifted(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    """Signing out everywhere and hanging up are `Store.set_banned`'s, which the command
    line shares; test_admin_commands.py drives them."""
    clock = FakeClock()
    admin = await admin_client(make_client, github, clock=clock)
    octo = await github_user(make_client, github, "1001", "octo", "octo@example.com", clock=clock)
    octo_id = (await find(admin, "octo"))["id"]

    res = await admin.post(f"/api/admin/users/{octo_id}/ban", json={"note": "刷量"})

    assert res.status_code == 200, res.text
    assert res.json()["banned"] is True
    assert res.json()["banned_at"] == START.isoformat()
    assert res.json()["ban_note"] == "刷量"
    assert (await octo.get("/api/account")).status_code == 401
    refused = await sign_in_with(octo, github, github_identity("1001", name="octo"))
    assert refused.headers["location"] == "/login?error=banned"

    res = await admin.delete(f"/api/admin/users/{octo_id}/ban")

    assert res.status_code == 200, res.text
    assert (res.json()["banned"], res.json()["banned_at"], res.json()["ban_note"]) == (
        False, None, None,
    )
    welcome = await sign_in_with(octo, github, github_identity("1001", name="octo"))
    assert welcome.headers["location"] == "/conversations"
    assert (await octo.get("/api/account")).status_code == 200


async def test_no_admin_can_be_banned_in_the_admin_console_not_even_oneself(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    settings = replace(settings, admins=frozenset({ADMIN, ("github", "9002")}))
    admin = await admin_client(make_client, github, settings=settings)
    other = make_client(FakeLLM(), user=None, settings=settings)
    await sign_in_with(other, github, github_identity("9002", name="deputy"))
    await agree_to_terms(other)

    for name in ("boss", "deputy"):
        target = await find(admin, name)
        res = await admin.post(f"/api/admin/users/{target['id']}/ban", json={"note": "试试"})
        assert res.status_code == 409, name
        assert "管理者" in res.json()["detail"], name
        assert (await details(admin, target["id"]))["banned"] is False, name
    assert (await other.get("/api/admin")).status_code == 200


async def test_a_banned_user_signing_in_is_told_whom_to_contact(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    contacted = replace(settings, contact="admin@example.com")
    admin = await admin_client(make_client, github, settings=contacted)
    await github_user(make_client, github, "1001", "octo", "octo@example.com", settings=contacted)
    await admin.post(f"/api/admin/users/{(await find(admin, 'octo'))['id']}/ban", json={})
    visitor = make_client(FakeLLM(), user=None, settings=contacted)

    refused = await sign_in_with(visitor, github, github_identity("1001", name="octo"))

    assert refused.headers["location"] == "/login?error=banned"
    assert (await visitor.get("/api/auth/providers")).json()["contact"] == "admin@example.com"


async def test_nothing_the_user_said_or_had_remembered_or_their_profile_shows(
    make_client: ClientFactory, github: FakeIdentityProvider, own_llm: FakeLLMService
):
    admin = await admin_client(make_client, github)
    producer = memory_client(make_client)
    await use_everything(producer)
    conversation = (await producer.get(
        "/api/conversations", params={"character_id": "sora"}
    )).json()[0]["id"]
    # Exercise an actual own key. Unlike four digits, this marker cannot occur in
    # a random hexadecimal user ID and masquerade as a credential disclosure.
    key_tail = "Z9!~"
    private_key = f"sk-test-admin-privacy-{key_tail}"
    own_llm.llm = FakeLLM(["<ja>はいっ</ja><zh>好的</zh>"])
    events = await send_turn(producer, conversation, "继续聊聊", own_llm={
        "protocol": "chat-completions", "base_url": "https://llm.example.com/v1",
        "api_key": private_key, "model": "privacy-test-model",
    })
    assert events[-1]["type"] == "done"
    assert own_llm.opened[-1].api_key == private_key
    producer_id = (await find(admin, "producer"))["id"]

    shown = [
        (await admin.get("/api/admin/users")).text,
        (await admin.get(f"/api/admin/users/{producer_id}")).text,
        (await admin.post(f"/api/admin/users/{producer_id}/ban", json={})).text,
        (await admin.delete(f"/api/admin/users/{producer_id}/ban")).text,
    ]

    for text in shown:
        for content in (CAT, "我家的猫叫小白哦", "はいっ", "好的", "小林", conversation, key_tail):
            assert content not in text, content
