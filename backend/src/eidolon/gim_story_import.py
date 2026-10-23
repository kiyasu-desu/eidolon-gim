"""Local Gakuen CSV adapter. No SC identifiers, categories or failure heuristics.

The converted CSV has no branch targets. Choices are audit data, never dialogue.
Reviewed canonical experiences and explicitly qualified conditional material enter
the recall corpus with distinct import formats.
"""

import csv
import hashlib
import io
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eidolon.characters import Character
from eidolon.corpus import Episode, Line, StoryCorpus
from eidolon.embedding import EmbeddingError

_SCRIPT = re.compile(r"adv_[A-Za-z0-9_-]+\.txt")
_RUBY = re.compile(r"<r(?:\\)?=[^<>]*>(.*?)</r>", re.DOTALL)
_CONTROL = re.compile(r"[<>{}]|\\[A-Za-z=]|__[A-Za-z_]+__")


@dataclass
class Choice:
    row: int
    text: str
    translation: str | None
    target: str = "unknown"


@dataclass
class FileReport:
    path: str
    sha256: str = ""
    source_id: str | None = None
    outcome: str = "unknown"
    status: str = "error"
    valid_lines: int = 0
    line_rows: list[int] = field(default_factory=list)
    speakers: dict[str, int] = field(default_factory=dict)
    cast: list[str] = field(default_factory=list)
    choices: list[list[Choice]] = field(default_factory=list)
    unknown_controls: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class GimImportReport:
    root: str
    source_url: str = ""
    version: str = ""
    usage_conditions: str = ""
    index_sha256: str | None = None
    manifest_sha256: str | None = None
    imported: int = 0
    unchanged: int = 0
    skipped_failures: int = 0
    unknown_outcomes: int = 0
    removed: int = 0
    embedded_passages: int = 0
    pending_passages: int = 0
    errors: list[str] = field(default_factory=list)
    files: list[FileReport] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def has_errors(self) -> bool:
        return bool(self.errors or any(f.errors for f in self.files))


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(path: Path) -> tuple[dict[str, object], str]:
    data = path.read_bytes()
    value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_object)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value, hashlib.sha256(data).hexdigest()


def _script(value: str) -> str:
    if not _SCRIPT.fullmatch(value):
        raise ValueError(f"invalid source identifier {value!r}; expected adv_*.txt")
    return value


def _inside(root: Path, value: str) -> Path:
    path = root / value
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes CSV root: {value}")
    if not path.is_file():
        raise ValueError(f"missing CSV file: {value}")
    if path.suffix.lower() != ".csv":
        raise ValueError(f"not a CSV file: {value}")
    return resolved


def _clean(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace(r"\n", "\n")
    value = value.replace("{user}", "制作人")
    value = _RUBY.sub(r"\1", value)
    return value.replace("<em>", "").replace("</em>", "").strip()


def _csv_files(root: Path, report: GimImportReport) -> list[Path]:
    """Inspect directory links too, without following an escape or directory cycle."""
    pending = [root]
    visited: set[Path] = set()
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    raise ValueError("path escapes CSV root (including directory links)")
                if path.is_dir():
                    if resolved in visited or resolved == root:
                        raise ValueError("duplicate directory alias or cycle")
                    visited.add(resolved)
                    pending.append(path)
                elif path.suffix.lower() == ".csv":
                    files.append(path)
            except (OSError, ValueError) as error:
                report.files.append(FileReport(path.relative_to(root).as_posix(), errors=[str(error)]))
    return sorted(files)


def _read(path: Path, indexed: str | None, entry: FileReport) -> tuple[str, list[Line]]:
    data = path.read_bytes()
    entry.sha256 = hashlib.sha256(data).hexdigest()
    # newline='' is required for CSV's quoted multiline fields and physical row numbers.
    with io.StringIO(data.decode("utf-8-sig"), newline="") as stream:
        reader = csv.reader(stream, strict=True)
        rows: list[tuple[int, list[str]]] = []
        while True:
            start = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) != 4:
                raise ValueError(f"row {start}: expected 4 columns, got {len(row)}")
            rows.append((start, [cell.strip() for cell in row]))
    if not rows or rows[0][1] != ["id", "name", "text", "trans"]:
        raise ValueError("missing id,name,text,trans header or empty CSV")
    info = {_script(row[1]) for _, row in rows[1:] if row[0] == "info"}
    if len(info) > 1:
        raise ValueError("contradictory info rows")
    source = next(iter(info), indexed)
    if source is None:
        raise ValueError("missing info source and validated index mapping")
    entry.source_id = f"gim/{source}"
    if indexed is not None and indexed != source:
        raise ValueError(f"info/index conflict: {source} != {indexed}")
    lines: list[Line] = []
    title = source.removesuffix(".txt")
    adjacent_choice = False
    for number, (line_id, speaker, original, translated) in rows[1:]:
        if line_id in ("info", "译者"):
            adjacent_choice = False
            continue
        text, translation, speaker = _clean(original), _clean(translated), _clean(speaker)
        if _CONTROL.search(text) or _CONTROL.search(translation) or (
            speaker not in ("__narration__", "__title__") and _CONTROL.search(speaker)
        ):
            entry.unknown_controls.append(number)
            entry.errors.append(f"row {number}: unknown control marker; file withheld")
            adjacent_choice = False
            continue
        if line_id == "select":
            if not adjacent_choice:
                entry.choices.append([])
            entry.choices[-1].append(Choice(number, text, translation or None))
            adjacent_choice = True
            continue
        adjacent_choice = False
        if speaker == "__title__":
            title = text or title
        elif text:
            lines.append(Line(None if speaker == "__narration__" else speaker or None,
                              text, translation or None))
            entry.line_rows.append(number)
    entry.valid_lines = len(lines)
    entry.speakers = dict(Counter(line.speaker or "__narration__" for line in lines))
    if not lines:
        raise ValueError("CSV has no dialogue/narration lines")
    return title, lines


def _validate_conditional(
    meta: dict[str, object], source: str, entry: FileReport, lines: list[Line],
) -> None:
    restoration = meta.get("branch_restoration")
    entries = restoration.get("entries") if isinstance(restoration, dict) else None
    evidence = entries.get(source) if isinstance(entries, dict) else None
    if not isinstance(evidence, dict):
        raise ValueError("conditional outcome requires branch_restoration.entries source evidence")
    for key in ("raw_sha256", "graph_sha256", "csv_sha256"):
        value = evidence.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError(f"conditional evidence requires 64-hex {key}")
    if evidence["csv_sha256"].lower() != entry.sha256:
        raise ValueError("conditional evidence csv_sha256 does not match CSV bytes")
    for line in lines:
        if not line.ja.startswith("【条件情境・未确认实际触发："):
            raise ValueError("conditional dialogue requires a per-message unconfirmed scenario label")
        if any(part.strip() in ("制作人", "プロデューサー")
               for part in re.split(r"[＆&]", line.speaker or "")):
            raise ValueError("conditional dialogue must exclude producer statements")


async def import_gim_directory(
    directory: Path,
    corpus: StoryCorpus,
    characters: Iterable[Character],
    *,
    manifest: Path,
    index: Path | None = None,
) -> GimImportReport:
    """Validate first, then save each valid canonical episode independently.

    Invalid global index/manifest prevents every mutation. Invalid files and duplicate
    identities leave their previous episodes intact. Unknown outcomes are withheld;
    when reclassified unknown, an earlier import is removed from recall as well.
    """
    root = directory.resolve()
    report = GimImportReport(str(root))
    indexed: dict[Path, str] = {}
    outcomes: dict[str, str] = {}
    try:
        if not root.is_dir():
            raise ValueError(f"missing CSV root: {root}")
        meta, report.manifest_sha256 = _json(manifest)
        for key in ("source_url", "version", "usage_conditions"):
            value = meta.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"manifest requires nonempty {key}")
            setattr(report, key, value)
        episodes = meta.get("episodes", {})
        if not isinstance(episodes, dict):
            raise ValueError("manifest episodes must map adv_*.txt to canon/conditional/failure/unknown")
        for source, outcome in episodes.items():
            _script(source)
            if outcome not in ("canon", "conditional", "failure", "unknown"):
                raise ValueError(f"invalid outcome for {source}: {outcome!r}")
            assert isinstance(outcome, str)
            outcomes[source] = outcome
        if index is not None:
            mappings, report.index_sha256 = _json(index)
            for source, relative in mappings.items():
                _script(source)
                if not isinstance(relative, str):
                    raise ValueError(f"index path is not a string: {source}")
                path = _inside(root, relative)
                if path in indexed:
                    raise ValueError(f"multiple source IDs map to {relative}")
                indexed[path] = source
    except (OSError, ValueError, UnicodeError) as error:
        report.errors.append(str(error))
        return report

    aliases = {re.sub(r"\s+", "", name): c.id for c in characters for name in c.speakers}
    pending: list[tuple[FileReport, Episode]] = []
    identities: dict[str, list[FileReport]] = {}
    try:
        files = _csv_files(root, report)
    except OSError as error:
        report.errors.append(str(error))
        return report
    for path in files:
        entry = FileReport(path.relative_to(root).as_posix())
        report.files.append(entry)
        try:
            safe = _inside(root, entry.path)
            if safe in indexed:
                entry.source_id = f"gim/{indexed[safe]}"
            title, lines = _read(safe, indexed.get(safe), entry)
            assert entry.source_id is not None
            source = entry.source_id.removeprefix("gim/")
            entry.outcome = outcomes.get(source, "unknown")
            if entry.outcome == "conditional":
                _validate_conditional(meta, source, entry, lines)
            cast = frozenset(
                aliases[name] for line in lines
                for part in re.split(r"[＆&]", line.speaker or "")
                if (name := re.sub(r"\s+", "", part)) in aliases
            )
            entry.cast = sorted(cast)
            pending.append((entry, Episode(entry.source_id, "学园剧情", source, title, cast,
                                           tuple(lines), "gim-conditional-csv" if entry.outcome == "conditional" else "gim-csv")))
        except (OSError, ValueError, UnicodeError, csv.Error) as error:
            entry.errors.append(str(error))
        if entry.source_id:
            identities.setdefault(entry.source_id, []).append(entry)
    if not report.files:
        report.errors.append("no CSV files under root")
    for source, entries in identities.items():
        if len(entries) > 1:
            for entry in entries:
                entry.errors.append(f"duplicate source {source}: " + ", ".join(e.path for e in entries))
    for entry, episode in pending:
        if entry.errors:
            continue
        if entry.outcome not in ("canon", "conditional"):
            if entry.outcome == "failure":
                report.skipped_failures += 1
                entry.status = "skipped_failure"
            else:
                report.unknown_outcomes += 1
                entry.status = "pending_outcome"
            if corpus.remove(episode.id):
                report.removed += 1
            continue
        if corpus.get(episode.id) == episode:
            report.unchanged += 1
            entry.status = "unchanged"
        else:
            try:
                report.embedded_passages += await corpus.save([episode])
            except (EmbeddingError, sqlite3.Error, ValueError) as error:
                # save embeds before its transaction: preserve the previous episode.
                entry.errors.append(f"save failed: {error}")
                continue
            report.imported += 1
            entry.status = "imported"
    report.pending_passages = corpus.count_missing_vectors()
    return report
