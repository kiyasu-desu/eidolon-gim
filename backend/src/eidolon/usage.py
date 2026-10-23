"""Per-user rate limits, so one user cannot use up the API credit everyone shares: on text
turns, voice calls, and the photos she sends (GLOSSARY.md「照片」), each apart.

A turn or call exempt on the user's own keys (GLOSSARY.md「免限额密钥」) is recorded all the
same, for the admin to see, but does not count towards the limit. An admin may set a user's
own limits, apart from the deployment's: a number, unlimited, or 0, which leaves them the
exempt ones only.
Each use is kept in the database, next to the
user it belongs to, for a day; whoever's they are, uses older than that are deleted as the
backend tidies up (`housekeeping`)."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from eidolon.clock import Clock
from eidolon.config import UsageLimits
from eidolon.database import connect

UsageKind = Literal["turn", "call", "photo"]

UserLimit = int | Literal["unlimited"] | None
"""A user's own limit on a kind of use an hour: a number (0: on their own keys only),
"unlimited", or None, the deployment's."""

WINDOW = timedelta(hours=1)

KEPT = timedelta(hours=24)
"""How long each use is kept: an hour for the limits, a day for the admin to look over."""

_NAMES: dict[UsageKind, str] = {"turn": "文字对话", "call": "语音通话", "photo": "照片"}

_SCHEMA = """
-- `at` is epoch seconds rather than ISO text, so that the window is a plain range query.
-- A use exempt on the user's own keys is `exempt`: recorded, but not limited.
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    at REAL NOT NULL,
    exempt INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS usage_by_user ON usage(user_id, kind, at);
-- For forgetting everyone's uses once they are older than `KEPT`.
CREATE INDEX IF NOT EXISTS usage_by_time ON usage(at);
-- A user's own limits, set by an admin; a NULL limit is the deployment's, -1 unlimited.
CREATE TABLE IF NOT EXISTS user_limits (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    turns_per_hour INTEGER,
    calls_per_hour INTEGER,
    note TEXT,
    updated_at TEXT NOT NULL,
    photos_per_hour INTEGER
);
"""

_UNLIMITED_ROW = -1
_COLUMNS: dict[UsageKind, str] = {
    "turn": "turns_per_hour", "call": "calls_per_hour", "photo": "photos_per_hour",
}


class OverLimit(Exception):
    """The user has used up this hour's `kind`; they can go on at `retry_at`. With a
    limit of 0 they may only on their own keys, and `retry_at` is None."""

    def __init__(
        self, kind: UsageKind, limit: int, retry_at: datetime | None, now: datetime
    ) -> None:
        super().__init__(
            f"这一小时的{_NAMES[kind]}次数已经用完了（每小时 {limit} 次）" if limit
            else f"你的{_NAMES[kind]}只能用自带密钥，可以在设置里填写"
        )
        self.retry_at = retry_at
        self.now = now


@dataclass(frozen=True)
class UserLimits:
    """A user's own limits an hour, each apart (None: the deployment's), with a note for
    the admins and when they were set."""

    turns_per_hour: UserLimit
    calls_per_hour: UserLimit
    note: str | None = None
    updated_at: str = ""
    photos_per_hour: UserLimit = None


@dataclass(frozen=True)
class Tally:
    """How many text turns and calls, and how many of each were on the user's own keys."""

    turns: int = 0
    calls: int = 0
    exempt_turns: int = 0
    exempt_calls: int = 0


@dataclass(frozen=True)
class DayOfUse:
    """A user's uses in the last day: each UTC hour that has any, oldest first, and all."""

    hours: dict[datetime, Tally]
    total: Tally


class Use:
    """One counted text turn or call; given back when it fails, so the user keeps it."""

    def __init__(self, limiter: "UsageLimiter", use_id: int) -> None:
        self._limiter = limiter
        self._id: int | None = use_id

    def give_back(self) -> None:
        if self._id is not None:
            self._limiter._give_back(self._id)
            self._id = None


class UsageLimiter:
    """Counts each user's text turns, voice calls and photos over the last hour, whichever
    device or sign-in method they come with."""

    def __init__(
        self, path: Path, limits: UsageLimits | Callable[[], UsageLimits], clock: Clock
    ) -> None:
        """Uses kept in the database at `path`, next to the users they belong to, limited
        by `limits`, or by what it says as each use is taken (the live configuration's)."""
        # What is given back or forgotten is overwritten, not just freed (see `database`).
        self._db = connect(path)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)
            columns = {name for _, name, *_ in self._db.execute("PRAGMA table_info(usage)")}
            if "exempt" not in columns:
                self._db.execute("ALTER TABLE usage ADD COLUMN exempt INTEGER NOT NULL DEFAULT 0")
            columns = {
                name for _, name, *_ in self._db.execute("PRAGMA table_info(user_limits)")
            }
            # Whether an admin let the user use the deployer's LLM where users had to bring
            # their own, which no longer is a rule.
            if "deployer_llm_allowed" in columns:
                self._db.execute("ALTER TABLE user_limits DROP COLUMN deployer_llm_allowed")
            if "photos_per_hour" not in columns:
                self._db.execute("ALTER TABLE user_limits ADD COLUMN photos_per_hour INTEGER")
        self._limits = limits if callable(limits) else lambda: limits
        self._clock = clock

    @property
    def limits(self) -> UsageLimits:
        """The limits in effect now."""
        return self._limits()

    def take(self, user_id: str, kind: UsageKind, exempt: bool = False) -> Use:
        """Record one `kind` by the user, counting it against their limit unless it is
        `exempt`; raises OverLimit, recording nothing, when they have none left this hour,
        that is, when the last hour already holds as many counting uses as the limit: the
        user's own, if an admin set one, else the deployment's."""
        now = self._clock()
        with self._lock, self._db:
            if not exempt:
                self._refuse_over(user_id, kind, now)
            cursor = self._db.execute(
                "INSERT INTO usage (user_id, kind, at, exempt) VALUES (?, ?, ?, ?)",
                (user_id, kind, now.timestamp(), int(exempt)),
            )
        assert cursor.lastrowid is not None
        return Use(self, cursor.lastrowid)

    def forget_old(self) -> None:
        """Delete everyone's uses older than `KEPT`, so that a user who does not come back
        leaves none behind."""
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM usage WHERE at <= ?", ((self._clock() - KEPT).timestamp(),)
            )

    def check(self, user_id: str, kind: UsageKind) -> None:
        """Raise OverLimit, as `take` would, if the user has no `kind` left this hour that
        counts; take nothing."""
        with self._lock:
            self._refuse_over(user_id, kind, self._clock())

    def user_limits(self, user_id: str) -> UserLimits | None:
        """The user's own limits; None if an admin set none."""
        with self._lock:
            row = self._db.execute(
                "SELECT turns_per_hour, calls_per_hour, photos_per_hour, note, updated_at"
                " FROM user_limits WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        turns, calls, photos, note, updated_at = row
        return UserLimits(
            _from_row(turns), _from_row(calls), note, updated_at, photos_per_hour=_from_row(photos)
        )

    def set_user_limits(self, user_id: str, limits: UserLimits | None) -> None:
        """Set the user's own limits, as of now, replacing those they had; None takes them
        off, and the deployment's hold again."""
        with self._lock, self._db:
            if limits is None:
                self._db.execute("DELETE FROM user_limits WHERE user_id = ?", (user_id,))
                return
            self._db.execute(
                "INSERT OR REPLACE INTO user_limits"
                " (user_id, turns_per_hour, calls_per_hour, photos_per_hour, note, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, _to_row(limits.turns_per_hour), _to_row(limits.calls_per_hour),
                 _to_row(limits.photos_per_hour), limits.note, self._clock().isoformat()),
            )

    def last_day(self, user_id: str) -> DayOfUse:
        """The user's uses in the last day, by hour, for the admin to look over."""
        with self._lock:
            rows = self._db.execute(
                "SELECT kind, at, exempt FROM usage WHERE user_id = ? AND at > ? ORDER BY at",
                (user_id, (self._clock() - KEPT).timestamp()),
            ).fetchall()
        hours: dict[datetime, list[tuple[UsageKind, bool]]] = {}
        for kind, at, exempt in rows:
            hour = datetime.fromtimestamp(at, UTC).replace(minute=0, second=0, microsecond=0)
            hours.setdefault(hour, []).append((kind, bool(exempt)))
        return DayOfUse(
            {hour: _tally(uses) for hour, uses in hours.items()},
            _tally([use for uses in hours.values() for use in uses]),
        )

    def close(self) -> None:
        """Close the connection once nothing on another thread is using it."""
        with self._lock:
            self._db.close()

    def _refuse_over(self, user_id: str, kind: UsageKind, now: datetime) -> None:
        """Raise OverLimit if the last hour already holds as many of the user's counting
        `kind` as their limit; under the lock."""
        limits = self._limits()
        deployment = {
            "turn": limits.turns_per_hour,
            "call": limits.calls_per_hour,
            "photo": limits.photos_per_hour,
        }[kind]
        own = self._own_limit(user_id, kind)
        limit = deployment if own is None else None if own == "unlimited" else own
        if limit == 0:
            raise OverLimit(kind, 0, None, now)
        if limit is None:
            return
        recent = [
            at
            for (at,) in self._db.execute(
                "SELECT at FROM usage WHERE user_id = ? AND kind = ? AND NOT exempt"
                " AND at > ? ORDER BY at",
                (user_id, kind, (now - WINDOW).timestamp()),
            )
        ]
        if len(recent) >= limit:
            blocking = recent[len(recent) - limit]  # this one must age out first
            retry_at = datetime.fromtimestamp(blocking, UTC) + WINDOW
            raise OverLimit(kind, limit, retry_at, now)

    def _own_limit(self, user_id: str, kind: UsageKind) -> UserLimit:
        row = self._db.execute(
            f"SELECT {_COLUMNS[kind]} FROM user_limits WHERE user_id = ?", (user_id,)
        ).fetchone()
        return _from_row(row[0]) if row else None

    def _give_back(self, use_id: int) -> None:
        """Forget a use, as if it had never been taken."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM usage WHERE id = ?", (use_id,))


def _to_row(limit: UserLimit) -> int | None:
    return _UNLIMITED_ROW if limit == "unlimited" else limit


def _from_row(value: int | None) -> UserLimit:
    return "unlimited" if value == _UNLIMITED_ROW else value


def _tally(uses: list[tuple[UsageKind, bool]]) -> Tally:
    return Tally(
        turns=sum(kind == "turn" for kind, _ in uses),
        calls=sum(kind == "call" for kind, _ in uses),
        exempt_turns=sum(kind == "turn" and exempt for kind, exempt in uses),
        exempt_calls=sum(kind == "call" and exempt for kind, exempt in uses),
    )
