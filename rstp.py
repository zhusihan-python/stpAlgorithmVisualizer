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
- The player chains every topology-change story by default (each phase is
  skipped automatically when the topology cannot demonstrate it):
    1. boot: election rounds + proposal/agreement cascade,
    2. link failure: the victim promotes an alternate port immediately,
    3. a new *worse* link appears: nobody accepts it, the tree is not
       disturbed at all,
    4. a new *better* link appears: the improving switch migrates its root
       port and the affected subtree re-handshakes.

Every phase's final state equals a fresh ``stp.simulate`` of the topology
as it stands after that phase (asserted by the tests), so the narrative
steps can never drift from the algorithm.

Step schema is the one produced by ``stp.simulate``, extended with:
``phase`` (boot/cascade/failure/link-add), ``links`` (per-step link visual
state), ``blocked_ends`` alongside ``links``, and events optionally
carrying ``kind`` ("proposal"/"agreement") plus ``delay`` (fraction of a
packet flight, for the reply direction).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import stp
from topologies import COST_GIGA

COST_NEW_LINK = COST_GIGA  # cost of a candidate "better" link (1 Gbps)


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
    added_links: List[str] = field(default_factory=list)  # ids of added links
    link_roles: Dict[str, str] = field(default_factory=dict)
    final_links: List[stp.Link] = field(default_factory=list)  # cumulative


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


# --------------------------------------------------------------------------
# Link-add scenarios

def _non_adjacent_pairs(topology: stp.Topology) -> List[Tuple[str, str]]:
    linked = {link.pair() for link in topology.links}
    ids = [s.id for s in topology.switches]
    pairs = [tuple(sorted((a, b)))
             for i, a in enumerate(ids) for b in ids[i + 1:]]
    return [pair for pair in sorted(pairs) if pair not in linked]


def _pick_added_links(topology: stp.Topology,
                      sim: stp.SimulationResult
                      ) -> Tuple[Optional[stp.Link], Optional[stp.Link]]:
    """Deterministically pick demo links to add:

    - worse: the first non-adjacent pair, cost = |root-cost difference| + 4,
      which is strictly worse for both endpoints (and therefore for
      everyone), so the tree is not disturbed at all;
    - better: the first other non-adjacent pair where a cost-4 link would
      improve one side's root path (triggering a root-port migration).
    """
    costs = sim.steps[-1]["switches"]
    worse = None
    better = None
    for a, b in _non_adjacent_pairs(topology):
        if worse is None:
            cost = abs(costs[a]["cost"] - costs[b]["cost"]) + COST_NEW_LINK
            worse = stp.Link(a, b, cost)
        if better is None and (a, b) != worse.pair():
            ca, cb = costs[a]["cost"], costs[b]["cost"]
            if ca > cb + COST_NEW_LINK or cb > ca + COST_NEW_LINK:
                better = stp.Link(a, b, COST_NEW_LINK)
        if worse is not None and better is not None:
            break
    return worse, better


def _designated_side(sim: stp.SimulationResult, link: stp.Link) -> str:
    """The designated switch of `link` according to `sim`'s port roles."""
    if link.b in sim.port_roles[link.a]["designated"]:
        return link.a
    return link.b


def _worse_link_phase(topology: stp.Topology, sim: stp.SimulationResult,
                      link: stp.Link, steps: List[dict],
                      link_state: Dict[str, str], edge_note: str,
                      repair_of: Optional[str]) -> stp.SimulationResult:
    """Add a link nobody wants: proposal goes out, the peer replies with its
    own superior BPDU instead of an agreement, link stays alternate, the
    existing tree is untouched."""
    topo2 = stp.Topology(list(topology.switches), topology.links + [link])
    sim2 = stp.simulate(topo2)
    states = sim2.steps[-1]["switches"]

    designated = _designated_side(sim2, link)
    other = link.other(designated)
    name = link.id().replace("-", "–")
    appear_text = (f"之前断开的 {name} 链路修复重连" if repair_of == link.id()
                   else f"新增链路 {name}（成本 {link.cost}）")

    up_state = dict(link_state)
    up_state[link.id()] = "pending"
    steps.append({
        "kind": "link-up",
        "phase": "link-add",
        "round": 0,
        "description": (
            f"{appear_text}。RSTP 中新链路两侧先处于 Discarding："
            f"{designated} 一侧作为指定桥发出提案，等待对方比较。{edge_note}"
        ),
        "switches": states,
        "events": [],
        "changes": [],
        "links": up_state,
        "blocked_ends": dict(sim.blocked_ends),
    })

    settled = dict(up_state)
    settled[link.id()] = "alternate"
    steps.append({
        "kind": "handshake",
        "phase": "link-add",
        "round": 1,
        "description": (
            f"{other} 比较（根桥 ID、总成本、发送者桥 ID）后发现经新链路并不更优，"
            f"于是不回送同意，而是继续宣告自己的信息（根={states[other]['root']}，"
            f"成本={states[other]['cost']}）。提案得不到同意，{designated} 侧保持 "
            f"Discarding——新链路停在备用，现有树零扰动。"
        ),
        "switches": states,
        "events": [
            {"kind": "proposal", "from": designated, "to": other},
            {"kind": "bpdu", "from": other, "to": designated, "delay": 0.6,
             "root": states[other]["root"], "cost": states[other]["cost"]},
        ],
        "changes": [other],
        "links": settled,
        "blocked_ends": dict(sim2.blocked_ends),
    })

    steps.append({
        "kind": "final",
        "phase": "link-add-worse-final",
        "round": 1,
        "description": (
            "结论：新增的劣链路对生成树没有任何影响——转发链路一条未变，"
            "新链路两侧端口为指定（Discarding）/ 备用。只有当新链路提供"
            "更优的根路径时，RSTP 才会触发切换。"
        ),
        "switches": states,
        "events": [],
        "changes": [],
        "roles": {
            "root": sim2.root_id,
            "links": {lid: ("tree" if s == "forwarding" else "blocked")
                      for lid, s in settled.items()},
            "blocked_ends": sim2.blocked_ends,
            "ports": sim2.port_roles,
        },
        "links": settled,
        "blocked_ends": sim2.blocked_ends,
    })
    return sim2


def _better_link_phase(topology: stp.Topology, sim: stp.SimulationResult,
                       link: stp.Link, steps: List[dict],
                       link_state: Dict[str, str]
                       ) -> stp.SimulationResult:
    """Add a link that improves someone's root path: the improving switch
    migrates its root port, flips links that lose their role to alternate,
    and re-handshakes the affected subtree."""
    topo3 = stp.Topology(list(topology.switches), topology.links + [link])
    sim3 = stp.simulate(topo3)
    states = sim3.steps[-1]["switches"]

    changed = [sid for sid in states
               if sim3.port_roles[sid]["root_port"] !=
               sim.port_roles[sid]["root_port"]]
    migrator = link.a if sim3.port_roles[link.a]["root_port"] == link.b \
        else link.b
    parent = link.other(migrator)
    old_rp = sim.port_roles[migrator]["root_port"]

    up_state = dict(link_state)
    up_state[link.id()] = "pending"
    steps.append({
        "kind": "link-up",
        "phase": "link-add",
        "round": 0,
        "description": (
            f"新增链路 {link.id().replace('-', '–')}（成本 {link.cost}）："
            f"{migrator} 发现经它到根桥的总成本从 "
            f"{sim.steps[-1]['switches'][migrator]['cost']} 降到 "
            f"{states[migrator]['cost']}，比现有路径更优。"
        ),
        "switches": states,
        "events": [],
        "changes": [],
        "links": up_state,
        "blocked_ends": dict(sim.blocked_ends),
    })

    # Links that lose their forwarding role flip to alternate; the subtree
    # links that must re-handshake go pending during the sync.
    flips = [lid for lid, role in sim3.link_roles.items()
             if role == "blocked" and sim.link_roles.get(lid) == "tree"]
    cascade = _tree_bfs_order(topo3, sim3, sim3.root_id)
    pending = [l.id() for l, _, child in cascade
               if child in changed and l.id() != link.id()]

    settled = dict(up_state)
    settled[link.id()] = "forwarding"
    for lid in flips:
        settled[lid] = "alternate"
    for lid in pending:
        settled[lid] = "pending"
    steps.append({
        "kind": "handshake",
        "phase": "link-add",
        "round": 1,
        "description": (
            f"{parent} 的提案到达时，{migrator} 把根端口从 →{old_rp} 迁移到 "
            f"→{parent}：先同步（受影响的下游端口暂时 Discarding），再回送同意，"
            "新链路立即进入转发。"
        ),
        "switches": states,
        "events": [
            {"kind": "proposal", "from": parent, "to": migrator},
            {"kind": "agreement", "from": migrator, "to": parent, "delay": 0.6},
        ],
        "changes": [migrator],
        "links": settled,
        "blocked_ends": sim3.blocked_ends,
    })

    resync = dict(settled)
    for i, (l, p, child) in enumerate(
            [c for c in cascade if c[2] in changed and c[0].id() != link.id()],
            2):
        resync[l.id()] = "forwarding"
        steps.append({
            "kind": "handshake",
            "phase": "link-add",
            "round": i,
            "description": (
                f"子树重新同步：{p} 的指定端口重新提案，{child} 同意后链路"
                "恢复转发。"
            ),
            "switches": states,
            "events": [
                {"kind": "proposal", "from": p, "to": child},
                {"kind": "agreement", "from": child, "to": p, "delay": 0.6},
            ],
            "changes": [child],
            "links": dict(resync),
            "blocked_ends": sim3.blocked_ends,
        })

    steps.append({
        "kind": "final",
        "phase": "link-add-better-final",
        "round": len(pending) + 1,
        "description": (
            f"更优链路接入完成：{migrator} 改经 {link.id().replace('-', '–')} "
            f"到达根桥（本相位共 {len(changed)} 台交换机调整了根端口），"
            "切换只是一次握手加子树重同步，全程无定时器等待。"
        ),
        "switches": states,
        "events": [],
        "changes": [],
        "roles": {
            "root": sim3.root_id,
            "links": {lid: ("tree" if s == "forwarding" else "blocked")
                      for lid, s in resync.items()},
            "blocked_ends": sim3.blocked_ends,
            "ports": sim3.port_roles,
        },
        "links": resync,
        "blocked_ends": sim3.blocked_ends,
    })
    return sim3


def _link_between(topology: stp.Topology, a: str, b: str) -> stp.Link:
    for link in topology.links:
        if link.pair() == tuple(sorted((a, b))):
            return link
    raise KeyError(f"no link between {a} and {b}")


def simulate_rstp(topology: stp.Topology, hosts=(),
                  include_failure: bool = True,
                  include_link_add: bool = True) -> RstpResult:
    """Boot convergence, then every topology-change story in sequence
    (each skipped automatically when the topology cannot show it)."""
    stp.validate(topology)
    hosts = list(hosts)
    validate_hosts(topology, hosts)

    base = stp.simulate(topology)
    root_id = base.root_id
    converged = base.steps[-1]["switches"]

    edge_note = ""
    if hosts:
        attached = "、".join(f"{h.id}→{h.attached_to}" for h in hosts)
        edge_note = f"边缘端口（{attached}）不受影响。"

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
    link_state = dict(boot_link_state)
    cascade = _tree_bfs_order(topology, base, root_id)
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

    # Running state across the remaining phases.
    topo_now = topology
    sim_now = base
    ls_now = dict(link_state)

    # ---- Phase 3: link failure and alternate promotion ----
    failed_link_id = None
    failed = pick_failure_link(topology, base) if include_failure else None
    if failed is None:
        if include_failure:
            steps[-1]["description"] += " 本拓扑没有可用的冗余链路，跳过故障演示。"
    else:
        fail_link, victim, parent = failed
        failed_link_id = fail_link.id()
        pruned = stp.Topology(
            switches=list(topo_now.switches),
            links=[l for l in topo_now.links if l.id() != failed_link_id])
        after = stp.simulate(pruned)
        after_converged = after.steps[-1]["switches"]
        new_root_port = after.port_roles[victim]["root_port"]

        subtree = _tree_bfs_order(pruned, after, victim,
                                  blocked_from=new_root_port)
        subtree_ids = {link.id() for link, _, _ in subtree}

        down_state = dict(ls_now)
        down_state[failed_link_id] = "down"
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

        upstream = new_root_port
        upstream_is_designated = (
            after.port_roles[upstream]["designated"] and
            victim in after.port_roles[upstream]["designated"])
        p_parent, p_child = (upstream, victim) if upstream_is_designated \
            else (victim, upstream)
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

        failure_state = {
            link.id(): ("down" if link.id() == failed_link_id
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
                "约 50 秒。" + edge_note
            ),
            "switches": after_converged,
            "events": [],
            "changes": [],
            "roles": {
                "root": after.root_id,
                "links": {lid: ("tree" if s == "forwarding" else "blocked")
                          for lid, s in failure_state.items()},
                "blocked_ends": after.blocked_ends,
                "ports": after.port_roles,
            },
            "links": failure_state,
            "blocked_ends": after.blocked_ends,
        })
        topo_now = pruned
        sim_now = after
        ls_now = failure_state

    # ---- Phase 4: link-add demonstrations (worse, then better) ----
    added_ids: List[str] = []
    if include_link_add:
        worse, better = _pick_added_links(topo_now, sim_now)
        if worse is not None:
            sim_now = _worse_link_phase(
                topo_now, sim_now, worse, steps, ls_now, edge_note,
                repair_of=failed_link_id)
            topo_now = stp.Topology(list(topo_now.switches),
                                    topo_now.links + [worse])
            ls_now = {lid: s for lid, s in steps[-1]["links"].items()}
            added_ids.append(worse.id())
        if better is not None:
            sim_now = _better_link_phase(topo_now, sim_now, better, steps, ls_now)
            topo_now = stp.Topology(list(topo_now.switches),
                                    topo_now.links + [better])
            ls_now = {lid: s for lid, s in steps[-1]["links"].items()}
            added_ids.append(better.id())

    return RstpResult(
        steps=steps,
        root_id=sim_now.root_id,
        hosts=hosts,
        failed_link=failed_link_id,
        added_links=added_ids,
        link_roles=dict(ls_now),
        final_links=list(topo_now.links),
    )
