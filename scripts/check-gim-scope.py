"""Reject removed work-specific content in the maintained application tree.

Historical ADRs, upstream license notices and private local backups are intentionally
outside this check. This does not rewrite Git history or scan user databases.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOVED = (
    "characters/characters.toml",
    "characters/world.json",
    "characters/world-corrections.json",
    "characters/readings.toml",
    "characters/sheets",
    "characters/facts",
    "characters/avatars",
    "characters/avatars-scsp",
    "characters/backgrounds",
    "deploy/story-sync.sh",
    "deploy/stand-sync.sh",
    "deploy/event-names.example.toml",
    "frontend/public/vendor/spine-3.6",
    "frontend/public/landing/phone",
)
MODULES = (
    "story_import", "story_sync", "mirror", "script_cache", "world_sync",
    "live_sync", "release_sync", "setlist_sync", "roster", "sync_tools",
    "stand_fetch", "stand_outfits", "stand_upload",
)
WORK = re.compile(
    r"shinycolors|shiny colors|SCTranslationData|闪耀色彩|閃耀色彩|"
    r"シャイニーカラーズ|SCSP|283PRODUCTION|283プロ|spine_manifest|spine/idols|"
    r"W\.I\.N\.G\.|illumination STARS|櫻木真乃|月岡恋鐘|"
    r"eidolon\s+(?:world\s+sync|stand\s+(?:fetch|outfits|upload)|"
    r"story\s+(?:sync|import-csv|import-json))",
    re.IGNORECASE,
)


def violations(root: Path) -> list[str]:
    errors = []
    for relative in (*REMOVED, *(f"backend/src/eidolon/{m}.py" for m in MODULES)):
        path = root / relative
        if path.is_file() or (path.is_dir() and any(p.is_file() for p in path.rglob("*"))):
            errors.append(f"Removed content returned: {relative}")
    for directory in ("backend/src", "frontend/src", "deploy"):
        for path in (root / directory).rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".sh", ".toml", ".json"}:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if WORK.search(line):
                    errors.append(f"{path.relative_to(root).as_posix()}:{number}: old work reference")
    return errors


def main() -> int:
    errors = violations(ROOT)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("GIM scope passed: no removed work-specific assets, adapters or runtime references.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
