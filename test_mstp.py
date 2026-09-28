"""Tests for PVST+/MSTP multi-instance mode."""

import json
import tempfile
import unittest
from pathlib import Path

import generate
import mstp
import stp
import topologies
from test_stp import SimulationInvariantTests

INVARIANT = SimulationInvariantTests()

SAMPLES = {
    "triangle": topologies.triangle,
    "square-diagonal": topologies.square_diagonal,
    "classic-6": topologies.classic6,
}


class MultiInstanceTests(unittest.TestCase):
    def check_instances(self, name, topology, protocol):
        instances = topologies.build_instances(protocol, name, topology, seed=7)
        result = mstp.simulate_multi(topology, instances, protocol)

        self.assertEqual(len(result.instances), len(instances))
        trees = []
        for inst_def, doc in zip(instances, result.instances):
            self.assertEqual(doc["id"], inst_def.id)
            self.assertEqual(doc["vlans"], inst_def.vlans)
            # Every instance is a full, valid classic STP run.
            INVARIANT.check(mstp.instance_topology(topology, inst_def))
            self.assertEqual(doc["root_id"], result.roots[inst_def.id])
            # Steps are tagged with the instance id.
            self.assertTrue(all(s["instance"] == inst_def.id for s in doc["steps"]))
            self.assertIn(inst_def.id, doc["steps"][0]["description"])
            trees.append(doc["link_roles"])
        return result, trees

    def test_samples_pvst_and_mstp(self):
        for name, build in SAMPLES.items():
            for protocol in ("pvst", "mstp"):
                result, trees = self.check_instances(name, build(), protocol)
                # Different roots -> different trees: the load-balancing story.
                roots = list(result.roots.values())
                self.assertEqual(len(set(roots)), len(roots),
                                 f"{name}/{protocol}: roots should differ")
                self.assertNotEqual(trees[0], trees[1],
                                    f"{name}/{protocol}: trees should differ")

    def test_random_topologies(self):
        for n in (3, 5, 8):
            for seed in range(3):
                self.check_instances("random",
                                     topologies.random_topology(n, seed), "pvst")

    def test_mstp_vlan_mapping_partition(self):
        topology = topologies.classic6()
        instances = topologies.build_instances("mstp", "classic-6", topology, seed=1)
        all_vlans = [v for inst in instances for v in inst.vlans]
        self.assertEqual(len(all_vlans), len(set(all_vlans)),
                         "each VLAN maps to exactly one instance")
        self.assertGreater(len(instances), 1)
        self.assertLess(len(instances), len(all_vlans),
                        "MSTP uses fewer instances than VLANs")
        for inst in instances:
            self.assertGreater(len(inst.vlans), 1,
                               "each MST instance carries several VLANs")

    def test_pvst_one_vlan_per_instance(self):
        instances = topologies.build_instances(
            "pvst", "classic-6", topologies.classic6(), seed=1)
        for inst in instances:
            self.assertEqual(len(inst.vlans), 1)
        self.assertEqual([i.vlans[0] for i in instances], ["10", "20"])

    def test_narration_mentions_mode(self):
        topology = topologies.triangle()
        pvst = mstp.simulate_multi(
            topology, topologies.build_instances("pvst", "triangle", topology, 1),
            "pvst")
        mstp_r = mstp.simulate_multi(
            topology, topologies.build_instances("mstp", "triangle", topology, 1),
            "mstp")
        self.assertIn("每个 VLAN", pvst.instances[0]["steps"][0]["description"])
        self.assertIn("共享一棵树", mstp_r.instances[0]["steps"][0]["description"])

    def test_empty_instances_rejected(self):
        with self.assertRaises(ValueError):
            mstp.simulate_multi(topologies.triangle(), [], "pvst")

    def test_deterministic(self):
        def doc():
            topology = topologies.random_topology(6, seed=5)
            return generate.build_document("random", topology, "mstp", seed=5)[0]
        self.assertEqual(json.dumps(doc(), sort_keys=True),
                         json.dumps(doc(), sort_keys=True))


class CliTests(unittest.TestCase):
    def test_pvst_mstp_and_regressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            pvst_path = Path(tmp) / "pvst.html"
            mstp_path = Path(tmp) / "mstp.html"
            stp_path = Path(tmp) / "stp.html"
            generate.main(["-p", "pvst", "-t", "triangle", "-o", str(pvst_path)])
            generate.main(["-p", "mstp", "-t", "classic-6", "-o", str(mstp_path)])
            generate.main(["-t", "triangle", "-o", str(stp_path)])

            pvst = pvst_path.read_text(encoding="utf-8")
            self.assertIn("PVST+", pvst)
            self.assertIn('"instances"', pvst)
            self.assertNotIn(generate.DATA_PLACEHOLDER, pvst)

            mstp = mstp_path.read_text(encoding="utf-8")
            self.assertIn("MSTP", mstp)
            self.assertIn("MST1", mstp)
            self.assertIn("MST2", mstp)

            # Single-instance protocols must not grow an instances field.
            stp = stp_path.read_text(encoding="utf-8")
            self.assertNotIn('"instances"', stp)


if __name__ == "__main__":
    unittest.main()
