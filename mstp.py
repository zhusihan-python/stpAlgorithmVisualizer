"""PVST+ and MSTP (multi-instance spanning tree) on the STP step pipeline.

Both protocols run several independent spanning-tree computations over the
same physical topology — the difference is only what an "instance" is:

- PVST+ (Cisco): one instance **per VLAN**, so each VLAN can have its own
  root bridge and its own tree. Redundant links end up forwarding for
  different VLANs (load balancing).
- MSTP (IEEE 802.1s): VLANs are mapped to a few **MST instances**; every
  VLAN in an instance shares that instance's tree (fewer trees than VLANs).
  Region/IST/CST inter-region details are out of scope for this teaching
  model; the demo shows the VLAN-to-instance mapping and per-instance
  trees inside a single region.

An instance is realised by cloning the topology with per-instance switch
priorities (the root is influenced per instance) and running the classic
``stp.simulate`` on it; every step is tagged with the instance id.
"""

from dataclasses import dataclass, field
from typing import Dict, List

import stp


@dataclass(frozen=True)
class Instance:
    id: str                       # e.g. "VLAN 10" or "MST1"
    vlans: List[str]              # VLANs carried by this instance
    priority_overrides: Dict[str, int] = field(default_factory=dict)


@dataclass
class MultiResult:
    instances: List[dict]         # [{id, vlans, steps, root_id, link_roles}]
    roots: Dict[str, str]         # instance id -> root switch


def instance_topology(topology: stp.Topology, instance: Instance) -> stp.Topology:
    """Clone the topology with the instance's per-switch priorities."""
    switches = [
        stp.Switch(
            id=s.id,
            priority=instance.priority_overrides.get(s.id, s.priority),
            mac=s.mac,
        )
        for s in topology.switches
    ]
    return stp.Topology(switches=switches, links=list(topology.links))


def simulate_multi(topology: stp.Topology, instances: List[Instance],
                   mode: str) -> MultiResult:
    """Run one classic STP simulation per instance.

    ``mode`` is "pvst" or "mstp"; it only shapes the narration text.
    """
    stp.validate(topology)
    if not instances:
        raise ValueError("need at least one instance")

    out = []
    roots: Dict[str, str] = {}
    for index, instance in enumerate(instances, 1):
        topo_i = instance_topology(topology, instance)
        result = stp.simulate(topo_i)
        roots[instance.id] = result.root_id

        vlan_text = "、".join(v for v in instance.vlans)
        if mode == "pvst":
            header = (
                f"实例 {index}/{len(instances)}（{instance.id}）："
                f"PVST+ 为每个 VLAN 单独运行一棵生成树。"
            )
            tree_text = (
                f"{instance.id} 的树：根桥 {result.root_id}。切换上方标签对比"
                "其他 VLAN——不同 VLAN 的阻塞端口不同，冗余链路因此为不同"
                "VLAN 分担流量。"
            )
        else:
            header = (
                f"实例 {index}/{len(instances)}（{instance.id}，承载 VLAN "
                f"{vlan_text}）：MSTP 把多个 VLAN 映射到同一个实例，共享一棵树。"
            )
            tree_text = (
                f"{instance.id} 的树：根桥 {result.root_id}；这些 VLAN 共用该树。"
                f"对比 PVST+ 为每个 VLAN 建一棵树，MSTP 用 "
                f"{len(instances)} 棵树承载了 {sum(len(i.vlans) for i in instances)} 个 VLAN。"
            )

        steps = [dict(step, instance=instance.id) for step in result.steps]
        steps[0]["description"] = header + steps[0]["description"]
        steps[-1]["description"] += tree_text
        out.append({
            "id": instance.id,
            "vlans": list(instance.vlans),
            "steps": steps,
            "root_id": result.root_id,
            "link_roles": result.link_roles,
        })

    return MultiResult(instances=out, roots=roots)
