import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MazeLabDeploymentContractTests(unittest.TestCase):
    def test_deployment_validator_and_runtime_digest_agree(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for deployment validation")

        validator = subprocess.run(
            [node, "deploy/verify-config.mjs"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            validator.returncode,
            0,
            msg="Deployment validation failed:\n%s\n%s"
            % (validator.stdout, validator.stderr),
        )
        match = re.search(r"Runtime SHA-256: ([0-9a-f]{64})", validator.stdout)
        self.assertIsNotNone(match, msg=validator.stdout)

        digest = subprocess.run(
            ["sh", "deploy/compute-runtime-sha256.sh", "game"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(digest.returncode, 0, msg=digest.stderr)
        self.assertEqual(digest.stdout.strip(), match.group(1))

    def test_compose_model_is_host_port_free(self):
        docker = shutil.which("docker")
        if docker is None:
            self.skipTest("Docker CLI is required for Compose model validation")

        environment = os.environ.copy()
        environment.update(
            {
                "MAZELAB_GIT_COMMIT": "0" * 40,
                "MAZELAB_RUNTIME_SHA256": "0" * 64,
                "MAZELAB_SOURCE_ARCHIVE_SHA256": "0" * 64,
                "MAZELAB_IMAGE_TAG": "contract-check",
            }
        )
        rendered = subprocess.run(
            [docker, "compose", "-f", "deploy/compose.yaml", "config"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            rendered.returncode,
            0,
            msg="Compose validation failed:\n%s\n%s"
            % (rendered.stdout, rendered.stderr),
        )
        self.assertNotRegex(rendered.stdout, r"(?m)^\s+ports:")
        self.assertRegex(rendered.stdout, r"(?m)^\s+expose:\n\s+- \"8080\"")
        self.assertIn("name: mazelab_edge", rendered.stdout)

    def test_operator_shell_scripts_parse(self):
        for relative in (
            "deploy/compute-runtime-sha256.sh",
            "deploy/prepare-release.sh",
            "deploy/verify-running.sh",
        ):
            parsed = subprocess.run(
                ["sh", "-n", relative],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(parsed.returncode, 0, msg=f"{relative}: {parsed.stderr}")

    def test_runtime_digest_rejects_undeclared_payload_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "game"
            for directory in ("js", "levels", "assets/stl", "vendor"):
                (runtime / directory).mkdir(parents=True, exist_ok=True)
            for relative in (
                "index.html",
                "styles.css",
                "icon.svg",
                "manifest.webmanifest",
                "service-worker.js",
                "THIRD_PARTY_NOTICES.md",
            ):
                (runtime / relative).write_text("test", encoding="utf-8")
            (runtime / "debug.txt").write_text("not declared", encoding="utf-8")

            digest = subprocess.run(
                ["sh", str(ROOT / "deploy/compute-runtime-sha256.sh"), str(runtime)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(digest.returncode, 0)
            self.assertIn("outside the deployment allowlist", digest.stderr)


if __name__ == "__main__":
    unittest.main()
