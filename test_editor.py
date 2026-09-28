"""Tests for the local editor server and the player/editor packaging."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import generate
import serve

TRIANGLE_PAYLOAD = {
    "topology": {
        "switches": [
            {"id": "S1", "priority": 32768, "mac": "00:00:00:00:00:01",
             "x": 0.5, "y": 0.1},
            {"id": "S2", "priority": 32768, "mac": "00:00:00:00:00:02",
             "x": 0.15, "y": 0.8},
            {"id": "S3", "priority": 8192, "mac": "00:00:00:00:00:03",
             "x": 0.85, "y": 0.8},
        ],
        "links": [
            {"a": "S1", "b": "S2", "cost": 4},
            {"a": "S1", "b": "S3", "cost": 4},
            {"a": "S2", "b": "S3", "cost": 4},
        ],
    },
    "protocol": "rstp",
    "seed": 7,
}


class GenerateEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_all_protocols_generate(self):
        for protocol, steps_key in (("stp", "steps"), ("rstp", "steps")):
            status, doc = self.post({**TRIANGLE_PAYLOAD, "protocol": protocol})
            self.assertEqual(status, 200)
            self.assertIn(steps_key, doc)
            self.assertIn("concept", doc)
            self.assertIn("positions", doc)  # editor coords honored
        for protocol in ("pvst", "mstp"):
            status, doc = self.post({**TRIANGLE_PAYLOAD, "protocol": protocol})
            self.assertEqual(status, 200)
            self.assertIn("instances", doc)

    def test_validation_errors_return_400(self):
        cases = [
            {"topology": {"switches": [{"id": "A"}, {"id": "B"}],
                          "links": []}},  # disconnected
            {**TRIANGLE_PAYLOAD,
             "topology": {**TRIANGLE_PAYLOAD["topology"],
                          "links": TRIANGLE_PAYLOAD["topology"]["links"][:1]}},
            {**TRIANGLE_PAYLOAD, "protocol": "spbm"},
        ]
        for body in cases:
            status, doc = self.post(body)
            self.assertEqual(status, 400, str(body))
            self.assertIn("error", doc)

    def test_bad_json_returns_400(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/generate",
            data=b"{not json", method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected 400")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 400)
            self.assertIn("error", json.loads(err.read().decode("utf-8")))


class PackagingTests(unittest.TestCase):
    def test_render_inlines_player(self):
        template = generate.TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn(generate.PLAYER_PLACEHOLDER, template)
        html = generate.render_html({"title": "x", "topology": {"switches": [],
                                                                "links": []}},
                                    template)
        self.assertNotIn(generate.PLAYER_PLACEHOLDER, html)
        self.assertIn("bootPlayer", html)
        self.assertIn("PLAYER_DATA", html)

    def test_player_js_contract(self):
        source = generate.PLAYER_PATH.read_text(encoding="utf-8")
        self.assertNotIn(generate.DATA_PLACEHOLDER, source)
        self.assertIn("window.bootPlayer", source)
        # Every DOM id the player needs exists in both host pages.
        ids = ["stage", "btn-first", "btn-prev", "btn-play", "btn-next",
               "btn-last", "speed", "btn-concept", "counter", "desc",
               "events", "tabs", "title", "subtitle",
               "concept-modal", "concept-body", "concept-close"]
        editor = Path("editor.html").read_text(encoding="utf-8")
        template = generate.TEMPLATE_PATH.read_text(encoding="utf-8")
        for i in ids:
            self.assertIn(f'id="{i}"', template, f"template missing #{i}")
            self.assertIn(f'id="{i}"', editor, f"editor missing #{i}")

    def test_editor_page_loads_assets(self):
        editor = Path("editor.html").read_text(encoding="utf-8")
        self.assertIn('src="player.js"', editor)
        self.assertIn('src="editor.js"', editor)
        editor_js = Path("editor.js").read_text(encoding="utf-8")
        self.assertIn("window.EDITOR", editor_js)
        self.assertIn("/generate", editor_js)


if __name__ == "__main__":
    unittest.main()
