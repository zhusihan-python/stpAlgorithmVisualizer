"""RSTP (IEEE 802.1w) extension built on the classic STP step pipeline.

Teaching model:

- Election is identical to classic STP (same BPDU priority-vector rounds),
  so ``stp.simulate`` is reused directly. The protocol difference is how
  ports move to *forwarding*:
- Instead of STP's listening/learning timers, a proposal/agreement
  handshake cascades down the tree: the designated port sends a Proposal;
  the neighbour that just selected this port as its root port syncs (its
  other non-edge ports go Discarding) and replies Agreement; the link
  enters Forwarding immediately. Root-bridge ports forward at once.
- Edge ports (links to end stations) are Forwarding from the start and
  never participate in the exchange.
- Optional failure phase: a tree link whose child side owns an alternate
  port goes down; the victim promotes the alternate to root port at once
  (no re-election timers) and the affected subtree re-runs the handshake.

Step schema is the one produced by ``stp.simulate``, extended with:
``phase`` (boot/cascade/failure), ``links`` (per-step link visual state),
``blocked_ends`` alongside ``links``, and events optionally carrying
``kind`` ("proposal"/"agreement") plus ``delay`` (fraction of a packet
flight, for the reply direction).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import stp


@dataclass(frozen=True)
class Host:
    id: str          # e.g. "PC1"
    attached_to: str  # switch id; that switch's port is an edge port


@dataclass
class RstpResult:
    steps: List[dict]
    root_id: str
    hosts: List[Host]
    failed_link: Optional[str]      # link id, or None if no failure phase
    link_roles: Dict[str, str]      # final state: forwarding/alternate/down


def validate_hosts(topology: stp.Topology, hosts) -> None:
    ids = {s.id for s in topology.switches}
    seen = set()
    for host in hosts:
        if host.id in ids or host.id in seen:
            raise ValueError(f"duplicate host id {host.id}")
        if host.attached_to not in ids:
            raise ValueError(f"host {host.id} attaches to unknown switch "
                             f"{host.attached_to}")
        seen.add(host.id)


def pick_failure_link(topology: stp.Topology,
                      base: stp.SimulationResult) -> Optional[Tuple[stp.Link, str, str]]:
    """Choose a tree link to fail: the child side must own an alternate port
    on another link, and the network must stay connected without it.
    Returns (link, victim, parent) or None when there is no redundancy."""
    for link in sorted(topology.links, key=lambda l: l.id()):
        if base.link_roles[link.id()] != "tree":
            continue
        a_is_child = base.port_roles[link.a]["root_port"] == link.b
        b_is_child = base.port_roles[link.b]["root_port"] == link.a
        if a_is_child:
            victim, parent = link.a, link.b
        elif b_is_child:
            victim, parent = link.b, link.a
        else:
            continue
        has_alternate = any(
            other_id != link.id() and end == victim
            for other_id, end in base.blocked_ends.items())
        if not has_alternate:
            continue
        pruned = stp.Topology(
            switches=list(topology.switches),
            links=[l for l in topology.links if l.id() != link.id()])
        try:
            stp.validate(pruned)
        except ValueError:
            continue
        return link, victim, parent
    return None


def _tree_bfs_order(topology: stp.Topology, result: stp.SimulationResult,
                    start: str, blocked_from: Optional[str] = None,
                    ) -> List[Tuple[stp.Link, str, str]]:
    """BFS over tree links from `start`; returns (link, parent, child) in
    discovery order. `blocked_from` excludes the branch back up (the
    neighbour that leads toward the root), for victim subtrees."""
    tree_adj: Dict[str, List[stp.Link]] = {s.id: [] for s in topology.switches}
    for link in topology.links:
        if result.link_roles[link.id()] == "tree":
            tree_adj[link.a].append(link)
            tree_adj[link.b].append(link)
    order = []
    visited = {start}
    if blocked_from is not None:
        visited.add(blocked_from)
    frontier = [start]
    while frontier:
        current = frontier.pop(0)
        for link in tree_adj[current]:
            child = link.other(current)
            if child in visited:
                continue
            visited.add(child)
            order.append((link, current, child))
            frontier.append(child)
    return order


def _handshake_step(link, parent, child, index, total, link_state,
                    blocked_ends, switches) -> dict:
    link_state = dict(link_state)
    link_state[link.id()] = "forwarding"
    return {
        "kind": "handshake",
        "phase": "cascade",
        "round": index,
        "description": (
            f"提案/同意握手（{index}/{total}）：{parent} 的指定端口发出提案"
            f"（Proposal），{child} 完成同步后把该端口选为根端口并回送同意"
            "（Agreement），链路立即进入转发——没有任何定时器等待。"
        ),
        "switches": switches,
        "events": [
            {"kind": "proposal", "from": parent, "to": child},
            {"kind": "agreement", "from": child, "to": parent, "delay": 0.6},
        ],
        "changes": [child],
        "links": link_state,
        "blocked_ends": dict(blocked_ends),
    }


def simulate_rstp(topology: stp.Topology, hosts=(),
                  include_failure: bool = True) -> RstpResult:
    """Boot convergence via proposal/agreement, then an optional link-failure
    recovery phase. Returns the full step list for the player."""
    stp.validate(topology)
    hosts = list(hosts)
    validate_hosts(topology, hosts)

    base = stp.simulate(topology)
    root_id = base.root_id
    converged = base.steps[-1]["switches"]

    edge_note = ""
    if hosts:
        attached = "、".join(f"{h.id}→{h.attached_to}" for h in hosts)
        edge_note = f"边缘端口（{attached}）从现在起直接转发，永不参与生成树计算。"

    # ---- Phase 1: boot (election rounds reused from classic STP) ----
    steps: List[dict] = [{
        "kind": "initial",
        "phase": "boot",
        "round": 0,
        "description": (
            "RSTP 初始状态：所有交换机以自己为根桥，交换机间端口处于 "
            "Discarding（不转发数据）。RSTP 的 BPDU 选举与经典 STP 相同，"
            "区别在于端口如何进入转发。" + edge_note
        ),
        "switches": base.steps[0]["switches"],
        "events": [],
        "changes": [],
    }]
    for step in base.steps[1:-1]:
        steps.append(dict(step, phase="boot"))

    # ---- Phase 2: proposal/agreement cascade down the tree ----
    boot_link_state = {
        link.id(): ("alternate" if base.link_roles[link.id()] == "blocked"
                    else "pending")
        for link in topology.links
    }
    cascade = _tree_bfs_order(topology, base, root_id)
    link_state = dict(boot_link_state)
    total = len(cascade)
    for i, (link, parent, child) in enumerate(cascade, 1):
        steps.append(_handshake_step(
            link, parent, child, i, total, link_state,
            base.blocked_ends, converged))
        link_state[link.id()] = "forwarding"

    steps.append({
        "kind": "final",
        "phase": "boot-final",
        "round": total,
        "description": (
            f"启动收敛完成：根桥 {root_id}，{total} 条树链路通过提案/同意级联"
            "依次进入转发（每跳一次往返），其余链路的端口为备用（Alternate）。"
            "经典 STP 在此处需要每端口 30–50 秒的监听/学习定时器，"
            "RSTP 全程只有消息往返时间。"
        ),
        "switches": converged,
        "events": [],
        "changes": [],
        "roles": {
            "root": root_id,
            "links": {lid: ("tree" if s == "forwarding" else "blocked")
                      for lid, s in link_state.items()},
            "blocked_ends": base.blocked_ends,
            "ports": base.port_roles,
        },
        "links": dict(link_state),
        "blocked_ends": base.blocked_ends,
    })

    failed = None
    if include_failure:
        failed = pick_failure_link(topology, base)

    if failed is None:
        if include_failure:
            steps[-1]["description"] += " 本拓扑没有可用的冗余链路，跳过故障演示。"
        return RstpResult(steps=steps, root_id=root_id, hosts=hosts,
                          failed_link=None, link_roles=link_state)

    # ---- Phase 3: link failure and alternate promotion ----
    fail_link, victim, parent = failed
    pruned = stp.Topology(
        switches=list(topology.switches),
        links=[l for l in topology.links if l.id() != fail_link.id()])
    after = stp.simulate(pruned)
    after_converged = after.steps[-1]["switches"]
    new_root_port = after.port_roles[victim]["root_port"]

    # Links inside the victim's subtree are forced to Discarding by the sync
    # (shown as pending) until they re-handshake.
    subtree = _tree_bfs_order(pruned, after, victim, blocked_from=new_root_port)
    subtree_ids = {link.id() for link, _, _ in subtree}

    down_state = dict(link_state)
    down_state[fail_link.id()] = "down"
    for lid in subtree_ids:
        down_state[lid] = "pending"
    steps.append({
        "kind": "link-down",
        "phase": "failure",
        "round": 0,
        "description": (
            f"链路故障：{fail_link.a}–{fail_link.b} 断开。{victim} 在本地立即检测"
            "（物理信号丢失，无定时器）。同步过程中，"
            + (f"{victim} 子树内其余链路暂时回到 Discarding。"
               if subtree_ids else "该链路下游没有其他树链路。")
            + edge_note
        ),
        "switches": converged,
        "events": [],
        "changes": [victim],
        "links": down_state,
        "blocked_ends": base.blocked_ends,
    })

    # The victim's new root port: designated side (per the pruned roles)
    # proposes, victim agrees, link forwards.
    upstream = new_root_port
    upstream_is_designated = (
        (after.port_roles[upstream]["designated"] and
         victim in after.port_roles[upstream]["designated"]))
    if upstream_is_designated:
        p_parent, p_child = upstream, victim
    else:
        p_parent, p_child = victim, upstream
    promote_link = _link_between(pruned, victim, upstream)
    was_alternate = base.blocked_ends.get(promote_link.id()) == victim
    promote_state = dict(down_state)
    promote_state[promote_link.id()] = "forwarding"
    steps.append({
        "kind": "handshake",
        "phase": "failure",
        "round": 1,
        "description": (
            (f"{victim} 的备用端口（→{upstream}）立即提升为根端口"
             if was_alternate
             else f"{victim} 立即重新选出根端口（→{upstream}）")
            + "——RSTP 不需要重新选举根桥、不等待定时器；提升端口与上游完成"
              "提案/同意握手后立即转发。"
        ),
        "switches": after_converged,
        "events": [
            {"kind": "proposal", "from": p_parent, "to": p_child},
            {"kind": "agreement", "from": p_child, "to": p_parent, "delay": 0.6},
        ],
        "changes": [victim],
        "links": promote_state,
        "blocked_ends": after.blocked_ends,
    })

    # Re-sync the victim's subtree.
    resync_state = dict(promote_state)
    for i, (link, p, c) in enumerate(subtree, 2):
        resync_state[link.id()] = "forwarding"
        steps.append({
            "kind": "handshake",
            "phase": "failure",
            "round": i,
            "description": (
                f"子树重新同步（{i}/{len(subtree) + 1}）：{p} 的指定端口重新提案，"
                f"{c} 同意后链路恢复转发。"
            ),
            "switches": after_converged,
            "events": [
                {"kind": "proposal", "from": p, "to": c},
                {"kind": "agreement", "from": c, "to": p, "delay": 0.6},
            ],
            "changes": [c],
            "links": dict(resync_state),
            "blocked_ends": after.blocked_ends,
        })

    final_state = {
        link.id(): ("down" if link.id() == fail_link.id()
                    else "alternate" if after.link_roles[link.id()] == "blocked"
                    else "forwarding")
        for link in topology.links
    }
    steps.append({
        "kind": "final",
        "phase": "failure-final",
        "round": len(subtree) + 1,
        "description": (
            f"故障收敛完成：{fail_link.a}–{fail_link.b} 仍断开，{victim} 经"
            f"→{upstream} 的路径到达根桥。整个恢复过程只是几次提案/同意往返"
            "（毫秒级）；经典 STP 需要等待 max-age（20s）加监听/学习（30s）"
            "约 50 秒。边缘端口全程不受影响。"
        ),
        "switches": after_converged,
        "events": [],
        "changes": [],
        "roles": {
            "root": after.root_id,
            "links": {lid: ("tree" if s == "forwarding" else "blocked")
                      for lid, s in final_state.items()},
            "blocked_ends": after.blocked_ends,
            "ports": after.port_roles,
        },
        "links": final_state,
        "blocked_ends": after.blocked_ends,
    })

    return RstpResult(steps=steps, root_id=after.root_id, hosts=hosts,
                      failed_link=fail_link.id(), link_roles=final_state)


def _link_between(topology: stp.Topology, a: str, b: str) -> stp.Link:
    for link in topology.links:
        if link.pair() == tuple(sorted((a, b))):
            return link
    raise KeyError(f"no link between {a} and {b}")
