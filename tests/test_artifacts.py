import math
import os
import struct
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from sanitize_3dm_metadata import sanitize_user_paths


EXPECTED_STL = {
    "grid_maze_platform_bridge_v1.stl": (20, (-50.0, 50.0, -23.0, 23.0, 0.0, 6.0)),
    "grid_maze_platform_recess_cutter_v1.stl": (48, (-0.2, 200.2, -0.2, 200.2, 0.0, 8.0)),
    "grid_maze_platform_tile_v1.stl": (76, (0.0, 200.0, 0.0, 200.0, 0.0, 10.0)),
}


def read_binary_stl(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 84:
        raise ValueError("binary STL is shorter than its header")
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * triangle_count:
        raise ValueError("binary STL length does not match its triangle count")
    vertices = []
    for index in range(triangle_count):
        record = struct.unpack_from("<12fH", data, 84 + index * 50)
        vertices.extend(record[3:12])
    if not all(math.isfinite(value) for value in vertices):
        raise ValueError("binary STL contains a non-finite vertex")
    xs, ys, zs = vertices[0::3], vertices[1::3], vertices[2::3]
    bounds = (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
    return triangle_count, bounds


class GeneratedArtifactTest(unittest.TestCase):
    def test_binary_stl_deliverables_have_expected_geometry_bounds(self):
        for filename, (expected_triangles, expected_bounds) in EXPECTED_STL.items():
            path = os.path.join(ROOT_DIR, "output", filename)
            triangles, bounds = read_binary_stl(path)
            self.assertEqual(expected_triangles, triangles, filename)
            for expected, actual in zip(expected_bounds, bounds):
                self.assertAlmostEqual(expected, actual, places=4, msg=filename)

    def test_rhino_username_redaction_preserves_binary_length(self):
        original = b"before /Users/example/Library/Application Support/McNeel/cache after"
        sanitized, usernames = sanitize_user_paths(original)
        self.assertEqual(len(original), len(sanitized))
        self.assertEqual([b"example"], usernames)
        self.assertNotIn(b"example", sanitized)
        self.assertIn(b"/Users/_______/Library/Application Support/McNeel/", sanitized)


if __name__ == "__main__":
    unittest.main()
