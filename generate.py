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
DATA_PLACEHOLDER = "__DATA__"


def serialize_topology(topology: stp.Topology, hosts=()) -> dict:
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
        "hosts": [{"id": h.id, "attached_to": h.attached_to} for h in hosts],
    }


def build_document(name: str, topology: stp.Topology, protocol: str = "stp",
                   seed: int = 42):
    """Run the simulation and return (embedded document, summary lines)."""
    concept = concepts.for_protocol(protocol, name)
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
        return document, result

    if protocol == "rstp":
        hosts = [rstp.Host("PC1", topologies.default_host_switch(name, topology, seed))]
        result = rstp.simulate_rstp(topology, hosts)
        failure = (f" · 故障演示 {result.failed_link}" if result.failed_link
                   else " · 无冗余链路，跳过故障演示")
        document = {
            "protocol": "rstp",
            "title": "RSTP（802.1w）逐步动画",
            "subtitle": (
                f"拓扑 {name} · {len(topology.switches)} 台交换机 · "
                f"{len(topology.links)} 条链路 · {len(result.steps)} 步{failure}"
            ),
            "topology": serialize_topology(topology, result.hosts),
            "concept": concept,
            "steps": result.steps,
        }
        return document, result

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
        "-p", "--protocol", choices=("stp", "rstp", "pvst", "mstp"),
        default="stp",
        help="protocol to animate (default: stp)",
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

    topology = topologies.BUILDERS[args.topology](args)
    stp.validate(topology)
    document, result = build_document(args.topology, topology,
                                      protocol=args.protocol, seed=args.seed)

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
              f"failed_link={result.failed_link}")
    else:
        blocked = len(result.link_roles) - sum(
            1 for r in result.link_roles.values() if r == "tree")
        print(f"  steps={len(result.steps)} root={result.root_id} "
              f"blocked_links={blocked}")
    if args.json:
        print(f"written: {args.json}")


if __name__ == "__main__":
    main()
