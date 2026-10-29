"""Check the actual Git index or commit, never the ignored local resource tree.

No match values are reported. This guards common accidental disclosures; it does
not assert that arbitrary secrets or copyrighted text can always be recognized.
"""

import argparse
import hashlib
import json
import math
import posixpath
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

POLICY = "release-policy.json"
PRIVATE_ROOTS = (".scratch", "coordination", "corpus", "logs", "docs/research", "backend/data")
PRIVATE_PARTS = {".git", "__pycache__", "node_modules", ".venv", ".next", ".cache", "screenshots"}
PRIVATE_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".csv", ".tsv", ".log", ".dmp", ".dump", ".pyc", ".pyo", ".har",
    ".glb", ".gltf", ".fbx", ".vrm", ".blend", ".obj", ".mtl", ".asset", ".anim",
    ".unity", ".unity3d", ".bundle", ".ab", ".bin", ".bvh", ".vmd", ".usdz",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".webm", ".mp4", ".mov", ".wav", ".flac",
}
TEXT_SECRETS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("provider API key", re.compile(r"\bsk-(?:(?:proj|svcacct|ant-api\d+)-)?[A-Za-z0-9_-]{24,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
)
ASSIGNMENT = re.compile(
    r"\b(?:[A-Z_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|SECRET_ACCESS_KEY|SECRET_KEY|PASSWORD)"
    r"|api_key|access_token|auth_token|client_secret|secret_key|password)[\"']?\s*[:=]\s*"
    r"[\"']([^\"'\n]{24,})[\"']"
)
ENV_ASSIGNMENT = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET)\s*=\s*([^\s#]+)"
)
PLACEHOLDER = re.compile(r"example|test|fake|dummy|fixture|placeholder|your|sample|not.real|<|\$\{", re.I)
PUBLIC_AWS_ID = "AKIA" + "IOSFODNN7EXAMPLE"
PUBLIC_AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def git(root: Path, *args: str, payload: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=payload, capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError(f"Git command failed: {args[0]}")
    return result.stdout


def entries(root: Path, ref: str | None) -> list[tuple[str, str, str]]:
    if ref:
        rows = git(root, "ls-tree", "-rz", "--full-tree", ref).split(b"\0")
    else:
        rows = git(root, "ls-files", "--stage", "-z").split(b"\0")
    found = []
    for row in rows:
        if not row:
            continue
        header, raw_path = row.split(b"\t", 1)
        fields = header.decode("ascii").split()
        mode, oid, stage = (fields[0], fields[2], "0") if ref else fields
        if stage != "0":
            raise ValueError("The index contains unresolved merge conflicts")
        found.append((raw_path.decode("utf-8"), mode, oid))
    return found


def blobs(root: Path, oids: list[str]) -> dict[str, bytes]:
    unique = list(dict.fromkeys(oids))
    if not unique:
        return {}
    data = git(root, "cat-file", "--batch", payload=("\n".join(unique) + "\n").encode())
    cursor = 0
    result = {}
    for oid in unique:
        end = data.index(b"\n", cursor)
        _, kind, size = data[cursor:end].split()
        if kind != b"blob":
            raise ValueError("Only source blobs and local symlinks may be published")
        cursor = end + 1
        length = int(size)
        result[oid] = data[cursor:cursor + length]
        cursor += length + 1
    return result


def private_path(path: str) -> bool:
    p = PurePosixPath(path)
    return (
        any(path == d or path.startswith(d + "/") for d in PRIVATE_ROOTS)
        or bool(set(p.parts) & PRIVATE_PARTS)
        or (p.name.startswith(".env") and p.name != ".env.example")
        or p.suffix.lower() in PRIVATE_SUFFIXES
        or re.search(r"\.(?:db|sqlite|sqlite3)-(?:wal|shm|journal)$", path, re.I) is not None
        or p.name in {"model.json", "animations.json", "Avatar.asset"}
        or re.fullmatch(r"adv_[A-Za-z0-9_-]+\.(?:txt|json)", p.name, re.I) is not None
    )


def secret_findings(path: str, text: str) -> list[dict]:
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in TEXT_SECRETS:
            for match in pattern.finditer(line):
                if path == "backend/tests/test_s3.py" and match.group() == PUBLIC_AWS_ID:
                    continue  # Public AWS signing example; no live credentials.
                findings.append({"path": path, "line": number, "reason": label})
        assignments = list(ASSIGNMENT.finditer(line))
        if PurePosixPath(path).name == ".env.example":
            assignments.extend(ENV_ASSIGNMENT.finditer(line))
        for match in assignments:
            value = match.group(1).strip("\"'")
            if len(value) < 24:
                continue
            if not value.isascii() or PLACEHOLDER.search(value) or value == PUBLIC_AWS_SECRET:
                continue
            counts = Counter(value)
            entropy = -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())
            if entropy >= 3.5:
                findings.append({"path": path, "line": number, "reason": "credential-like literal"})
    return findings


def check(root: Path, ref: str | None = None) -> dict:
    tree = entries(root, ref)
    available = {path: (mode, oid) for path, mode, oid in tree}
    errors = []
    safe = []
    for path, mode, oid in tree:
        if private_path(path):
            errors.append({"path": path, "reason": "local/private resource path"})
        elif mode not in {"100644", "100755", "120000"}:
            errors.append({"path": path, "reason": "unsupported Git object mode"})
        else:
            safe.append((path, mode, oid))
    content = blobs(root, [oid for _, _, oid in safe])
    if POLICY not in available:
        raise ValueError("release-policy.json must be part of the selected Git tree")
    policy = json.loads(content[available[POLICY][1]])
    binary_assets = policy["binary_assets"]
    roots = set(policy["source_roots"])
    root_files = set(policy["root_files"])
    for path, mode, oid in safe:
        data = content[oid]
        if ("/" in path and path.split("/", 1)[0] not in roots) or (
            "/" not in path and path not in root_files
        ):
            errors.append({"path": path, "reason": "outside the source allowlist"})
        if len(data) > policy["max_file_bytes"]:
            errors.append({"path": path, "reason": "file exceeds source size limit"})
        if mode == "120000":
            target = data.decode("utf-8")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
            if (target.startswith(("/", "\\")) or re.match(r"[A-Za-z]:", target)
                    or resolved.startswith("../") or private_path(resolved)):
                errors.append({"path": path, "reason": "symlink escapes repository"})
            continue
        try:
            text = data.decode("utf-8")
            binary = b"\x00" in data
        except UnicodeDecodeError:
            text, binary = "", True
        if path in binary_assets:
            if hashlib.sha256(data).hexdigest() != binary_assets[path]:
                errors.append({"path": path, "reason": "approved UI asset checksum changed"})
        elif binary:
            errors.append({"path": path, "reason": "unapproved binary asset"})
        else:
            errors.extend(secret_findings(path, text))
            if path.endswith(".json") and path != POLICY:
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue  # Format checks belong to the file's owning tool.
                if isinstance(value, dict) and set(value) & {
                    "meshes", "vertices", "skeleton", "episode_lines", "episode_passages", "embeddings"
                }:
                    errors.append({"path": path, "reason": "model/story/vector payload"})
    return {
        "target": ref or "index", "files": len(tree), "approved_ui_assets": len(binary_assets),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="Check this commit instead of the actual Git index")
    parser.add_argument("--report", type=Path, help="Write a metadata-only local JSON report")
    args = parser.parse_args()
    try:
        result = check(Path(__file__).resolve().parents[1], args.ref)
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"Release check failed: {error}", file=sys.stderr)
        return 1
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for error in result["errors"]:
        location = error["path"] + (f":{error['line']}" if "line" in error else "")
        print(f"{location}: {error['reason']}", file=sys.stderr)
    if result["errors"]:
        return 1
    print(f"Release check passed: {result['files']} files; {result['approved_ui_assets']} pinned UI assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
