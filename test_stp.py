"""Tests for the STP simulation core, topology builders and generator."""

import heapq
import json
import tempfile
import unittest
from pathlib import Path

import generate
import stp
import topologies


def dijkstra(topology, source):
    """Shortest-path costs from source, for cross-checking STP convergence."""
    adj = {s.id: [] for s in topology.switches}
    for link in topology.links:
        adj[link.a].append((link.b, link.cost))
        adj[link.b].append((link.a, link.cost))
    dist = {s.id: float("inf") for s in topology.switches}
    dist[source] = 0
    pq = [(0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, cost in adj[u]:
            if d + cost < dist[v]:
                dist[v] = d + cost
                heapq.heappush(pq, (dist[v], v))
    return dist


def reachable_over(topology, links, source):
    """Switches reachable from source using only the given links."""
    adj = {s.id: [] for s in topology.switches}
    for link in links:
        adj[link.a].append(link.b)
        adj[link.b].append(link.a)
    visited, frontier = set(), [source]
    while frontier:
        u = frontier.pop()
        if u in visited:
            continue
        visited.add(u)
        frontier.extend(v for v in adj[u] if v not in visited)
    return visited


class SimulationInvariantTests(unittest.TestCase):
    """Invariants that must hold for every topology we can build."""

    def check(self, topology):
        result = stp.simulate(topology)
        switches = {s.id: s for s in topology.switches}

        # 1. Root bridge is the lowest bridge ID in the network.
        expected_root = min(switches.values(), key=lambda s: s.sort_key()).id
        self.assertEqual(result.root_id, expected_root)

        final_states = result.steps[-1]["switches"]
        for sid in switches:
            self.assertEqual(final_states[sid]["root"], expected_root)

        # 2. Converged root path costs are shortest-path distances.
        dist = dijkstra(topology, expected_root)
        for sid in switches:
            self.assertEqual(final_states[sid]["cost"], dist[sid],
                             f"cost mismatch for {sid}")

        # 3. Port roles: root bridge has no root port and all ports designated;
        #    every other switch has exactly one root port.
        for sid, roles in result.port_roles.items():
            if sid == expected_root:
                self.assertIsNone(roles["root_port"])
                self.assertEqual(len(roles["designated"]),
                                 len(topology.adjacency()[sid]))
                self.assertEqual(roles["blocked"], [])
            else:
                self.assertIsNotNone(roles["root_port"])
                self.assertNotIn(roles["root_port"], roles["blocked"])

        # 4. The root port of a switch is the designated side of that link.
        for sid, roles in result.port_roles.items():
            if roles["root_port"]:
                neighbour = roles["root_port"]
                self.assertIn(sid, result.port_roles[neighbour]["designated"])

        # 5. Forwarding (tree) links form a spanning tree: n-1 links,
        #    connected, therefore acyclic.
        tree_links = [l for l in topology.links
                      if result.link_roles[l.id()] == "tree"]
        self.assertEqual(len(tree_links), len(switches) - 1)
        self.assertEqual(reachable_over(topology, tree_links, expected_root),
                         set(switches))

        # 6. Blocked links are exactly the redundant ones, with a blocked end
        #    that is neither the root nor using the link as root port.
        self.assertEqual(len(result.blocked_ends),
                         len(topology.links) - len(tree_links))
        for link in topology.links:
            if result.link_roles[link.id()] == "blocked":
                blocked_sw = result.blocked_ends[link.id()]
                self.assertNotEqual(blocked_sw, expected_root)
                self.assertIn(
                    link.other(blocked_sw),
                    result.port_roles[blocked_sw]["blocked"])

        # 7. Step structure: initial -> rounds (last one quiet) -> final.
        steps = result.steps
        self.assertEqual(steps[0]["kind"], "initial")
        self.assertEqual(steps[-1]["kind"], "final")
        self.assertTrue(all(s["kind"] == "round" for s in steps[1:-1]))
        quiet = [s for s in steps[1:-1] if not s["changes"]]
        self.assertEqual(len(quiet), 1,
                         "exactly one confirming round expected")
        self.assertLessEqual(len(steps) - 2, len(switches),
                             "must converge within n rounds")

        # 8. Step 0: everyone believes itself to be the root.
        for sid, info in steps[0]["switches"].items():
            self.assertEqual(info["root"], sid)
            self.assertEqual(info["cost"], 0)
            self.assertIsNone(info["root_port"])

        # 9. Every round step carries one BPDU per link per direction.
        for step in steps[1:-1]:
            self.assertEqual(len(step["events"]), 2 * len(topology.links))
        return result

    def test_triangle(self):
        result = self.check(topologies.triangle())
        self.assertEqual(result.root_id, "S3")
        # Equal costs: the S1-S2 link is blocked on S2 (higher bridge ID).
        self.assertEqual(result.link_roles["S1-S2"], "blocked")
        self.assertEqual(result.blocked_ends["S1-S2"], "S2")

    def test_square_diagonal(self):
        result = self.check(topologies.square_diagonal())
        self.assertEqual(result.root_id, "S2")
        # The direct 19-cost link S2-S4 loses against the two-hop 4+4 path.
        self.assertEqual(result.link_roles["S2-S4"], "blocked")

    def test_classic6(self):
        result = self.check(topologies.classic6())
        self.assertEqual(result.root_id, "S4")

    def test_random_topologies(self):
        # n >= 10 covers two-digit ids (S10 sorts before S9), which once
        # defeated the duplicate-pair check in the generator.
        for n in (3, 4, 5, 6, 8, 10, 12, 15):
            for seed in range(3):
                self.check(topologies.random_topology(n, seed))


class DeterminismTests(unittest.TestCase):
    def test_same_seed_same_document(self):
        def doc():
            return generate.build_document(
                "random", topologies.random_topology(7, seed=11))[0]
        self.assertEqual(json.dumps(doc(), sort_keys=True),
                         json.dumps(doc(), sort_keys=True))

    def test_different_seed_different_topology(self):
        a = generate.serialize_topology(topologies.random_topology(6, seed=1))
        b = generate.serialize_topology(topologies.random_topology(6, seed=2))
        self.assertNotEqual(a, b)


class ValidationTests(unittest.TestCase):
    def make(self, switches, links):
        return stp.Topology(switches=switches, links=links)

    def base_switches(self, count=3):
        return topologies._switches(count, [32768] * count)

    def test_rejects_disconnected(self):
        with self.assertRaises(ValueError):
            stp.validate(self.make(
                self.base_switches(3), [stp.Link("S1", "S2", 1)]))

    def test_rejects_duplicate_link(self):
        with self.assertRaises(ValueError):
            stp.validate(self.make(
                self.base_switches(2),
                [stp.Link("S1", "S2", 1), stp.Link("S2", "S1", 1)]))

    def test_rejects_self_loop(self):
        with self.assertRaises(ValueError):
            stp.validate(self.make(
                self.base_switches(1), [stp.Link("S1", "S1", 1)]))

    def test_rejects_zero_cost(self):
        with self.assertRaises(ValueError):
            stp.validate(self.make(
                self.base_switches(2), [stp.Link("S1", "S2", 0)]))

    def test_rejects_unknown_switch(self):
        with self.assertRaises(ValueError):
            stp.validate(self.make(
                self.base_switches(2), [stp.Link("S1", "S9", 1)]))

    def test_rejects_duplicate_ids(self):
        switches = [stp.Switch("S1", 32768, "00:01"), stp.Switch("S1", 32768, "00:02")]
        with self.assertRaises(ValueError):
            stp.validate(self.make(switches, [stp.Link("S1", "S1", 1)]))

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            stp.validate(stp.Topology(switches=[], links=[]))

    def test_random_requires_three_switches(self):
        with self.assertRaises(ValueError):
            topologies.random_topology(2, seed=1)


class GeneratorTests(unittest.TestCase):
    def test_cli_produces_html_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "out.html"
            json_path = Path(tmp) / "steps.json"
            generate.main(["-t", "classic-6", "-o", str(html_path),
                           "--json", str(json_path)])
            html = html_path.read_text(encoding="utf-8")
            self.assertTrue(html.startswith("<!DOCTYPE html>"))
            self.assertNotIn(generate.DATA_PLACEHOLDER, html)
            self.assertIn("经典 STP", html)

            document = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("steps", document)
            self.assertIn("topology", document)
            self.assertTrue(document["steps"][-1]["kind"] == "final")

    def test_template_has_placeholder(self):
        template = generate.TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn(generate.DATA_PLACEHOLDER, template)

    def test_render_escapes_closing_script_tag(self):
        document = {"steps": [{"description": "</script>"}]}
        html = generate.render_html(
            document, "before __DATA__ mid /*__PLAYER__*/ after")
        self.assertIn("<\\/script>", html)   # payload escaped, JSON still valid
        self.assertEqual(html.count("</script>"), 0)


if __name__ == "__main__":
    unittest.main()
