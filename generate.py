#!/usr/bin/env python3
"""Generate a self-contained STP step-animation HTML file.

Examples:
    python3 generate.py                          # triangle sample -> stp.html
    python3 generate.py -t classic-6 -o out.html
    python3 generate.py -t random -n 8 --seed 7 --json steps.json
"""

import argparse
import json
from pathlib import Path

import stp
import topologies

TEMPLATE_PATH = Path(__file__).with_name("template.html")
DATA_PLACEHOLDER = "__DATA__"


def serialize_topology(topology: stp.Topology) -> dict:
    return {
        "switches": [
            {
                "id": s.id,
                "priority": s.priority,
                "mac": s.mac,
                "bridge_id": s.bridge_id,
            }
            for s in topology.switches
        ],
        "links": [
            {"id": link.id(), "a": link.a, "b": link.b, "cost": link.cost}
            for link in topology.links
        ],
    }


def build_document(name: str, topology: stp.Topology):
    """Run the simulation and return (embedded document, simulation result)."""
    result = stp.simulate(topology)
    document = {
        "title": "经典 STP（802.1D）逐步动画",
        "subtitle": (
            f"拓扑 {name} · {len(topology.switches)} 台交换机 · "
            f"{len(topology.links)} 条链路 · 收敛于 {len(result.steps)} 步"
        ),
        "topology": serialize_topology(topology),
        "steps": result.steps,
    }
    return document, result


def render_html(document: dict, template: str) -> str:
    if DATA_PLACEHOLDER not in template:
        raise RuntimeError("template.html is missing the __DATA__ placeholder")
    payload = json.dumps(document, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(DATA_PLACEHOLDER, payload)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "-t", "--topology", default="triangle",
        choices=sorted(topologies.BUILDERS),
        help="topology to animate (default: triangle)",
    )
    parser.add_argument(
        "-n", "--nodes", type=int, default=6,
        help="switch count for the random topology (default: 6)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="seed for the random topology (default: 42)",
    )
    parser.add_argument(
        "-o", "--output", default="stp.html",
        help="output HTML file (default: stp.html)",
    )
    parser.add_argument(
        "--json", metavar="FILE",
        help="also dump the raw step data as JSON",
    )
    args = parser.parse_args(argv)

    topology = topologies.BUILDERS[args.topology](args)
    stp.validate(topology)
    document, result = build_document(args.topology, topology)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    Path(args.output).write_text(render_html(document, template), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    blocked = len(result.link_roles) - sum(
        1 for r in result.link_roles.values() if r == "tree")
    print(f"written: {args.output}")
    print(f"  topology={args.topology} switches={len(topology.switches)} "
          f"links={len(topology.links)}")
    print(f"  steps={len(result.steps)} root={result.root_id} blocked_links={blocked}")
    if args.json:
        print(f"written: {args.json}")


if __name__ == "__main__":
    main()
