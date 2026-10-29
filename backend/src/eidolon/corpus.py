"""The story corpus: episodes the characters can recall, and their vector index.

Each episode is keyed by its source identifier (the game script it came from), so
saving the same episode again replaces it. Each episode also records the format it was
imported from, so an import can leave alone a better version from another. Episodes
are split into passages of consecutive lines; each passage is embedded and searched
by cosine similarity, only among the episodes the asking character is in the cast of. Passages whose
text has not changed keep their vectors, so re-importing costs no embedding calls.
An episode with no cast is kept but not embedded: no character could recall it.

Each passage keeps one vector, from the embedding model it was last embedded with;
only passages embedded with the current model are searched. After the model changes,
`embed_missing` re-embeds the rest from their stored text (`eidolon reembed`).

The story catalog is read from the same tables: each character's episodes, grouped
by the card or event they belong to, so it is always in step with the last import.

Episodes live in a detachable local SQLite story library, separate from user data.
The library and its vectors stay out of the repository.
"""

import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import typing
from pathlib import Path
from typing import Literal

from eidolon.database import connect
from eidolon.embedding import Document, Embedder, NoEmbedder, nearest, to_blob

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    imported_from TEXT NOT NULL DEFAULT 'csv',
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episode_cast (
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    character_id TEXT NOT NULL,
    PRIMARY KEY (episode_id, character_id)
);
CREATE INDEX IF NOT EXISTS episode_cast_by_character ON episode_cast(character_id);
CREATE TABLE IF NOT EXISTS episode_lines (
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    speaker TEXT,
    ja TEXT NOT NULL,
    zh TEXT,
    PRIMARY KEY (episode_id, seq)
);
CREATE TABLE IF NOT EXISTS episode_passages (
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    model TEXT NOT NULL,
    embedding BLOB NOT NULL,
    PRIMARY KEY (episode_id, seq)
);
"""

_PASSAGE_CHARS = 1200
"""Roughly how much text goes into one passage before a new one starts."""
REEMBED_BATCH = 200
"""How many passages (or memories) `eidolon reembed` embeds before committing them."""


ImportFormat = Literal["csv", "json", "gim-csv", "gim-conditional-csv"]
"""Legacy format values remain readable for existing private databases. New imports use GIM formats."""


@dataclass(frozen=True)
class Line:
    """One line of dialogue; `speaker` is None for narration."""

    speaker: str | None
    ja: str
    zh: str | None = None


@dataclass(frozen=True)
class Episode:
    id: str
    """The source identifier, e.g. `produce_events/100100101`."""
    category: str
    source: str
    """The card or event the episode belongs to."""
    title: str
    cast: frozenset[str]
    """Identifiers of the configured characters who appear in it."""
    lines: tuple[Line, ...]
    imported_from: ImportFormat = "csv"


@dataclass(frozen=True)
class CatalogEntry:
    """One episode in the story catalog."""

    episode_id: str
    title: str


@dataclass(frozen=True)
class CatalogSource:
    """A card or event in the story catalog, with the episodes one character is cast in."""

    category: str
    source: str
    episodes: tuple[CatalogEntry, ...]


@dataclass(frozen=True)
class Passage:
    episode: Episode
    text: str
    score: float


class StoryCorpus:
    def __init__(self, path: Path, embedder: Embedder) -> None:
        self._db = connect(path)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._embedder = embedder
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)
            columns = {r["name"] for r in self._db.execute("PRAGMA table_info(episodes)")}
            if "imported_from" not in columns:  # corpora from before JSON import were all CSV
                self._db.execute(
                    "ALTER TABLE episodes ADD COLUMN imported_from TEXT NOT NULL DEFAULT 'csv'"
                )

    async def save(self, episodes: list[Episode]) -> int:
        """Save episodes; NoEmbedder retains pending text without making fake vectors.

        Pending passages use an empty model/blob, are excluded from search, and can
        later be embedded by `embed_missing` with a configured embedder.
        """
        passages = {e.id: _passages(e) if e.cast else [] for e in episodes}
        titles = {t: passage_title(e.source, e.title) for e in episodes for t in passages[e.id]}
        offline = isinstance(self._embedder, NoEmbedder)
        known = self._known_vectors(list(passages), offline=offline)
        missing = sorted(titles.keys() - known.keys())
        if missing and not offline:
            vectors = await self._embedder.embed_documents(
                [Document(t, titles[t]) for t in missing]
            )
            known.update(zip(
                missing, ((self._embedder.model, to_blob(v)) for v in vectors), strict=True
            ))

        now = datetime.now(UTC).isoformat()
        with self._lock, self._db:
            for episode in episodes:
                self._delete(episode.id)
                self._db.execute(
                    "INSERT INTO episodes (id, category, source, title, imported_from, imported_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        episode.id,
                        episode.category,
                        episode.source,
                        episode.title,
                        episode.imported_from,
                        now,
                    ),
                )
                self._db.executemany(
                    "INSERT INTO episode_cast (episode_id, character_id) VALUES (?, ?)",
                    [(episode.id, c) for c in sorted(episode.cast)],
                )
                self._db.executemany(
                    "INSERT INTO episode_lines (episode_id, seq, speaker, ja, zh)"
                    " VALUES (?, ?, ?, ?, ?)",
                    [(episode.id, i, line.speaker, line.ja, line.zh) for i, line in enumerate(episode.lines)],
                )
                self._db.executemany(
                    "INSERT INTO episode_passages (episode_id, seq, text, model, embedding)"
                    " VALUES (?, ?, ?, ?, ?)",
                    [
                        (episode.id, i, text, *known.get(text, ("", b"")))
                        for i, text in enumerate(passages[episode.id])
                    ],
                )
        return 0 if offline else len(missing)

    def remove(self, episode_id: str) -> bool:
        """Remove an episode if present; returns whether it was."""
        with self._lock, self._db:
            return self._delete(episode_id)

    def get(self, episode_id: str) -> Episode | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
            return self._episode(row) if row else None

    def imported_from(self, episode_id: str) -> ImportFormat | None:
        """The format an episode was imported from, or None if it is not in the corpus."""
        with self._lock:
            row = self._db.execute(
                "SELECT imported_from FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone()
            return typing.cast(ImportFormat, row["imported_from"]) if row else None

    def episode_ids(self, prefix: str = "") -> list[str]:
        """The identifiers of the episodes whose identifier starts with `prefix`, in order."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id FROM episodes WHERE substr(id, 1, ?) = ? ORDER BY id",
                (len(prefix), prefix),
            ).fetchall()
            return [row["id"] for row in rows]

    def list_episodes(self, character_id: str | None = None) -> list[Episode]:
        """All episodes, or those `character_id` appears in, ordered by source identifier."""
        with self._lock:
            if character_id is None:
                rows = self._db.execute("SELECT * FROM episodes ORDER BY id").fetchall()
            else:
                rows = self._db.execute(
                    "SELECT e.* FROM episodes e JOIN episode_cast c ON c.episode_id = e.id"
                    " WHERE c.character_id = ? ORDER BY e.id",
                    (character_id,),
                ).fetchall()
            return [self._episode(row) for row in rows]

    def catalog(self, character_id: str) -> list[CatalogSource]:
        """The story catalog for one character: character → card or event → episode.

        Cards and events come in the order of their first episode, episodes in
        source identifier order, which is the order the game numbers them in.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT e.id, e.category, e.source, e.title FROM episodes e"
                " JOIN episode_cast c ON c.episode_id = e.id"
                " WHERE c.character_id = ? ORDER BY e.id",
                (character_id,),
            ).fetchall()
        sources: dict[tuple[str, str], list[CatalogEntry]] = {}
        for row in rows:
            sources.setdefault((row["category"], row["source"]), []).append(
                CatalogEntry(row["id"], row["title"])
            )
        return [
            CatalogSource(category, source, tuple(entries))
            for (category, source), entries in sources.items()
        ]

    async def search(self, query: str, character_id: str, limit: int = 5) -> list[Passage]:
        """The passages most similar to `query`, from episodes `character_id` appears in."""
        if isinstance(self._embedder, NoEmbedder):
            return []
        return self.search_by_vector(await self._embedder.embed_query(query), character_id, limit)

    def search_by_vector(
        self, query_vector: Sequence[float], character_id: str, limit: int = 5
    ) -> list[Passage]:
        """Like `search`, for a query already embedded with this corpus's embedder."""
        with self._lock:
            rows = self._db.execute(
                "SELECT p.episode_id, p.text, p.embedding FROM episode_passages p"
                " JOIN episode_cast c ON c.episode_id = p.episode_id"
                " WHERE c.character_id = ? AND p.model = ? AND length(p.embedding) > 0",
                (character_id, self._embedder.model),
            ).fetchall()
        best = nearest([r["embedding"] for r in rows], query_vector, limit)
        episodes: dict[str, Episode] = {}
        passages = []
        for i, score in best:
            episode_id = rows[i]["episode_id"]
            if episode_id not in episodes:
                episode = self.get(episode_id)
                assert episode is not None
                episodes[episode_id] = episode
            passages.append(Passage(episodes[episode_id], rows[i]["text"], score))
        return passages

    def count_missing_vectors(self) -> int:
        """How many passages have no vector from this corpus's embedder, and so cannot be
        found: those embedded before the embedding service, model or dimensions changed."""
        with self._lock:
            if isinstance(self._embedder, NoEmbedder):
                return self._db.execute(
                    "SELECT count(*) FROM episode_passages WHERE length(embedding) = 0"
                ).fetchone()[0]
            return self._db.execute(
                "SELECT count(*) FROM episode_passages WHERE model != ? OR length(embedding) = 0",
                (self._embedder.model,)
            ).fetchone()[0]

    async def embed_missing(
        self, batch: int = REEMBED_BATCH, progress: Callable[[int], None] | None = None
    ) -> int:
        """Re-embed, from their stored text, the passages that have no vector from this
        corpus's embedder, replacing their old vectors (a passage keeps only one), `batch`
        at a time; returns how many it embedded, telling `progress` the count so far after
        each batch. Interrupted, what it finished is kept. A passage an import rewrites
        meanwhile is left to the import, and not counted."""
        model = self._embedder.model
        done = 0
        after = ("", -1)
        while True:
            with self._lock:
                rows = self._db.execute(
                    "SELECT p.episode_id, p.seq, p.text, e.source, e.title"
                    " FROM episode_passages p JOIN episodes e ON e.id = p.episode_id"
                    " WHERE (p.model != ? OR length(p.embedding) = 0)"
                    " AND (p.episode_id, p.seq) > (?, ?)"
                    " ORDER BY p.episode_id, p.seq LIMIT ?",
                    (model, *after, batch),
                ).fetchall()
            if not rows:
                return done
            vectors = await self._embedder.embed_documents(
                [Document(r["text"], passage_title(r["source"], r["title"])) for r in rows]
            )
            with self._lock, self._db:
                updated = self._db.executemany(
                    "UPDATE episode_passages SET model = ?, embedding = ?"
                    " WHERE episode_id = ? AND seq = ? AND text = ?",
                    [
                        (model, to_blob(v), r["episode_id"], r["seq"], r["text"])
                        for r, v in zip(rows, vectors, strict=True)
                    ],
                )
            done += updated.rowcount
            after = (rows[-1]["episode_id"], rows[-1]["seq"])
            if progress is not None:
                progress(done)

    def close(self) -> None:
        self._db.close()

    def _known_vectors(
        self, episode_ids: list[str], *, offline: bool
    ) -> dict[str, tuple[str, bytes]]:
        """Keep each vector's model; an offline edit preserves unchanged passages.

        Online imports reuse only their configured model. Offline imports have no
        replacement model, so retain the existing model instead of discarding it.
        """
        with self._lock:
            known = {}
            for episode_id in episode_ids:
                for row in self._db.execute(
                    "SELECT text, model, embedding FROM episode_passages"
                    " WHERE episode_id = ? AND (model = ? OR ?) AND length(embedding) > 0",
                    (episode_id, self._embedder.model, offline),
                ):
                    known[row["text"]] = (row["model"], row["embedding"])
            return known

    def _delete(self, episode_id: str) -> bool:
        """Its cast, lines and passages go with it (ON DELETE CASCADE)."""
        return self._db.execute("DELETE FROM episodes WHERE id = ?", (episode_id,)).rowcount > 0

    def _episode(self, row: sqlite3.Row) -> Episode:
        episode_id = row["id"]
        cast = self._db.execute(
            "SELECT character_id FROM episode_cast WHERE episode_id = ?", (episode_id,)
        ).fetchall()
        lines = self._db.execute(
            "SELECT speaker, ja, zh FROM episode_lines WHERE episode_id = ? ORDER BY seq",
            (episode_id,),
        ).fetchall()
        return Episode(
            id=episode_id,
            category=row["category"],
            source=row["source"],
            title=row["title"],
            cast=frozenset(r["character_id"] for r in cast),
            lines=tuple(Line(r["speaker"], r["ja"], r["zh"]) for r in lines),
            imported_from=typing.cast(ImportFormat, row["imported_from"]),
        )


def passage_title(source: str, title: str) -> str:
    """Where a passage comes from: its episode's card or event, and the episode's title."""
    return f"{source}「{title}」"


def _passages(episode: Episode) -> list[str]:
    """Consecutive lines grouped into passages, each headed by where it comes from."""
    header = passage_title(episode.source, episode.title) + "\n"
    passages: list[str] = []
    current: list[str] = []
    size = 0
    for line in episode.lines:
        text = f"{line.speaker}：{line.ja}" if line.speaker else line.ja
        if line.zh:
            text += f"（{line.zh}）"
        if current and size + len(text) > _PASSAGE_CHARS:
            passages.append(header + "\n".join(current))
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        passages.append(header + "\n".join(current))
    return passages

