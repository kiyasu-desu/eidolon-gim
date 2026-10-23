"""Housekeeping: what the backend deletes as it ages, everyone's at once, every `TICK` from
when it starts, on a thread of its own: uses of the limits a day old (`usage.KEPT`), and
activity records and service calls 90 days old (`activity.KEPT`). Not as each turn begins,
which would keep it waiting on deleting, and the whole server with it."""

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

log = logging.getLogger(__name__)

TICK = timedelta(minutes=10)


def tidy(*forgetting: Callable[[], None]) -> None:
    """Delete what has aged out with each of `forgetting`; one failing keeps none of the
    others from it."""
    for forget in forgetting:
        try:
            forget()
        except Exception:
            log.exception("tidying up failed")


async def keep_tidy(*forgetting: Callable[[], None]) -> None:
    """`tidy` now and at every `TICK`, until cancelled; cancelled while tidying, once the
    thread is done, so that what it uses is not closed under it."""
    while True:
        tidying = asyncio.ensure_future(asyncio.to_thread(tidy, *forgetting))
        try:
            await asyncio.shield(tidying)
        except asyncio.CancelledError:
            await tidying
            raise
        await asyncio.sleep(TICK.total_seconds())
