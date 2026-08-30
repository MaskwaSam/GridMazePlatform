import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GAME_VALIDATOR = ROOT / "game" / "tests" / "validate.mjs"


class StandaloneGameContractTests(unittest.TestCase):
    def test_node_game_validator_passes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for the standalone game validator")

        result = subprocess.run(
            [node, str(GAME_VALIDATOR)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg="Standalone game validation failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertRegex(result.stdout, r"\n\d+/\d+ checks passed")


if __name__ == "__main__":
    unittest.main()
