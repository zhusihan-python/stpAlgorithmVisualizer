"""Classic STP (IEEE 802.1D) simulation core.

Pure logic, no I/O, so it can be unit-tested headlessly:

- ``simulate(topology)`` runs a synchronous, round-based BPDU exchange and
  returns every intermediate snapshot (for step-by-step animation) plus the
  final link/port roles.
- Model (the standard teaching simplification of STP): every round, each
  switch sends its current ``(root bridge, root path cost, bridge ID)`` to
  all neighbours, then adopts the best candidate by comparing lowest root
  bridge ID, then lowest total cost, then lowest sender bridge ID.
- At the fixed point every switch believes the same root (the lowest bridge
  ID in the network), root path costs equal shortest-path distances, and
  roles are assigned per link: the side closer to the root (ties broken by
  lower bridge ID) is the designated bridge; the other side's port is either
  its root port (forwarding) or blocked (alternate).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Switch:
    id: str        # display name, e.g. "S1"
    priority: int  # e.g. 32768; lowest (priority, mac) becomes root
    mac: str       # fixed width, e.g. "00:00:00:00:00:01"

    @property
    def bridge_id(self) -> str:
        return f"{self.priority}.{self.mac}"

    def sort_key(self) -> Tuple[int, str]:
        return (self.priority, self.mac)


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    cost: int

    def other(self, switch_id: str) -> str:
        if switch_id == self.a:
            return self.b
        if switch_id == self.b:
            return self.a
        raise KeyError(switch_id)

    def pair(self) -> Tuple[str, ...]:
        return tuple(sorted((self.a, self.b)))

    def id(self) -> str:
        return "-".join(self.pair())


@dataclass
class Topology:
    switches: List[Switch]
    links: List[Link]

    def __post_init__(self) -> None:
        self._by_id = {s.id: s for s in self.switches}

    def switch(self, switch_id: str) -> Switch:
        return self._by_id[switch_id]

    def adjacency(self) -> Dict[str, List[Link]]:
        adj: Dict[str, List[Link]] = {s.id: [] for s in self.switches}
        for link in self.links:
            adj[link.a].append(link)
            adj[link.b].append(link)
        return adj


@dataclass
class SwitchState:
    """What one switch currently believes."""
    root_id: str               # believed root bridge
    cost: int                  # this switch's root path cost
    root_port: Optional[str]   # neighbour the root port points at; None if believed root


@dataclass
class SimulationResult:
    steps: List[dict]              # snapshots for the animation player
    root_id: str                   # elected root bridge
    link_roles: Dict[str, str]     # link id -> "tree" | "blocked"
    blocked_ends: Dict[str, str]   # link id -> switch whose port is blocked
    port_roles: Dict[str, dict]    # switch -> {"root_port", "designated", "blocked"}


def validate(topology: Topology) -> None:
    """Reject topologies the model cannot handle."""
    if not topology.switches:
        raise ValueError("empty topology")
    ids = [s.id for s in topology.switches]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate switch ids")
    seen_pairs = set()
    for link in topology.links:
        if link.a == link.b:
            raise ValueError(f"self-loop on {link.a}")
        if link.a not in ids or link.b not in ids:
            raise ValueError(f"link {link.a}-{link.b} references unknown switch")
        if link.cost < 1:
            raise ValueError(f"link {link.a}-{link.b} cost must be >= 1")
        pair = link.pair()
        if pair in seen_pairs:
            raise ValueError(f"duplicate link between {link.a} and {link.b}")
        seen_pairs.add(pair)
    # Connectedness: flood-fill from the first switch.
    adj = topology.adjacency()
    visited = set()
    frontier = [ids[0]]
    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        frontier.extend(link.other(current) for link in adj[current])
    if visited != set(ids):
        unreachable = sorted(set(ids) - visited)
        raise ValueError(f"topology is not connected; unreachable: {unreachable}")


def _best_candidate(switch_id: str, state: Dict[str, SwitchState],
                    topology: Topology) -> SwitchState:
    """Best (root, cost, root port) for one switch, given the current states."""
    switch = topology.switch(switch_id)
    best = SwitchState(root_id=switch_id, cost=0, root_port=None)
    best_key = (switch.sort_key(), 0, switch.sort_key())
    for link in topology.adjacency()[switch_id]:
        neighbour = link.other(switch_id)
        n_state = state[neighbour]
        cost = n_state.cost + link.cost
        root_key = topology.switch(n_state.root_id).sort_key()
        sender_key = topology.switch(neighbour).sort_key()
        key = (root_key, cost, sender_key)
        if key < best_key:
            best_key = key
            best = SwitchState(root_id=n_state.root_id, cost=cost, root_port=neighbour)
    return best


def _switches_snapshot(state: Dict[str, SwitchState]) -> dict:
    return {
        sid: {"root": st.root_id, "cost": st.cost, "root_port": st.root_port}
        for sid, st in state.items()
    }


def simulate(topology: Topology, max_rounds: Optional[int] = None) -> SimulationResult:
    """Run the BPDU exchange until stable; return all animation steps."""
    validate(topology)
    if max_rounds is None:
        max_rounds = len(topology.switches)

    switch_ids = [s.id for s in topology.switches]
    state: Dict[str, SwitchState] = {
        sid: SwitchState(root_id=sid, cost=0, root_port=None) for sid in switch_ids
    }

    steps: List[dict] = [{
        "kind": "initial",
        "round": 0,
        "description": (
            "初始状态：每台交换机都认为自己是根桥（成本 0）。"
            "BPDU 的关键字段是（根桥 ID、根路径成本、发送者桥 ID）。"
            "黄色描边的交换机当前以自己为根。点击「下一步」开始第一轮 BPDU 交换。"
        ),
        "switches": _switches_snapshot(state),
        "events": [],
        "changes": [],
    }]

    converged_round = None
    for round_no in range(1, max_rounds + 1):
        # Every switch sends its current (root, cost, bridge ID) on every port.
        events = []
        for link in topology.links:
            for sender, receiver in ((link.a, link.b), (link.b, link.a)):
                s_state = state[sender]
                events.append({
                    "from": sender,
                    "to": receiver,
                    "root": s_state.root_id,
                    "cost": s_state.cost,
                })

        # Synchronous update: all switches decide from the previous state.
        new_state: Dict[str, SwitchState] = {}
        changes = []
        change_details = []
        for sid in switch_ids:
            new_state[sid] = _best_candidate(sid, state, topology)
            old, new = state[sid], new_state[sid]
            if (old.root_id, old.cost, old.root_port) != \
                    (new.root_id, new.cost, new.root_port):
                changes.append(sid)
                change_details.append(
                    "{}：根 {}→{}，成本 {}→{}，根端口 {}".format(
                        sid, old.root_id, new.root_id, old.cost, new.cost,
                        "→" + new.root_port if new.root_port else "无",
                    )
                )

        state = new_state
        if changes:
            description = (
                f"第 {round_no} 轮 BPDU 交换，{len(changes)} 台交换机更新："
                + "；".join(change_details)
                + "。橙色圆点是本轮传输的 BPDU，接收方会再加上本端口的链路成本后比较。"
            )
        else:
            converged_round = round_no
            description = (
                f"第 {round_no} 轮 BPDU 交换：BPDU 照常发送，"
                "但没有任何交换机更新信息 —— 生成树已收敛。"
            )

        steps.append({
            "kind": "round",
            "round": round_no,
            "description": description,
            "switches": _switches_snapshot(state),
            "events": events,
            "changes": changes,
        })
        if converged_round is not None:
            break

    if converged_round is None:
        raise RuntimeError(f"did not converge within {max_rounds} rounds")

    roles = _compute_roles(topology, state)
    root = topology.switch(roles.root_id)
    tree_count = sum(1 for r in roles.link_roles.values() if r == "tree")
    steps.append({
        "kind": "final",
        "round": converged_round,
        "description": (
            f"收敛完成。根桥是 {roles.root_id}（桥 ID {root.bridge_id}，全网最小）。"
            f"绿色链路构成无环生成树（{tree_count} 条转发链路）；"
            f"红色 ✕ 标记被阻塞的端口（{len(roles.blocked_ends)} 条冗余链路被阻断以消除环路）。"
            "交换机下方的文字标出了各端口角色。"
        ),
        "switches": _switches_snapshot(state),
        "events": [],
        "changes": [],
        "roles": {
            "root": roles.root_id,
            "links": roles.link_roles,
            "blocked_ends": roles.blocked_ends,
            "ports": roles.port_roles,
        },
    })

    return SimulationResult(
        steps=steps,
        root_id=roles.root_id,
        link_roles=roles.link_roles,
        blocked_ends=roles.blocked_ends,
        port_roles=roles.port_roles,
    )


@dataclass
class _Roles:
    root_id: str
    link_roles: Dict[str, str]
    blocked_ends: Dict[str, str]
    port_roles: Dict[str, dict]


def _compute_roles(topology: Topology, state: Dict[str, SwitchState]) -> _Roles:
    """Assign designated/blocked roles from the converged state."""
    switches = {s.id: s for s in topology.switches}
    root_id = min(switches.values(), key=lambda s: s.sort_key()).id
    for sid in switches:
        if state[sid].root_id != root_id:
            raise RuntimeError(f"{sid} still believes root is {state[sid].root_id}")

    link_roles: Dict[str, str] = {}
    blocked_ends: Dict[str, str] = {}
    port_roles: Dict[str, dict] = {
        sid: {"root_port": state[sid].root_port, "designated": [], "blocked": []}
        for sid in switches
    }

    for link in topology.links:
        cost_a, cost_b = state[link.a].cost, state[link.b].cost
        # Designated bridge on the segment: closer to the root, ties by bridge ID.
        designated, other = link.a, link.b
        if (cost_b, switches[link.b].sort_key()) < (cost_a, switches[link.a].sort_key()):
            designated, other = link.b, link.a
        port_roles[designated]["designated"].append(other)
        if state[other].root_port == designated:
            link_roles[link.id()] = "tree"  # root port <-> designated port
        else:
            link_roles[link.id()] = "blocked"
            blocked_ends[link.id()] = other
            port_roles[other]["blocked"].append(designated)

    for roles in port_roles.values():
        roles["designated"].sort()
        roles["blocked"].sort()

    return _Roles(root_id, link_roles, blocked_ends, port_roles)
