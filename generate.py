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

import concepts
import mstp
import rstp
import stp
import topologies

TEMPLATE_PATH = Path(__file__).with_name("template.html")
PLAYER_PATH = Path(__file__).with_name("player.js")
DATA_PLACEHOLDER = "__DATA__"
PLAYER_PLACEHOLDER = "/*__PLAYER__*/"


def serialize_topology(topology: stp.Topology, hosts=(), appear=None) -> dict:
    """Serialize a topology; `appear` marks links/switches that join the
    story mid-animation with the step index at which they appear."""
    def appear_at(key):
        return {"appear_at": appear[key]} if appear and key in appear else {}

    return {
        "switches": [
            {
                "id": s.id,
                "priority": s.priority,
                "mac": s.mac,
                "bridge_id": s.bridge_id,
                **appear_at(s.id),
            }
            for s in topology.switches
        ],
        "links": [
            {"id": link.id(), "a": link.a, "b": link.b, "cost": link.cost,
             **appear_at(link.id())}
            for link in topology.links
        ],
        "hosts": [{"id": h.id, "attached_to": h.attached_to} for h in hosts],
    }


def build_document(name: str, topology: stp.Topology, protocol: str = "stp",
                   seed: int = 42, positions=None):
    """Run the simulation and return (embedded document, summary lines).

    ``positions`` maps switch id -> (x, y) normalized to 0..1; when given
    the player uses them instead of the circular layout."""
    concept = concepts.for_protocol(protocol, name)

    def add_positions(document):
        if positions:
            document["positions"] = {
                sid: {"x": round(x, 4), "y": round(y, 4)}
                for sid, (x, y) in positions.items()}
        return document
    if protocol in ("pvst", "mstp"):
        instances = topologies.build_instances(protocol, name, topology, seed)
        result = mstp.simulate_multi(topology, instances, protocol)
        vlan_count = sum(len(i.vlans) for i in instances)
        title = ("PVST+ 逐步动画（每 VLAN 一棵树）" if protocol == "pvst"
                 else "MSTP（802.1s）逐步动画（多 VLAN 映射实例）")
        document = {
            "protocol": protocol,
            "title": title,
            "subtitle": (
                f"拓扑 {name} · {len(topology.switches)} 台交换机 · "
                f"{len(topology.links)} 条链路 · {len(instances)} 个实例 · "
                f"{vlan_count} 个 VLAN"
            ),
            "topology": serialize_topology(topology),
            "concept": concept,
            "instances": result.instances,
        }
        return add_positions(document), result

    if protocol == "rstp":
        hosts = [rstp.Host("PC1", topologies.default_host_switch(name, topology, seed))]
        result = rstp.simulate_rstp(topology, hosts)
        failure = (f" · 故障演示 {result.failed_link}" if result.failed_link
                   else " · 无冗余链路，跳过故障演示")
        added = (f" · 新增链路 {'、'.join(result.added_links)}"
                 if result.added_links else "")
        joined = (f" · 上线 {len(result.joined_switches)} 台交换机"
                  if result.joined_switches else "")
        document = {
            "protocol": "rstp",
            "title": "RSTP（802.1w）逐步动画",
            "subtitle": (
                f"拓扑 {name} · {len(topology.switches)} 台交换机 · "
                f"{len(topology.links)} 条链路 · {len(result.steps)} 步"
                f"{failure}{added}{joined}"
            ),
            "topology": serialize_topology(result.final_topology,
                                           result.hosts, result.appear),
            "concept": concept,
            "steps": result.steps,
        }
        return add_positions(document), result

    result = stp.simulate(topology)
    document = {
        "protocol": "stp",
        "title": "经典 STP（802.1D）逐步动画",
        "subtitle": (
            f"拓扑 {name} · {len(topology.switches)} 台交换机 · "
            f"{len(topology.links)} 条链路 · 收敛于 {len(result.steps)} 步"
        ),
        "topology": serialize_topology(topology),
        "concept": concept,
        "steps": result.steps,
    }
    return add_positions(document), result


def render_html(document: dict, template: str, player_js: str = None) -> str:
    if DATA_PLACEHOLDER not in template:
        raise RuntimeError("template.html is missing the __DATA__ placeholder")
    if player_js is None:
        player_js = PLAYER_PATH.read_text(encoding="utf-8")
    if PLAYER_PLACEHOLDER not in template:
        raise RuntimeError("template.html is missing the player placeholder")
    if DATA_PLACEHOLDER in player_js:
        raise RuntimeError("player.js must not contain the data placeholder")
    payload = json.dumps(document, ensure_ascii=False).replace("</", "<\\/")
    return (template
            .replace(DATA_PLACEHOLDER, payload)
            .replace(PLAYER_PLACEHOLDER, player_js))


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
        "-p", "--protocol", choices=("stp", "rstp", "pvst", "mstp"),
        default="stp",
        help="protocol to animate (default: stp)",
    )
    parser.add_argument(
        "-f", "--topology-file", metavar="FILE",
        help="custom topology JSON instead of a built-in sample "
             "(schema: see topologies.from_file)",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="output HTML file (default: stp.html / rstp.html by protocol)",
    )
    parser.add_argument(
        "--json", metavar="FILE",
        help="also dump the raw step data as JSON",
    )
    args = parser.parse_args(argv)
    output = args.output or (f"{args.protocol}.html")

    positions = None
    if args.topology_file:
        topology, positions = topologies.from_file(args.topology_file)
        topology_name = "custom"
    else:
        topology = topologies.BUILDERS[args.topology](args)
        topology_name = args.topology
    stp.validate(topology)
    document, result = build_document(
        topology_name, topology, protocol=args.protocol, seed=args.seed,
        positions=positions)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    Path(output).write_text(render_html(document, template), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"written: {output}")
    print(f"  protocol={args.protocol} topology={args.topology} "
          f"switches={len(topology.switches)} links={len(topology.links)}")
    if args.protocol in ("pvst", "mstp"):
        for inst in result.instances:
            print(f"  instance={inst['id']} vlans={','.join(inst['vlans'])} "
                  f"steps={len(inst['steps'])} root={inst['root_id']}")
    elif args.protocol == "rstp":
        forwarding = sum(1 for r in result.link_roles.values() if r == "forwarding")
        alternates = sum(1 for r in result.link_roles.values() if r == "alternate")
        print(f"  steps={len(result.steps)} root={result.root_id} "
              f"forwarding={forwarding} alternate={alternates} "
              f"failed_link={result.failed_link} "
              f"added_links={','.join(result.added_links) or '-'} "
              f"joined={','.join(result.joined_switches) or '-'}")
    else:
        blocked = len(result.link_roles) - sum(
            1 for r in result.link_roles.values() if r == "tree")
        print(f"  steps={len(result.steps)} root={result.root_id} "
              f"blocked_links={blocked}")
    if args.json:
        print(f"written: {args.json}")


if __name__ == "__main__":
    main()
