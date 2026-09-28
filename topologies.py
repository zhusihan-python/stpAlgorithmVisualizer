"""Topology builders for the STP visualizer.

Three hand-picked teaching scenarios plus a seeded random generator.
All builders return a ``stp.Topology``.
"""

import random
from typing import List

import stp

# Classic STP port costs by link speed (for a realistic flavour).
COST_FAST = 19   # 100 Mbps
COST_GIGA = 4    # 1 Gbps
COST_TEN_G = 1   # 10 Gbps


def _switches(count: int, priorities: List[int]) -> List[stp.Switch]:
    """S1..Sn with the given priorities and MACs ordered by index."""
    return [
        stp.Switch(
            id=f"S{i + 1}",
            priority=priorities[i],
            mac="00:00:00:00:{:02x}:{:02x}".format((i + 1) // 256, (i + 1) % 256),
        )
        for i in range(count)
    ]


def triangle() -> stp.Topology:
    """3 switches, equal costs: root election + one blocked link by bridge-ID tie-break."""
    return stp.Topology(
        switches=_switches(3, [32768, 32768, 8192]),
        links=[
            stp.Link("S1", "S2", COST_GIGA),
            stp.Link("S1", "S3", COST_GIGA),
            stp.Link("S2", "S3", COST_GIGA),
        ],
    )


def square_diagonal() -> stp.Topology:
    """4 switches: shows a cheaper two-hop path beating a direct 19-cost link."""
    return stp.Topology(
        switches=_switches(4, [32768, 8192, 32768, 24576]),
        links=[
            stp.Link("S1", "S2", COST_GIGA),
            stp.Link("S2", "S3", COST_GIGA),
            stp.Link("S3", "S4", COST_GIGA),
            stp.Link("S4", "S1", COST_GIGA),
            stp.Link("S2", "S4", COST_FAST),
        ],
    )


def classic6() -> stp.Topology:
    """6 switches, a ring plus two chords: equal-cost tie-breaks and blocked chords."""
    return stp.Topology(
        switches=_switches(6, [32768, 32768, 32768, 8192, 32768, 32768]),
        links=[
            stp.Link("S1", "S2", COST_GIGA),
            stp.Link("S2", "S3", COST_GIGA),
            stp.Link("S3", "S4", COST_GIGA),
            stp.Link("S4", "S5", COST_GIGA),
            stp.Link("S5", "S6", COST_GIGA),
            stp.Link("S6", "S1", COST_GIGA),
            stp.Link("S2", "S6", COST_FAST),
            stp.Link("S3", "S5", COST_FAST),
        ],
    )


def random_topology(num_switches: int, seed: int) -> stp.Topology:
    """Seeded random connected topology: random spanning tree + extra edges.

    One randomly placed switch gets priority 8192 so the root election is
    not always won by S1.
    """
    if num_switches < 3:
        raise ValueError("random topology needs at least 3 switches")
    rng = random.Random(seed)

    ids = [f"S{i + 1}" for i in range(num_switches)]
    priorities = [32768] * num_switches
    priorities[rng.randrange(num_switches)] = 8192
    switches = _switches(num_switches, priorities)

    # Random spanning tree: shuffle the ids and chain them up.
    order = ids[:]
    rng.shuffle(order)
    links = []
    for first, second in zip(order, order[1:]):
        a, b = sorted((first, second))
        links.append(stp.Link(a, b, rng.choice([COST_TEN_G, COST_GIGA, COST_GIGA, COST_FAST])))

    # Extra edges between random non-adjacent pairs, up to 2n links total.
    # Note: pairs must be compared in their canonical (sorted) form, or the
    # two-digit ids (S10 sorts before S9) defeat the "not in existing" check.
    existing = {link.pair() for link in links}
    max_links = 2 * num_switches
    all_pairs = [
        tuple(sorted((a, b)))
        for i, a in enumerate(ids)
        for b in ids[i + 1:]
    ]
    candidates = [pair for pair in all_pairs if pair not in existing]
    rng.shuffle(candidates)
    for a, b in candidates:
        if len(links) >= max_links:
            break
        if rng.random() < 0.35:
            links.append(stp.Link(a, b, rng.choice([COST_TEN_G, COST_GIGA, COST_GIGA, COST_FAST])))

    # Deterministic order so serialization is reproducible.
    links.sort(key=lambda link: link.pair())
    return stp.Topology(switches=switches, links=links)


BUILDERS = {
    "triangle": lambda args: triangle(),
    "square-diagonal": lambda args: square_diagonal(),
    "classic-6": lambda args: classic6(),
    "random": lambda args: random_topology(args.nodes, args.seed),
}

# Where the edge-port demo host attaches for each built-in sample.
HOST_SWITCH = {
    "triangle": "S1",
    "square-diagonal": "S4",
    "classic-6": "S5",
}


def default_host_switch(name: str, topology: stp.Topology, seed: int) -> str:
    """Deterministic switch to attach the edge-port demo host to."""
    if name in HOST_SWITCH:
        return HOST_SWITCH[name]
    import random
    rng = random.Random(seed + 1000)
    return rng.choice([s.id for s in topology.switches])


# Second-instance root overrides: give a different switch a lower priority so
# the second PVST VLAN / MST instance elects a different root and builds a
# different tree (the load-balancing story).
SECOND_ROOT_OVERRIDES = {
    "triangle": {"S1": 4096},
    "square-diagonal": {"S4": 4096},
    "classic-6": {"S1": 4096},
}


def _second_root_overrides(name, topology, seed):
    if name in SECOND_ROOT_OVERRIDES:
        return dict(SECOND_ROOT_OVERRIDES[name])
    import random
    base_root = stp.simulate(topology).root_id
    rng = random.Random(seed + 2000)
    candidates = [s.id for s in topology.switches if s.id != base_root]
    return {rng.choice(candidates): 4096}


def build_instances(protocol, name, topology, seed):
    """Instance definitions for pvst/mstp modes."""
    from mstp import Instance
    overrides = _second_root_overrides(name, topology, seed)
    if protocol == "pvst":
        return [
            Instance("VLAN 10", ["10"], {}),
            Instance("VLAN 20", ["20"], overrides),
        ]
    return [
        Instance("MST1", ["10", "20"], {}),
        Instance("MST2", ["30", "40"], overrides),
    ]
