"""Waiting on the database is done on threads, not on the event loop, which every call's
audio runs on too: a text turn reads and writes the database on threads, but for recording
the turn itself, which may hang up her calls with the user there; so does deleting an
account. As many as `assembly.THREADS` may wait on threads at once."""

import asyncio
import threading
from collections.abc import Callable
from typing import Any

import pytest

from eidolon.assembly import THREADS
from eidolon.store import Store
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM
from tests.test_delete_account import DELETE
from tests.test_live_config import start
from tests.test_service_status import backend_of
from tests.test_text_turn import send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]


def watch(
    monkeypatch: pytest.MonkeyPatch, store: Store, names: list[str]
) -> dict[str, set[int]]:
    """The threads each of the store's methods `names` is called on, from now on."""
    threads: dict[str, set[int]] = {name: set() for name in names}
    for name in names:
        method = getattr(store, name)

        def watched(*args: Any, _name: str = name, _method: Callable = method) -> Any:
            threads[_name].add(threading.get_ident())
            return _method(*args)

        monkeypatch.setattr(store, name, watched)
    return threads


async def test_a_text_turn_reads_the_database_off_the_event_loop(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    client = make_client(FakeLLM(REPLY, REPLY))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "早上好")  # so that there is a record to read
    threads = watch(
        monkeypatch, backend_of(client).store,
        ["ended", "record", "last_contact", "get_profile", "typed_turns"],
    )

    await send_turn(client, conversation, "在吗")

    assert all(threads.values()), threads
    assert not [name for name, on in threads.items() if threading.get_ident() in on]


async def test_deleting_an_account_deletes_off_the_event_loop(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    client = make_client(FakeLLM())
    threads = watch(monkeypatch, backend_of(client).store, ["delete_user"])

    res = await client.post("/api/account/delete", json=DELETE)

    assert res.status_code == 204
    assert threads["delete_user"] and threading.get_ident() not in threads["delete_user"]


async def test_as_many_as_32_wait_on_threads_at_once(make_client: ClientFactory):
    """However few the server's cores: a backup or data package taking minutes keeps no
    turn waiting for a thread."""
    client = make_client(FakeLLM())
    await start(client)
    all_there = threading.Barrier(THREADS, timeout=5)

    await asyncio.gather(*[asyncio.to_thread(all_there.wait) for _ in range(THREADS)])
