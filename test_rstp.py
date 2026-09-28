"""Tests for the RSTP extension (proposal/agreement, edge ports, failure)."""

import json
import tempfile
import unittest
from pathlib import Path

import generate
import rstp
import stp
import topologies


def chain_topology(count=4):
    """A pure tree (no redundancy): nothing can fail over."""
    switches = topologies._switches(count, [32768] * count)
    links = [stp.Link(f"S{i}", f"S{i + 1}", 4) for i in range(1, count)]
    return stp.Topology(switches=switches, links=links)


class BootPhaseTests(unittest.TestCase):
    def check_boot(self, topology, hosts=()):
        result = rstp.simulate_rstp(topology, hosts, include_failure=False,
                                    include_link_add=False)
        n = len(topology.switches)
        steps = result.steps
        kinds = [s["kind"] for s in steps]
        self.assertEqual(kinds[0], "initial")
        self.assertEqual(kinds[-1], "final")
        handshakes = [s for s in steps if s["kind"] == "handshake"]
        self.assertEqual(len(handshakes), n - 1, "one handshake per tree link")

        # Every tree link is handshake target exactly once, and the cascade
        # respects the tree hierarchy: a parent's handshake precedes the
        # child's own handshake step.
        base = stp.simulate(topology)
        first_at = {}
        seen_links = []
        for idx, step in enumerate(steps):
            if step["kind"] != "handshake":
                continue
            proposal = [e for e in step["events"] if e["kind"] == "proposal"]
            agreement = [e for e in step["events"] if e["kind"] == "agreement"]
            self.assertEqual(len(proposal), 1)
            self.assertEqual(len(agreement), 1)
            parent, child = proposal[0]["from"], proposal[0]["to"]
            self.assertEqual(agreement[0]["from"], child)
            self.assertEqual(agreement[0]["to"], parent)
            self.assertGreaterEqual(agreement[0].get("delay", 0), 0.5)
            # base.port_roles must agree this is parent -> child on the tree.
            self.assertEqual(base.port_roles[child]["root_port"], parent)
            link_id = "-".join(sorted((parent, child)))
            seen_links.append(link_id)
            first_at[child] = idx
            if parent != base.root_id:
                self.assertLess(first_at[parent], idx,
                                "parent must handshake before child")
            # Link state flips to forwarding in this step and stays.
            self.assertEqual(step["links"][link_id], "forwarding")
        self.assertEqual(sorted(seen_links),
                         sorted(l.id() for l in topology.links
                                if base.link_roles[l.id()] == "tree"))

        # Final boot state: n-1 forwarding, rest alternate.
        final_state = steps[-1]["links"]
        self.assertEqual(sum(1 for s in final_state.values() if s == "forwarding"),
                         n - 1)
        self.assertEqual(sum(1 for s in final_state.values() if s == "alternate"),
                         len(topology.links) - (n - 1))
        return result

    def test_samples(self):
        self.check_boot(topologies.triangle())
        self.check_boot(topologies.square_diagonal())
        self.check_boot(topologies.classic6())

    def test_random_topologies(self):
        for n in (3, 5, 8, 11):
            for seed in range(3):
                self.check_boot(topologies.random_topology(n, seed))


class EdgePortTests(unittest.TestCase):
    def test_hosts_never_participate(self):
        topology = topologies.triangle()
        hosts = [rstp.Host("PC1", "S1")]
        result = rstp.simulate_rstp(topology, hosts, include_failure=True)
        for step in result.steps:
            for event in step["events"]:
                self.assertNotIn(event["from"], {"PC1"})
                self.assertNotIn(event["to"], {"PC1"})
        self.assertEqual(result.hosts, hosts)
        # Initial step explains the edge ports.
        self.assertIn("边缘端口", result.steps[0]["description"])

    def test_host_validation(self):
        topology = topologies.triangle()
        with self.assertRaises(ValueError):
            rstp.validate_hosts(topology, [rstp.Host("PC1", "S9")])
        with self.assertRaises(ValueError):
            rstp.validate_hosts(topology, [rstp.Host("S1", "S1")])
        with self.assertRaises(ValueError):
            rstp.validate_hosts(
                topology, [rstp.Host("PC1", "S1"), rstp.Host("PC1", "S2")])


class FailurePhaseTests(unittest.TestCase):
    def check_failure(self, topology):
        result = rstp.simulate_rstp(topology, include_failure=True,
                                    include_link_add=False)
        if result.failed_link is None:
            return "skipped"
        n = len(topology.switches)
        self.assertIn(result.failed_link, result.link_roles)
        self.assertEqual(result.link_roles[result.failed_link], "down")

        # Final roles must equal a fresh simulation of the pruned topology.
        pruned = stp.Topology(
            switches=list(topology.switches),
            links=[l for l in topology.links if l.id() != result.failed_link])
        after = stp.simulate(pruned)
        final_step = result.steps[-1]
        self.assertEqual(final_step["kind"], "final")
        self.assertEqual(final_step["roles"]["ports"], after.port_roles)
        self.assertEqual(final_step["roles"]["root"], after.root_id)

        # Recovered tree: n-1 forwarding links, failed link down.
        final_state = final_step["links"]
        self.assertEqual(sum(1 for s in final_state.values() if s == "forwarding"),
                         n - 1)
        self.assertEqual(sum(1 for s in final_state.values() if s == "down"), 1)

        # There is a link-down step followed by a promotion handshake.
        kinds = [s["kind"] for s in result.steps]
        self.assertIn("link-down", kinds)
        down_idx = kinds.index("link-down")
        promotion = next(s for s in result.steps[down_idx:]
                         if s["kind"] == "handshake")
        self.assertIn("根端口", promotion["description"])
        return "failed"

    def test_samples_fail_over(self):
        for build in (topologies.triangle, topologies.square_diagonal,
                      topologies.classic6):
            self.assertEqual(self.check_failure(build()), "failed")

    def test_random_topologies(self):
        outcomes = set()
        for seed in range(6):
            outcomes.add(self.check_failure(topologies.random_topology(7, seed)))
        self.assertIn("failed", outcomes)

    def test_no_redundancy_skips_failure(self):
        topology = chain_topology(4)
        result = rstp.simulate_rstp(topology, include_failure=True,
                                    include_link_add=False)
        self.assertIsNone(result.failed_link)
        self.assertIn("跳过故障演示", result.steps[-1]["description"])
        self.assertEqual(result.steps[-1]["phase"], "boot-final")


class PickFailureLinkTests(unittest.TestCase):
    def test_criteria(self):
        topology = topologies.triangle()
        base = stp.simulate(topology)
        picked = rstp.pick_failure_link(topology, base)
        self.assertIsNotNone(picked)
        link, victim, parent = picked
        # Victim must own an alternate port on some other link.
        alternates = [lid for lid, end in base.blocked_ends.items()
                      if end == victim and lid != link.id()]
        self.assertTrue(alternates)
        # And the network survives without the link.
        pruned = stp.Topology(
            switches=list(topology.switches),
            links=[l for l in topology.links if l.id() != link.id()])
        stp.validate(pruned)  # must not raise

    def test_tree_topology_has_no_candidate(self):
        topology = chain_topology(4)
        base = stp.simulate(topology)
        self.assertIsNone(rstp.pick_failure_link(topology, base))


def complete_topology(count=3, cost=4):
    switches = topologies._switches(count, [32768] * count)
    ids = [s.id for s in switches]
    links = [stp.Link(a, b, cost)
             for i, a in enumerate(ids) for b in ids[i + 1:]]
    return stp.Topology(switches=switches, links=links)


class LinkAddTests(unittest.TestCase):
    def final_roles(self, topology):
        result = rstp.simulate_rstp(topology)
        final = stp.Topology(list(topology.switches), result.final_links)
        fresh = stp.simulate(final)
        expected = {
            link.id(): ("forwarding" if fresh.link_roles[link.id()] == "tree"
                        else "alternate")
            for link in result.final_links
        }
        final_ids = {link.id() for link in result.final_links}
        if result.failed_link and result.failed_link not in final_ids:
            expected[result.failed_link] = "down"
        return result, fresh, expected

    def test_final_equals_fresh_simulation(self):
        """Master assertion: the whole chained story ends exactly where a
        fresh run of the algorithm on the final topology would end."""
        builds = [topologies.triangle, topologies.square_diagonal,
                  topologies.classic6, chain_topology, complete_topology]
        for build in builds:
            result, fresh, expected = self.final_roles(build())
            last = result.steps[-1]
            self.assertEqual(last["roles"]["ports"], fresh.port_roles)
            self.assertEqual(last["roles"]["root"], fresh.root_id)
            self.assertEqual(result.link_roles, expected)
        for n in (3, 5, 8, 10):
            for seed in range(3):
                self.final_roles(topologies.random_topology(n, seed))

    def test_worse_link_leaves_tree_untouched(self):
        result = rstp.simulate_rstp(topologies.classic6())
        self.assertTrue(result.added_links)
        phases = [s["phase"] for s in result.steps]
        kinds = [s["kind"] for s in result.steps]
        worse_final = result.steps[phases.index("link-add-worse-final")]
        before = result.steps[kinds.index("link-up") - 1]
        forwarding_before = {lid for lid, s in before["links"].items()
                             if s == "forwarding"}
        forwarding_after = {lid for lid, s in worse_final["links"].items()
                            if s == "forwarding"}
        self.assertEqual(forwarding_before, forwarding_after,
                         "a worse link must not change the tree at all")
        self.assertEqual(worse_final["links"][result.added_links[0]],
                         "alternate")

    def test_better_link_migrates_root_port(self):
        result = rstp.simulate_rstp(topologies.classic6())
        self.assertGreaterEqual(len(result.added_links), 2)
        phases = [s["phase"] for s in result.steps]
        worse_final = result.steps[phases.index("link-add-worse-final")]
        better_final = result.steps[phases.index("link-add-better-final")]
        migrated = [
            sid for sid in better_final["roles"]["ports"]
            if better_final["roles"]["ports"][sid]["root_port"] !=
            worse_final["roles"]["ports"][sid]["root_port"]
        ]
        self.assertTrue(migrated, "the better link must migrate a root port")
        better_final_links = better_final["links"]
        self.assertEqual(better_final_links[result.added_links[1]],
                         "forwarding")

    def test_triangle_repairs_failed_link_without_impact(self):
        result = rstp.simulate_rstp(topologies.triangle())
        self.assertEqual(len(result.added_links), 1)
        self.assertEqual(result.added_links[0], result.failed_link)
        up = next(s for s in result.steps if s["phase"] == "link-add"
                  and s["kind"] == "link-up")
        self.assertIn("修复重连", up["description"])

    def test_link_add_skipped_for_complete_topology_without_failure(self):
        result = rstp.simulate_rstp(complete_topology(4),
                                    include_failure=False)
        self.assertEqual(result.added_links, [])
        self.assertEqual(result.steps[-1]["phase"], "boot-final")

    def test_phase_order(self):
        result = rstp.simulate_rstp(topologies.classic6())
        order = []
        for step in result.steps:
            if step["phase"] not in order:
                order.append(step["phase"])
        self.assertEqual(
            order,
            ["boot", "cascade", "boot-final", "failure",
             "failure-final", "link-add", "link-add-worse-final",
             "link-add-better-final"])

    def test_deterministic(self):
        def doc():
            return generate.build_document(
                "classic-6", topologies.classic6(), "rstp", seed=1)[0]
        import json
        self.assertEqual(json.dumps(doc(), sort_keys=True),
                         json.dumps(doc(), sort_keys=True))


class DocumentTests(unittest.TestCase):
    def test_deterministic(self):
        def doc():
            topology = topologies.random_topology(6, seed=3)
            return generate.build_document("random", topology, "rstp", seed=3)[0]
        self.assertEqual(json.dumps(doc(), sort_keys=True),
                         json.dumps(doc(), sort_keys=True))

    def test_cli_rstp_and_stp_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            rstp_html = Path(tmp) / "rstp.html"
            stp_html = Path(tmp) / "stp.html"
            generate.main(["--protocol", "rstp", "-t", "classic-6",
                           "-o", str(rstp_html)])
            generate.main(["-t", "classic-6", "-o", str(stp_html)])

            rstp_doc_text = rstp_html.read_text(encoding="utf-8")
            self.assertIn("RSTP", rstp_doc_text)
            self.assertNotIn(generate.DATA_PLACEHOLDER, rstp_doc_text)
            self.assertIn('"hosts"', rstp_doc_text)

            stp_doc_text = stp_html.read_text(encoding="utf-8")
            self.assertIn("经典 STP", stp_doc_text)
            self.assertIn('"hosts": []', stp_doc_text)


if __name__ == "__main__":
    unittest.main()
