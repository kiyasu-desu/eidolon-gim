"""The release gate sees Git blobs, including staged leaks and Git-only symlinks."""

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_check", ROOT / "scripts/check-release.py")
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseTree(unittest.TestCase):
    def setUp(self):
        base = ROOT / ".scratch/release-tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(base.resolve())
        self.git("init", "--quiet")
        self.policy = {
            "root_files": ["release-policy.json"],
            "source_roots": ["backend", "frontend"],
            "max_file_bytes": 2000,
            "binary_assets": {},
        }
        self.save_policy()

    def tearDown(self):
        assert self.root.is_relative_to((ROOT / ".scratch/release-tests").resolve())
        self.temp.cleanup()

    def git(self, *args, data=None):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], input=data, capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode() if isinstance(data, str) else data)

    def stage(self, path, data):
        self.write(path, data)
        self.git("add", "--", path)

    def save_policy(self):
        self.stage("release-policy.json", json.dumps(self.policy))

    def test_reads_the_index_and_ref_not_unstaged_files_or_private_local_data(self):
        self.stage("backend/source.py", "print('source')\n")
        self.write("corpus/private.db", b"private user data\x00")
        self.git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "source")
        token = "ghp_" + "A" * 36
        self.write("backend/source.py", f"token = '{token}'\n")
        self.assertEqual(release.check(self.root)["errors"], [])
        self.git("add", "backend/source.py")
        errors = release.check(self.root)["errors"]
        self.assertEqual(errors, [{"path": "backend/source.py", "line": 1, "reason": "GitHub token"}])
        self.assertNotIn(token, json.dumps(errors))
        self.assertEqual(release.check(self.root, "HEAD")["errors"], [])

    def test_private_paths_cannot_be_approved_as_binary_assets(self):
        data = b"not a source model\x00"
        for path in (".env", "corpus/raw.csv", ".scratch/report.txt", "backend/data/user.sqlite", "frontend/hero.glb"):
            self.stage(path, data)
            self.policy["binary_assets"][path] = hashlib.sha256(data).hexdigest()
        self.save_policy()
        errors = release.check(self.root)["errors"]
        self.assertEqual(len(errors), 5)
        self.assertTrue(all(e["reason"] == "local/private resource path" for e in errors))

    def test_pins_ui_media_and_rejects_new_payloads_and_changed_assets(self):
        path, image = "frontend/logo.png", b"\x89PNG\x00original UI icon"
        self.stage(path, image)
        self.policy["binary_assets"][path] = hashlib.sha256(image).hexdigest()
        self.save_policy()
        self.assertEqual(release.check(self.root)["errors"], [])
        self.stage(path, image + b"modified")
        self.stage("backend/export.json", '{"meshes": [1]}')
        self.stage("backend/opaque.dat", b"\x00unapproved binary")
        self.stage("backend/large.txt", "x" * 2001)
        self.stage("private-notes.txt", "local deployment details")
        reasons = {e["reason"] for e in release.check(self.root)["errors"]}
        self.assertEqual(reasons, {
            "approved UI asset checksum changed", "model/story/vector payload",
            "unapproved binary asset", "file exceeds source size limit", "outside the source allowlist",
        })

    def test_git_symlink_targets_must_stay_inside_the_repository(self):
        target = "../../../private.env"
        oid = self.git("hash-object", "-w", "--stdin", data=target.encode()).decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"120000,{oid},backend/link")
        self.assertEqual(release.check(self.root)["errors"], [
            {"path": "backend/link", "reason": "symlink escapes repository"},
        ])

    def test_private_keys_and_high_entropy_literals_are_redacted(self):
        value = "x7Q" + "_aK9mR3dF6vB2cN8sW5tJ4zY0"
        key = "-----BEGIN " + "PRIVATE KEY-----"
        self.stage("backend/config.py", f"API_KEY = '{value}'\n# {key}\n")
        errors = release.check(self.root)["errors"]
        self.assertEqual({e["reason"] for e in errors}, {"credential-like literal", "private key"})
        self.assertNotIn(value, json.dumps(errors))

    def test_localized_configuration_messages_are_not_credentials(self):
        self.stage("backend/messages.py", 'API_KEY = "请配置向量化服务的密钥，没有配置时不启用自动检索；用户可以稍后在设置页中补齐。"\n')
        self.assertEqual(release.check(self.root)["errors"], [])

    def test_unquoted_dotenv_credentials_are_checked_too(self):
        self.policy["root_files"].append(".env.example")
        self.save_policy()
        value = "x7Q" + "_aK9mR3dF6vB2cN8sW5tJ4zY0"
        self.stage(".env.example", f"FISH_AUDIO_API_KEY={value}\n")
        errors = release.check(self.root)["errors"]
        self.assertEqual(errors, [
            {"path": ".env.example", "line": 1, "reason": "credential-like literal"},
        ])


if __name__ == "__main__":
    unittest.main()
