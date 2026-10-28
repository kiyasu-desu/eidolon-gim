"""File-boundary regressions for a tool that can replace production assets."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "stand_pipeline", Path(__file__).parents[1] / "pipeline.py"
)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineTransactions(unittest.TestCase):
    def setUp(self):
        base = pipeline.ROOT / "corpus/gim-assets/pipeline"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.run = self.root / "run"
        self.target = self.root / "production"
        for folder in ["run/candidate", "run/rollback", "run/acceptance", "production"]:
            (self.root / folder).mkdir(parents=True)
        for name in ["model.json", "animations.json"]:
            pipeline.write(self.run / "candidate" / name, {"version": 2})
            pipeline.write(self.run / "rollback" / name, {"version": 1})
            pipeline.copy(self.run / "rollback" / name, self.target / name)
        pipeline.write(self.run / "profile.json", {"version": 1})
        pipeline.write(self.run / "run.json", {"status": "accepted"})
        pipeline.write(
            self.run / "candidate-manifest.json", pipeline.files(self.run / "candidate")
        )
        pipeline.write(
            self.run / "acceptance.json",
            {"passed": True, "key": pipeline.acceptance_key(self.run), "reports": {}},
        )
        pipeline.write(self.run / "manifest.json", pipeline.files(self.run))

    def test_source_pin_and_relative_path_must_match_before_snapshot(self):
        expected = pipeline.files(self.target)
        pipeline.write(self.target / "model.json", {"unknown": True})
        with self.assertRaisesRegex(ValueError, "changed"):
            pipeline.check_files(self.target, expected)
        with self.assertRaisesRegex(ValueError, "relative path"):
            pipeline.member(self.target, "../other-file")

    def test_bake_reuse_rejects_changed_inputs_and_corrupted_cache(self):
        cache = self.root / "cache"
        cache.mkdir()
        profile = {
            "avatarProfile": {"sha256": "avatar"},
            "reference": {"sha256": "reference"},
            "clips": [],
            "unity": {},
        }
        pipeline.write(cache / "pose.json", {"pose": "original"})
        cached_files = pipeline.files(cache)
        pipeline.write(
            cache / "manifest.json", {"fingerprint": "wrong", "files": cached_files}
        )
        first = self.root / "first-reuse"
        first.mkdir()
        with self.assertRaisesRegex(ValueError, "inputs/editor/probe"):
            pipeline.bake(profile, first, None, cache)
        pipeline.write(
            cache / "manifest.json",
            {"fingerprint": pipeline.bake_fingerprint(profile), "files": cached_files},
        )
        pipeline.write(cache / "pose.json", {"pose": "corrupted"})
        second = self.root / "second-reuse"
        second.mkdir()
        with self.assertRaisesRegex(ValueError, "changed"):
            pipeline.bake(profile, second, None, cache)

    def test_accepted_run_rejects_modified_artifacts_and_changed_runtime(self):
        pipeline.verify(self.run)
        with patch.object(pipeline, "code_hashes", return_value={"runtime": "changed"}):
            with self.assertRaisesRegex(ValueError, "stale"):
                pipeline.verify(self.run)
        pipeline.write(self.run / "candidate/model.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "changed"):
            pipeline.verify(self.run)

    def test_activation_and_rollback_preserve_the_pair_and_reject_unknown_target(self):
        baseline = pipeline.files(self.target)
        pipeline.install(self.run, self.target)
        self.assertEqual(
            pipeline.files(self.target), pipeline.files(self.run / "candidate")
        )
        pipeline.install(self.run, self.target, rollback=True)
        self.assertEqual(pipeline.files(self.target), baseline)
        pipeline.write(self.target / "animations.json", {"unrelated-edit": True})
        with self.assertRaisesRegex(ValueError, "changed"):
            pipeline.install(self.run, self.target)
        self.assertEqual(
            pipeline.sha(self.target / "model.json"), baseline["model.json"]
        )

    def test_interrupted_pair_replacement_restores_completed_files(self):
        before = pipeline.files(self.target)
        original = pipeline.os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated second-file failure")
            return original(source, destination)

        with patch.object(pipeline.os, "replace", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second-file"):
                pipeline.install(self.run, self.target)
        self.assertEqual(pipeline.files(self.target), before)
        self.assertFalse(list(self.target.glob("*.stand3d-stage")))


if __name__ == "__main__":
    unittest.main()
