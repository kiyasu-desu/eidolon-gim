"""Personal deployments admit only listed OAuth subjects, including existing sessions."""

from dataclasses import replace

import pytest

from eidolon.config import Settings, identities_from_env
from eidolon.sessions import SESSION_COOKIE
from tests.conftest import (
    ClientFactory, agree_to_terms, github_identity, google_identity, sign_in_as, sign_in_with,
)
from tests.fakes import FakeIdentityProvider, FakeLLM


@pytest.mark.parametrize("provider_name", ["github", "google"])
async def test_only_listed_subject_can_sign_in(
    make_client: ClientFactory, settings: Settings,
    github: FakeIdentityProvider, google: FakeIdentityProvider, provider_name: str,
):
    provider = github if provider_name == "github" else google
    identity = github_identity() if provider_name == "github" else google_identity()
    private = replace(
        settings, dev_login=False, private_mode=True,
        allowed_identities=frozenset({(identity.provider, identity.subject)}),
    )
    denied = make_client(FakeLLM(), user=None, settings=private)
    # Even the owner's same name and email do not grant access to another subject.
    response = await sign_in_with(denied, provider, replace(identity, subject="other"))
    assert response.headers["location"] == "/login?error=not_allowed"
    assert SESSION_COOKIE not in denied.cookies
    assert (await denied.get("/api/account")).status_code == 401

    owner = make_client(FakeLLM(), user=None, settings=private)
    response = await sign_in_with(owner, provider, identity)
    assert response.headers["location"] == "/conversations"
    await agree_to_terms(owner)
    assert (await owner.get("/api/account")).status_code == 200
    assert (await owner.post("/api/auth/dev-login", json={"name": "producer"})).status_code == 404


async def test_owner_cannot_link_an_unlisted_identity(
    make_client: ClientFactory, settings: Settings,
    github: FakeIdentityProvider, google: FakeIdentityProvider,
):
    private = replace(
        settings, dev_login=False, private_mode=True,
        allowed_identities=frozenset({("github", "1001")}),
    )
    owner = make_client(FakeLLM(), user=None, settings=private)
    await sign_in_with(owner, github, github_identity())
    await agree_to_terms(owner)
    response = await sign_in_with(owner, google, google_identity(), link=True)
    assert response.headers["location"] == "/settings/sign-in?error=not_allowed"
    methods = (await owner.get("/api/account")).json()["sign_in_methods"]
    assert [method["provider"] for method in methods] == ["github"]


@pytest.mark.parametrize("has_identity", [False, True])
async def test_enabling_private_access_revokes_old_unlisted_sessions(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider,
    has_identity: bool,
):
    old = make_client(FakeLLM(), user=None if has_identity else "producer")
    if has_identity:
        await sign_in_with(old, github, github_identity("stranger"))
        await agree_to_terms(old)
    assert (await old.get("/api/account")).status_code == 200
    private = replace(
        settings, dev_login=False, private_mode=True,
        allowed_identities=frozenset({("github", "1001")}),
    )
    after_restart = make_client(FakeLLM(), user=None, settings=private)
    sign_in_as(after_restart, old)
    assert (await after_restart.get("/api/account")).status_code == 401
    # Reopening public sign-in later must not resurrect that session.
    assert (await old.get("/api/account")).status_code == 401


async def test_allowlisted_existing_session_survives_private_access(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider,
):
    old = make_client(FakeLLM(), user=None)
    await sign_in_with(old, github, github_identity())
    await agree_to_terms(old)
    private = replace(
        settings, dev_login=False, private_mode=True,
        allowed_identities=frozenset({("github", "1001")}),
    )
    after_restart = make_client(FakeLLM(), user=None, settings=private)
    sign_in_as(after_restart, old)
    assert (await after_restart.get("/api/account")).status_code == 200


def test_private_mode_requires_a_nonempty_allowlist(settings: Settings):
    with pytest.raises(RuntimeError, match="EIDOLON_ALLOWED_IDENTITIES"):
        replace(settings, dev_login=False, private_mode=True)
    with pytest.raises(RuntimeError, match="EIDOLON_DEV_LOGIN"):
        replace(settings, allowed_identities=frozenset({("github", "1001")}))


@pytest.mark.parametrize("value", ["github:", "email:owner@example.com", "owner"])
def test_bad_allowlist_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str):
    monkeypatch.setenv("EIDOLON_ALLOWED_IDENTITIES", value)
    with pytest.raises(RuntimeError, match="EIDOLON_ALLOWED_IDENTITIES"):
        identities_from_env("EIDOLON_ALLOWED_IDENTITIES")


def test_private_access_from_env(monkeypatch: pytest.MonkeyPatch):
    for name, value in {
        "CHAT_LLM_BASE_URL": "http://llm.invalid/v1", "CHAT_LLM_API_KEY": "k",
        "CHAT_LLM_MODEL": "m", "EIDOLON_DEV_LOGIN": "", "EIDOLON_PRIVATE_MODE": "1",
        "EIDOLON_ALLOWED_IDENTITIES": "github:1001, google:g-1001",
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert settings.private_mode
    assert settings.allowed_identities == frozenset({("github", "1001"), ("google", "g-1001")})
    monkeypatch.delenv("EIDOLON_ALLOWED_IDENTITIES")
    with pytest.raises(RuntimeError, match="EIDOLON_ALLOWED_IDENTITIES"):
        Settings.from_env()
