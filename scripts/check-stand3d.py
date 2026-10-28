"""Asset-free Stand3D pipeline checks for developer machines and CI."""

import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts/stand3d"


def run(*arguments):
    print("Running:", *map(str, arguments), flush=True)
    subprocess.run([str(value) for value in arguments], cwd=ROOT, check=True)


def main():
    # Check source/configuration without opening corpus, Unity or node_modules.
    for source in sorted(TOOLS.rglob("*.py")):
        ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
    for profile in sorted((TOOLS / "profiles").glob("*.json")):
        json.loads(profile.read_text(encoding="utf-8-sig"))
    # These are dynamically imported by browser module URL; frontend typecheck
    # alone cannot detect a checkout that omitted the generator's dependencies.
    for name in (
        "Stand3DEngine",
        "Stand3DBodyMotion",
        "Stand3DGesture",
        "Stand3DHandContact",
    ):
        source = ROOT / "frontend/src/components/conversations/stand" / (name + ".ts")
        if not source.is_file():
            raise FileNotFoundError(
                f"Required product runtime is not versioned: {source}"
            )
    for source in sorted(TOOLS.glob("*.mjs")):
        run("node", "--check", source)
    run(sys.executable, TOOLS / "pipeline.py", "--help")
    run(sys.executable, "-m", "unittest", "discover", "-s", TOOLS / "tests", "-v")
    print("Stand3D asset-free checks passed.", flush=True)


if __name__ == "__main__":
    main()
