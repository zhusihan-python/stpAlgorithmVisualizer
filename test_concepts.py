"""Tests for the per-protocol concept cards and scenario notes."""

import tempfile
import unittest
from pathlib import Path

import concepts
import generate
import topologies


class ConceptContentTests(unittest.TestCase):
    def check(self, protocol, must_mention):
        topology = topologies.classic6()
        document, _ = generate.build_document("classic-6", topology, protocol)
        concept = document["concept"]
        for key in ("title", "problem", "idea", "rules", "glossary", "scenario"):
            self.assertIn(key, concept)
        self.assertGreaterEqual(len(concept["rules"]), 3)
        self.assertGreaterEqual(len(concept["glossary"]), 3)
        self.assertIn("场景看点", concept["scenario"])
        blob = concept["title"] + concept["problem"] + concept["idea"] + \
            "".join(concept["rules"]) + "".join(
                t + d for t, d in concept["glossary"])
        for word in must_mention:
            self.assertIn(word, blob,
                          f"{protocol} concept should mention {word}")

    def test_stp(self):
        self.check("stp", ["根桥", "BPDU", "生成树", "备用"])

    def test_rstp(self):
        self.check("rstp", ["提案", "同意", "备用", "边缘"])

    def test_pvst(self):
        self.check("pvst", ["VLAN", "负载分担"])

    def test_mstp(self):
        self.check("mstp", ["实例", "负载分担"])

    def test_scenario_notes_vary(self):
        notes = {name: concepts.SCENARIO_NOTES[name]
                 for name in ("triangle", "square-diagonal", "classic-6")}
        self.assertEqual(len(set(notes.values())), len(notes))

    def test_unknown_scenario_gets_generic_note(self):
        concept = concepts.for_protocol("stp", "random")
        self.assertIn("随机", concept["scenario"])

    def test_all_protocols_defined(self):
        self.assertEqual(set(concepts.CONCEPTS),
                         {"stp", "rstp", "pvst", "mstp"})


class EmbeddingTests(unittest.TestCase):
    def test_documents_carry_concept_and_player_has_modal(self):
        template = generate.TEMPLATE_PATH.read_text(encoding="utf-8")
        for hook in ("btn-concept", "concept-modal", "concept-body"):
            self.assertIn(hook, template)
        player = generate.PLAYER_PATH.read_text(encoding="utf-8")
        self.assertIn("buildConceptModal", player)
        builders = {"triangle": topologies.triangle,
                    "classic-6": topologies.classic6,
                    "square-diagonal": topologies.square_diagonal}
        for protocol, name in (("stp", "triangle"), ("rstp", "classic-6"),
                               ("pvst", "square-diagonal"), ("mstp", "classic-6")):
            document, _ = generate.build_document(
                name, builders[name](), protocol)
            self.assertIn("concept", document)

    def test_cli_html_contains_concept_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.html"
            generate.main(["-t", "triangle", "-o", str(out)])
            html = out.read_text(encoding="utf-8")
            self.assertIn("📖 原理", html)
            self.assertIn("广播风暴", html)   # distinctive STP problem text


if __name__ == "__main__":
    unittest.main()
