"""The embedded text set: the vectors of texts that come from configuration, not an
import, kept in SQLite by scope, text and model. The character facts (a scope for each
character) and the work facts (one scope) are searched through it.

The first time a scope is searched, the vectors stored for it are read, those of its
texts not stored yet are embedded (in batches, each committed, so an interrupted run
keeps what it finished) and those of texts no longer among them are forgotten; so an
edited facts file or data file takes effect after a restart without any command and
costs only the changed texts. The scope's vectors are then kept in memory, as its texts
do not change while the server runs, and a scope is loaded only once at a time. Reading
and writing SQLite happen in a thread, off the event loop.

The vectors were once kept in a table for the character facts and another for the work
facts; opening the set moves their rows over and drops them, embedding nothing again.
"""

import asyncio
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path

from eidolon.corpus import REEMBED_BATCH
from eidolon.database import connect
from eidolon.embedding import Document, Embedder, nearest, to_blob

WORK_SCOPE = "work"
"""The scope of the work facts, shared by every character."""
CHARACTER_SCOPES = "character"
"""What every character's scope starts with, for forgetting all of them at once."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embedded_texts (
    scope TEXT NOT NULL,
    text TEXT NOT NULL,
    model TEXT NOT NULL,
    embedding BLOB NOT NULL,
    PRIMARY KEY (scope, model, text)
);
"""


def character_scope(character_id: str) -> str:
    """The scope of a character's facts."""
    return f"{CHARACTER_SCOPES}:{character_id}"


class EmbeddedTexts:
    def __init__(self, path: Path, embedder: Embedder) -> None:
        self._db = connect(path)
        self._lock = threading.Lock()
        self._embedder = embedder
        self._loaded: dict[str, dict[str, bytes]] = {}
        self._loading: dict[str, asyncio.Lock] = {}
        with self._lock:
            self._create()

    def _create(self) -> None:
        """Create the table, moving over the rows of the tables the character facts and
        the work facts were kept in before, if they are still there, so no vector is
        embedded again."""
        self._db.execute("BEGIN IMMEDIATE")  # another process may be migrating too
        try:
            self._db.execute(_SCHEMA)
            old = {
                name
                for (name,) in self._db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                    " AND name IN ('character_facts', 'world_entries')"
                )
            }
            if "character_facts" in old:
                self._db.execute(
                    "INSERT OR IGNORE INTO embedded_texts (scope, text, model, embedding)"
                    " SELECT ? || ':' || character_id, text, model, embedding"
                    " FROM character_facts",
                    (CHARACTER_SCOPES,),
                )
                self._db.execute("DROP TABLE character_facts")
            if "world_entries" in old:
                self._db.execute(
                    "INSERT OR IGNORE INTO embedded_texts (scope, text, model, embedding)"
                    " SELECT ?, text, model, embedding FROM world_entries",
                    (WORK_SCOPE,),
                )
                self._db.execute("DROP TABLE world_entries")
        except BaseException:
            self._db.rollback()
            raise
        self._db.commit()

    async def search(
        self,
        scope: str,
        documents: Sequence[Document],
        query_vector: Sequence[float],
        limit: int,
        among: Sequence[int] | None = None,
    ) -> list[tuple[int, float]]:
        """The positions in `documents` (the scope's texts, all of them) of those most
        similar to a query embedded with this set's embedder, best first, with their
        similarity; only those at the positions `among`, if given."""
        vectors = await self._load(scope, documents)
        positions = range(len(documents)) if among is None else among
        best = await asyncio.to_thread(
            nearest, [vectors[i] for i in positions], query_vector, limit
        )
        return [(positions[i], similarity) for i, similarity in best]

    async def embed_missing(
        self, scope: str, documents: Sequence[Document], batch: int = REEMBED_BATCH
    ) -> int:
        """Embed those of `documents` that have no vector from this set's embedder yet,
        `batch` at a time; returns how many that was."""
        _, embedded = await self._vectors(scope, documents, batch)
        return embedded

    def forget_other_models(self, scopes: str) -> int:
        """Drop every vector of `scopes` (a scope, or `CHARACTER_SCOPES` for every
        character's) not from this set's embedder; returns how many there were."""
        with self._lock, self._db:
            return self._db.execute(
                "DELETE FROM embedded_texts WHERE (scope = ? OR scope LIKE ? || ':%')"
                " AND model != ?",
                (scopes, scopes, self._embedder.model),
            ).rowcount

    def close(self) -> None:
        self._db.close()

    async def _load(self, scope: str, documents: Sequence[Document]) -> list[bytes]:
        """The vector of each of `documents`, in order."""
        vectors, _ = await self._vectors(scope, documents)
        return [vectors[d.text] for d in documents]

    async def _vectors(
        self, scope: str, documents: Sequence[Document], batch: int = REEMBED_BATCH
    ) -> tuple[dict[str, bytes], int]:
        """The vectors of the scope's texts, by text, embedding those not yet stored (in
        batches, each committed); and how many it embedded. Loaded once per scope, then
        kept in memory."""
        async with self._loading.setdefault(scope, asyncio.Lock()):
            if (loaded := self._loaded.get(scope)) is not None:
                return loaded, 0
            model = self._embedder.model
            stored = await asyncio.to_thread(self._stored, scope, model)
            missing = list({d.text: d for d in documents if d.text not in stored}.values())
            if stale := stored.keys() - {d.text for d in documents}:
                await asyncio.to_thread(self._forget, scope, model, stale)
                stored = {t: v for t, v in stored.items() if t not in stale}
            for start in range(0, len(missing), batch):
                texts = missing[start : start + batch]
                embedded = await self._embedder.embed_documents(texts)
                rows = [
                    (scope, d.text, model, to_blob(v)) for d, v in zip(texts, embedded, strict=True)
                ]
                await asyncio.to_thread(self._save, rows)
                stored.update((text, blob) for _, text, _, blob in rows)
            self._loaded[scope] = stored
            return stored, len(missing)

    def _stored(self, scope: str, model: str) -> dict[str, bytes]:
        with self._lock:
            return dict(
                self._db.execute(
                    "SELECT text, embedding FROM embedded_texts WHERE scope = ? AND model = ?",
                    (scope, model),
                ).fetchall()
            )

    def _forget(self, scope: str, model: str, texts: Iterable[str]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "DELETE FROM embedded_texts WHERE scope = ? AND model = ? AND text = ?",
                [(scope, model, t) for t in texts],
            )

    def _save(self, rows: Sequence[tuple[str, str, str, bytes]]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO embedded_texts (scope, text, model, embedding)"
                " VALUES (?, ?, ?, ?)",
                rows,
            )
