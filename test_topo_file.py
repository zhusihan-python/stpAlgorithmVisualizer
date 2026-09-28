"""Tests for the custom topology file loader and position schema."""

import json
import tempfile
import unittest
from pathlib import Path

import generate
import topologies

TRIANGLE_FILE = {
    "switches": [
        {"id": "A", "priority": 32768, "x": 0.5, "y": 0.1},
        {"id": "B", "priority": 32768, "x": 0.15, "y": 0.8},
        {"id": "C", "priority": 8192, "x": 0.85, "y": 0.8},
    ],
    "links": [
        {"a": "A", "b": "B", "cost": 4},
        {"a": "A", "b": "C"},
        {"a": "B", "b": "C", "cost": 4},
    ],
}


def write(tmp, payload):
    path = Path(tmp) / "topo.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class LoaderTests(unittest.TestCase):
    def test_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            topology, positions = topologies.from_file(write(tmp, TRIANGLE_FILE))
        self.assertEqual([s.id for s in topology.switches], ["A", "B", "C"])
        self.assertEqual(topology.switch("C").priority, 8192)
        # Missing cost defaults to 4 (COST_GIGA).
        self.assertEqual(
            [l.cost for l in sorted(topology.links, key=lambda l: l.pair())],
            [4, 4, 4])
        self.assertEqual(positions["A"], (0.5, 0.1))

    def test_defaults_and_partial_positions(self):
        payload = {
            "switches": [{"id": "X"}, {"id": "Y", "x": 0.2, "y": 0.3}],
            "links": [{"a": "X", "b": "Y", "cost": 19}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            topology, positions = topologies.from_file(write(tmp, payload))
        self.assertEqual(topology.switch("X").priority, 32768)
        self.assertTrue(topology.switch("X").mac)  # auto-generated
        self.assertEqual(list(positions), ["Y"])

    def test_rejects_bad_files(self):
        cases = [
            {"links": []},                                   # no switches key
            {"switches": [{"priority": 1}], "links": []},    # no id
            {"switches": [{"id": "A"}],
             "links": [{"a": "A", "b": "Z"}]},               # unknown ref
            {"switches": [{"id": "A"}],
             "links": [{"a": "A", "b": "A"}]},               # self loop
            {"switches": [{"id": "A"}, {"id": "B"}],
             "links": []},                                   # disconnected
        ]
        for payload in cases:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError, msg=str(payload)):
                    topologies.from_file(write(tmp, payload))


class CliTests(unittest.TestCase):
    def test_custom_topology_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            topo_path = write(tmp, TRIANGLE_FILE)
            out = Path(tmp) / "custom.html"
            generate.main(["-f", str(topo_path), "-p", "rstp",
                           "-o", str(out)])
            html = out.read_text(encoding="utf-8")
            self.assertIn('"positions"', html)
            self.assertIn("custom", html)
            self.assertIn("A", html)

    def test_rstp_custom_topology_simulation(self):
        # The whole RSTP story must run on a custom topology: names like
        # "A"/"B" must not break switch-id parsing for joins.
        with tempfile.TemporaryDirectory() as tmp:
            topo_path = write(tmp, TRIANGLE_FILE)
            out = Path(tmp) / "custom.html"
            generate.main(["-f", str(topo_path), "-p", "rstp", "-o", str(out)])
            html = out.read_text(encoding="utf-8")
            self.assertIn("RSTP", html)
            # joined switches get sequential numeric ids even for A/B/C names
            self.assertIn('"S1"', html)

    def test_builtin_samples_have_no_positions(self):
        document, _ = generate.build_document("triangle",
                                              topologies.triangle())
        self.assertNotIn("positions", document)


if __name__ == "__main__":
    unittest.main()
