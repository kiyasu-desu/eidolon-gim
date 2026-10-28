"""Rebuild, calibrate, accept and package an exported Stand3D outfit.

Python owns native metadata (including 64-bit Unity IDs) and file transactions.
Node owns Three.js composition and acceptance against the actual product engine.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def workspace(path):
    path = Path(path).resolve()
    require(
        path.is_relative_to(ROOT) and path != ROOT,
        f"Path must be inside the workspace: {path}",
    )
    require(
        not any(
            p in {".git", ".agents", ".codex", ".aws"}
            for p in path.relative_to(ROOT).parts
        ),
        "Protected workspace path",
    )
    return path


def member(folder, relative):
    path = (Path(folder) / relative).resolve()
    require(
        path.is_relative_to(Path(folder).resolve()) and path != Path(folder).resolve(),
        f"Invalid relative path: {relative}",
    )
    return path


def copy(source, target):
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def files(folder):
    return {
        p.relative_to(folder).as_posix(): sha(p)
        for p in sorted(Path(folder).rglob("*"))
        if p.is_file()
    }


def check_files(folder, expected):
    for name, expected_sha in expected.items():
        path = member(folder, name)
        require(
            path.is_file() and sha(path) == expected_sha,
            f"File missing or changed: {path}",
        )


def code_hashes():
    paths = [
        p
        for p in HERE.rglob("*")
        if p.suffix in {".py", ".mjs", ".cs"} and "tests" not in p.parts
    ]
    paths += [
        p
        for p in (ROOT / "frontend/src/components/conversations/stand").glob(
            "Stand3D*.ts"
        )
        if ".test." not in p.name
    ]
    paths += [ROOT / "frontend/src/lib/stand3d.ts", ROOT / "frontend/package-lock.json"]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


@contextlib.contextmanager
def lock():
    path = ROOT / "corpus/gim-assets/pipeline/.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(
            f"Pipeline lock exists; inspect its PID before removing a stale lock: {path}"
        ) from None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def command(args, log, timeout=900):
    print("Running:", Path(str(args[0])).name, *[str(v) for v in args[1:3]], flush=True)
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
    with Path(log).open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            [str(a) for a in args],
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            startupinfo=startup,
        )
    require(result.returncode == 0, f"Command failed ({result.returncode}); see {log}")


def snapshot(profile, run):
    require(profile["version"] == 1, "Unsupported pipeline profile")
    require(
        profile["unity"]["sampleRate"] == 30, "This bake implementation supports 30Hz"
    )
    assets = workspace(ROOT / profile["assets"]["path"])
    check_files(assets, profile["assets"]["files"])
    for name in profile["assets"]["files"]:
        copy(member(assets, name), member(run / "inputs/assets", name))
    for kind in ["reference", "avatarProfile"]:
        source = workspace(ROOT / profile[kind]["path"])
        require(sha(source) == profile[kind]["sha256"], f"{kind} SHA mismatch")
        copy(source, run / "inputs" / (kind + ".json"))
    for clip in profile["clips"]:
        source = workspace(ROOT / clip["path"])
        require(sha(source) == clip["sha256"], f"Clip SHA mismatch: {clip['name']}")
        copy(source, run / "inputs/bundles" / (clip["name"] + ".unity3d"))
    write(run / "profile.json", profile)


def bake_fingerprint(profile):
    return digest(
        {
            "avatar": profile["avatarProfile"]["sha256"],
            "reference": profile["reference"]["sha256"],
            "clips": [(c["name"], c["sha256"]) for c in profile["clips"]],
            "unity": profile["unity"],
            "probe": files(HERE / "unity"),
        }
    )


def bake(profile, run, editor, cache):
    output = run / "bakes"
    output.mkdir()
    origin = "fresh-editor-execution"
    if cache:
        cache = workspace(cache)
        if (cache / "manifest.json").exists():
            manifest = read(cache / "manifest.json")
            require(
                manifest["fingerprint"] == bake_fingerprint(profile),
                "Bake cache inputs/editor/probe do not match",
            )
            expected = manifest["files"]
            origin = "verified-pipeline-cache"
        else:
            approved = profile["approvedBakeCache"]
            require(
                cache == workspace(ROOT / approved["path"]),
                "Unregistered historical bake cache",
            )
            expected = approved["files"]
            origin = "pinned-historical-capture"
        check_files(cache, expected)
        for name in expected:
            copy(member(cache, name), member(output, name))
    else:
        require(
            editor and Path(editor).is_file(),
            "Provide --editor, or --reuse-bakes with a verified cache",
        )
        project = run / "unity-project"
        for name in [
            "Assets/Editor",
            "Assets/StreamingAssets/Reference",
            "Packages",
            "ProjectSettings",
        ]:
            (project / name).mkdir(parents=True, exist_ok=True)
        for source in (HERE / "unity").glob("*.cs"):
            copy(source, project / "Assets/Editor" / source.name)
        copy(
            run / "inputs/reference.json",
            project / "Assets/StreamingAssets/Reference/reference.json",
        )
        write(
            project / "Packages/manifest.json",
            {
                "dependencies": {
                    f"com.unity.modules.{n}": "1.0.0"
                    for n in ["animation", "assetbundle", "jsonserialize"]
                }
            },
        )
        (project / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: " + profile["unity"]["editorVersion"] + "\n",
            encoding="utf-8",
        )
        avatar = read(run / "inputs/avatarProfile.json")
        request = dict(
            profileSHA256=profile["avatarProfile"]["sha256"],
            referenceSHA256=profile["reference"]["sha256"],
            resourceVersion=profile["unity"]["resourceVersion"],
            expectedEditor=profile["unity"]["editorVersion"],
            boneMap=[
                dict(boneName=k, humanName=v)
                for k, v in avatar["boneToHumanName"].items()
            ],
            humanDescription=avatar["humanDescription"],
            cmmnHipsHeight=avatar["heightConstants"]["CmmnHipsHeight"],
            clips=[
                dict(
                    name=c["name"],
                    sha256=c["sha256"],
                    path=str(run / "inputs/bundles" / (c["name"] + ".unity3d")),
                )
                for c in profile["clips"]
            ],
        )
        write(output / "request.json", request)
        if os.name == "nt":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "if(Get-Process Unity -ErrorAction SilentlyContinue){exit 1}",
                ],
                capture_output=True,
            )
            require(result.returncode == 0, "Another Unity Editor is running")
        command(
            [
                editor,
                "-batchmode",
                "-force-d3d11",
                "-projectPath",
                project,
                "-executeMethod",
                "StandModelBake.Run",
                "-pipelineRequest",
                output / "request.json",
                "-pipelineOutput",
                output,
                "-logFile",
                run / "logs/unity-editor.log",
            ],
            run / "logs/unity-process.log",
        )
        copy(
            project / "Assets/AvatarRebuild/Temari-campus.asset",
            output / "Avatar.asset",
        )
    report = read(output / "avatar-rebuild-report.json")
    require(
        not report.get("error")
        and report["editor"] == profile["unity"]["editorVersion"],
        "Bake failed or wrong editor",
    )
    require(
        report["profileSHA256"] == profile["avatarProfile"]["sha256"]
        and report["referenceSHA256"] == profile["reference"]["sha256"],
        "Bake profile/reference mismatch",
    )
    request = read(output / "request.json")
    avatar = read(run / "inputs/avatarProfile.json")
    require(
        request["humanDescription"] == avatar["humanDescription"],
        "Bake parameters changed",
    )
    require(
        {c["name"]: c["sha256"] for c in request["clips"]}
        == {c["name"]: c["sha256"] for c in profile["clips"]},
        "Bake clip sources changed",
    )
    variant = next(v for v in report["variants"] if v["id"] == "campus")
    require(
        variant["valid"]
        and variant["human"]
        and variant["mappedBones"] == 52
        and not variant["hipNormalized"],
        "Invalid Campus Avatar",
    )
    require(
        {c["name"] for c in variant["clips"]} == {c["name"] for c in profile["clips"]},
        "Bake clip set mismatch",
    )
    for clip in variant["clips"]:
        require(
            clip["finite"]
            and clip["tracks"] == 52
            and not clip["unmappedAnimatedBones"],
            "Incomplete bake",
        )
    manifest = dict(
        fingerprint=bake_fingerprint(profile), origin=origin, files=files(output)
    )
    write(output / "manifest.json", manifest)
    return variant


def export_sources(profile, run, variant):
    data = read(run / "inputs/assets/animations.json")
    by_name = {c["name"]: c for c in data["clips"]}
    for clip in variant["clips"]:
        raw = read(run / "bakes" / clip["file"])
        original = by_name[clip["name"]]
        require(
            abs(raw["duration"] - original["duration"]) < 1e-4
            and raw["loop"] == original["sourceLoop"],
            "Clip timing mismatch",
        )
        keys = [b["key"] for b in raw["frames"][0]["bones"]]
        tracks = []
        for index, key in enumerate(keys):
            positions, rotations = [], []
            for frame in raw["frames"]:
                bone = frame["bones"][index]
                require(bone["key"] == key, "Bake bone order changed")
                p, q = bone["p"], bone["q"]
                positions.append([-p["x"], p["y"], p["z"]])
                rotation = [q["x"], -q["y"], -q["z"], q["w"]]
                norm = math.sqrt(sum(v * v for v in rotation))
                require(abs(norm - 1) < 1e-4, "Invalid baked quaternion")
                rotation = [v / norm for v in rotation]
                if (
                    rotations
                    and sum(x * y for x, y in zip(rotation, rotations[-1])) < 0
                ):
                    rotation = [-v for v in rotation]
                rotations.append(rotation)
            tracks.append(dict(bone=key, positions=positions, rotations=rotations))
        original["skeletal"] = dict(
            version=1,
            coordinates="three-mirror-x",
            sampleRate=30,
            tracks=tracks,
            sourceSha256=sha(run / "bakes" / clip["file"]),
            provenance="Campus Avatar rebuilt from recovered profile; Unity "
            + profile["unity"]["editorVersion"],
        )
    data["clips"] = [
        c
        for c in data["clips"]
        if c.get("role") not in {"portraitIdle", "speakingHold"}
    ]
    write(run / "source-animations.json", data)


def assemble(profile, run):
    data = read(run / "source-animations.json")
    derived = read(run / "derived.json")
    data["clips"].extend(derived["clips"])
    by_name = {c["name"]: c for c in data["clips"]}
    require(len(by_name) == len(data["clips"]), "Duplicate clip names")
    for clip in derived["clips"]:
        s = clip["skeletal"]
        s["sourceSha256"] = digest(s["tracks"])
        composition = clip["composition"]
        composition["baseBakeSha256"] = by_name[composition["base"]]["skeletal"][
            "sourceSha256"
        ]
        layer = composition.get("relativeLayer", composition.get("layer"))
        composition["layerBakeSha256"] = by_name[layer]["skeletal"]["sourceSha256"]
        if clip["role"] == "speakingHold":
            by_name[composition["base"]]["holdClipName"] = clip["name"]
    candidate = run / "candidate"
    for name in profile["assets"]["files"]:
        copy(member(run / "inputs/assets", name), member(candidate, name))
    model = read(candidate / "model.json")
    guards = model["handClearance"].setdefault("introClips", [])
    for guard in profile["calibration"]["entranceGuards"]:
        guards[:] = [g for g in guards if g["name"] != guard["name"]]
        guards.append(guard)
    write(candidate / "model.json", model)
    write(candidate / "animations.json", data)
    validate_assets(profile, run)


def validate_assets(profile, run):
    old = {c["name"]: c for c in read(run / "inputs/assets/animations.json")["clips"]}
    clips = read(run / "candidate/animations.json")["clips"]
    require(
        {c["name"] for c in clips} == set(old),
        "Pipeline must preserve the input clip catalog",
    )
    maximum = 0.0
    for clip in clips:
        if "skeletal" not in clip:
            require(clip == old[clip["name"]], "Native face/metadata was altered")
            continue
        s = clip["skeletal"]
        require(
            s["coordinates"] == "three-mirror-x" and len(s["tracks"]) == 52,
            "Invalid skeletal schema",
        )
        if clip.get("role") not in {"portraitIdle", "speakingHold"}:
            require(
                clip["tracks"] == old[clip["name"]]["tracks"],
                "Original native tracks/64-bit IDs changed",
            )
        for track in s["tracks"]:
            require(
                len(track["positions"]) == len(track["rotations"]) > 0,
                "Unbalanced track",
            )
            require(
                all(
                    math.isfinite(v)
                    for field in ["positions", "rotations"]
                    for row in track[field]
                    for v in row
                ),
                "Non-finite pose",
            )
            for q in track["rotations"]:
                error = abs(math.sqrt(sum(v * v for v in q)) - 1)
                maximum = max(maximum, error)
                require(
                    error < profile["thresholds"]["quaternionNormError"],
                    "Quaternion not normalized",
                )
    write(
        run / "asset-validation.json",
        dict(
            passed=True,
            clips=len(clips),
            humanBones=52,
            maxQuaternionNormError=maximum,
            nativeMetadataPreserved=True,
        ),
    )


def acceptance_key(run):
    return digest(
        dict(
            candidate=files(run / "candidate"),
            profile=read(run / "profile.json"),
            code=code_hashes(),
        )
    )


def accept(run, reuse=None):
    key = acceptance_key(run)
    if reuse:
        reuse = workspace(reuse)
        verify(reuse)
        old = read(reuse / "acceptance.json")
        require(
            old["key"] == key and old["passed"],
            "Acceptance cannot be reused: candidate, configuration or runtime changed",
        )
        shutil.copytree(reuse / "acceptance", run / "acceptance")
        write(run / "acceptance.json", {**old, "reusedFrom": str(reuse)})
    else:
        command(["node", HERE / "accept.mjs", run], run / "logs/acceptance.log")
        report = read(run / "acceptance/results.json")
        require(report["passed"], "Browser acceptance failed")
        write(
            run / "acceptance.json",
            dict(passed=True, key=key, reports=files(run / "acceptance")),
        )


def archive(folder, target):
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as output:
        for name in files(folder):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            output.writestr(entry, member(folder, name).read_bytes())


def build(args):
    run = workspace(args.output)
    require(
        run.is_relative_to(ROOT / "corpus/gim-assets/pipeline"),
        "Outputs belong under corpus/gim-assets/pipeline/",
    )
    require(
        not run.exists(),
        "Run directory already exists; choose a new output to retain its audit history",
    )
    profile = read(args.profile)
    run.mkdir(parents=True)
    (run / "logs").mkdir()
    state = dict(
        status="building",
        startedAt=dt.datetime.now(dt.timezone.utc).isoformat(),
        code=code_hashes(),
    )
    write(run / "run.json", state)
    try:
        snapshot(profile, run)
        variant = bake(profile, run, args.editor, args.reuse_bakes)
        export_sources(profile, run, variant)
        command(["node", HERE / "generate.mjs", run], run / "logs/generation.log")
        assemble(profile, run)
        accept(run, args.reuse_acceptance)
        shutil.copytree(run / "inputs/assets", run / "rollback")
        write(run / "candidate-manifest.json", files(run / "candidate"))
        archive(run / "candidate", run / "candidate.zip")
        archive(run / "rollback", run / "rollback.zip")
        state.update(
            status="accepted",
            acceptanceKey=acceptance_key(run),
            sameVersionCheck=profile["unity"]["sameVersionCheck"],
        )
        write(run / "run.json", state)
        write_report(run)
        tracked = {
            name: value
            for name, value in files(run).items()
            if not name.startswith("unity-project/")
        }
        write(run / "manifest.json", tracked)
        verify(run)
        print("Accepted candidate:", run, flush=True)
    except BaseException as error:
        state.update(status="failed", error=str(error))
        write(run / "run.json", state)
        raise


def write_report(run):
    from html import escape

    results = read(run / "acceptance/results.json")
    text = escape(json.dumps(results, ensure_ascii=False, indent=2))
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stand3D 流水线验收</title><style>body{{max-width:1100px;margin:auto;padding:24px;font:15px/1.7 system-ui;background:#eef2f6;color:#24313b}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}img{{max-width:100%}}a{{color:#225c86}}</style><h1>Stand3D 制作流水线：候选验收通过</h1><p>已生成独立候选，未自动修改生产素材。Unity6000同版本验证按本次配置跳过，不宣称原运行时数值等价。</p><p><a href="candidate.zip">候选包</a> · <a href="rollback.zip">回退包</a> · <a href="candidate-manifest.json">来源与SHA</a> · <a href="acceptance.json">验收凭据</a></p><img src="acceptance/comparison.png" alt="左侧输入版本，右侧新生成候选"><p>同一姿势／相机；物理和衣料指标是局部检测，不证明全网格零穿插。</p><pre>{text}</pre></html>"""
    (run / "report.html").write_text(html, encoding="utf-8")


def verify(run):
    run = workspace(run)
    check_files(run, read(run / "manifest.json"))
    require(read(run / "run.json")["status"] == "accepted", "Run is not accepted")
    receipt = read(run / "acceptance.json")
    require(
        receipt["passed"] and receipt["key"] == acceptance_key(run),
        "Acceptance is stale for these assets/configuration/runtime",
    )
    check_files(run / "acceptance", receipt["reports"])
    require(
        files(run / "candidate") == read(run / "candidate-manifest.json"),
        "Candidate file set changed",
    )


def install(run, target, rollback=False):
    verify(run)
    target = workspace(target)
    require(
        not target.is_relative_to(run) and not run.is_relative_to(target),
        "Target must be separate from run artifacts",
    )
    baseline, candidate = files(run / "rollback"), files(run / "candidate")
    expected, replacement = (candidate, baseline) if rollback else (baseline, candidate)
    check_files(target, expected)
    source = run / ("rollback" if rollback else "candidate")
    changed = [name for name in replacement if replacement[name] != expected.get(name)]
    staged = []
    completed = []
    try:
        for name in changed:
            destination = member(target, name)
            temporary = destination.with_name(destination.name + ".stand3d-stage")
            require(not temporary.exists(), f"Staged file already exists: {temporary}")
            copy(member(source, name), temporary)
            staged.append(temporary)
            require(sha(temporary) == replacement[name], "Staging integrity failure")
        # Compare again immediately before mutation; never overwrite an unknown version.
        check_files(target, expected)
        for name, temporary in zip(changed, staged):
            os.replace(temporary, member(target, name))
            completed.append(name)
        check_files(target, replacement)
    except BaseException:
        original = run / ("candidate" if rollback else "rollback")
        for name in completed:
            copy(member(original, name), member(target, name))
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
    record = dict(
        action="rollback" if rollback else "activate",
        target=str(target),
        changed=changed,
        at=dt.datetime.now(dt.timezone.utc).isoformat(),
        fileHashes=replacement,
    )
    write(
        run / ("rollback-record.json" if rollback else "activation-record.json"), record
    )
    print(record["action"], "completed:", target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    p = commands.add_parser(
        "build", help="Snapshot, bake, calibrate, accept and package a new isolated run"
    )
    p.add_argument("--profile", type=Path, default=HERE / "profiles/temari-campus.json")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--editor", type=Path)
    p.add_argument("--reuse-bakes", type=Path)
    p.add_argument("--reuse-acceptance", type=Path)
    for action in ["verify", "activate", "rollback"]:
        p = commands.add_parser(action)
        p.add_argument("run", type=Path)
        if action != "verify":
            p.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    try:
        with lock():
            if args.action == "build":
                build(args)
            elif args.action == "verify":
                verify(args.run)
                print("Run hashes and acceptance are valid")
            else:
                install(workspace(args.run), args.target, args.action == "rollback")
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
