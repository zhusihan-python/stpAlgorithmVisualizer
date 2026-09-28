"""Per-protocol core-concept explanations and per-scenario teaching notes.

Rendered by the player as the「📖 原理」modal, so a first-time viewer can
grasp the algorithm before stepping through the animation. Text is static
Chinese content; the step descriptions stay focused on what is happening.
"""

STP = {
    "title": "经典生成树协议 STP（802.1D）核心思路",
    "problem": (
        "二层网络为了可靠会部署冗余链路，但只要有环，广播帧就会沿着环路"
        "无限复制（广播风暴），MAC 地址表也会被反复扰动。冗余必须保留"
        "（坏了一条还有别的路），平时却要把环在逻辑上剪断。"
    ),
    "idea": (
        "交换机彼此交换 BPDU，自动完成三件事：选出全网的根桥；每台交换机"
        "计算自己到根桥成本最低的路径；其余冗余路径上的端口被阻塞。结果"
        "是一棵无环的生成树——链路故障时重新计算，冗余自动恢复。"
    ),
    "rules": [
        "桥 ID = 优先级 + MAC 地址，全网最小者当选根桥（先比优先级，再比 MAC）",
        "每台非根交换机选出唯一的根端口：到根桥总成本最小的那个端口；"
        "总成本 = 沿途链路成本之和；平局时比较发送者的桥 ID",
        "每条链路选出指定桥：离根桥更近（总成本更小）的一侧，平局比桥 ID；"
        "指定桥在该链路上的端口叫指定端口",
        "既不是根端口也不是指定端口的端口 = 备用端口，被阻塞、不转发数据",
    ],
    "glossary": [
        ["BPDU", "交换机之间周期性交换的协议报文，携带（根桥 ID、根路径成本、发送者桥 ID）"],
        ["根桥", "整棵生成树的根，全网桥 ID 最小的交换机；它的所有端口都是指定端口"],
        ["根端口", "每台非根交换机上通往根桥最优的那个端口（转发）"],
        ["指定端口", "每条链路上负责转发流量的那一侧端口（转发）"],
        ["备用端口", "被阻塞的冗余端口，不转发数据，故障时可以顶上"],
        ["链路成本", "与链路带宽反向相关的开销（如 100M=19、1G=4），路径成本是沿途之和"],
    ],
}

RSTP = {
    "title": "快速生成树协议 RSTP（802.1w）核心思路",
    "problem": (
        "经典 STP 的端口要定时器走完监听/学习两个状态（每端口 30 秒，"
        "故障后还要先等 max-age 20 秒）才能转发，一次收敛常要 30–50 秒，"
        "对现代网络太慢。"
    ),
    "idea": (
        "选举逻辑与 STP 完全相同（同样的 BPDU、同样的比较规则），差别只在"
        "端口如何进入转发：用提案/同意握手替代定时器——指定端口发出提案，"
        "下游交换机确认后立刻回送同意，双方立即转发。收敛速度取决于消息"
        "沿树逐跳往返的次数，而不是等待时间。"
    ),
    "rules": [
        "提案/同意握手：指定端口提案 → 下游把它选为根端口并同步（其余端口"
        "暂时 Discarding）→ 回送同意 → 该链路立即转发，并继续向下游提案，"
        "如此级联到全网",
        "备用端口（Alternate）：阻塞端口明确登记为备用；根端口故障时立即"
        "提升备用端口，不需要重新选举根桥",
        "边缘端口（Edge）：连接主机/终端的端口直接转发、永不参与生成树计算",
        "端口状态简化为 Discarding / Learning / Forwarding，不再有独立的监听定时器",
    ],
    "glossary": [
        ["提案 Proposal", "指定端口请求进入转发的握手报文（动画中的黄色圆点）"],
        ["同意 Agreement", "下游确认后回送的报文（青色圆点），收到即双方转发"],
        ["同步 Sync", "交换机在同意之前把自己的非边缘端口置于 Discarding，保证不临时成环"],
        ["备用端口 Alternate", "STP 阻塞端口在 RSTP 中的正式角色，可立即提升为根端口"],
        ["边缘端口 Edge", "连终端的端口，直接转发且不受拓扑变化影响"],
    ],
}

PVST = {
    "title": "每 VLAN 生成树 PVST+（Cisco）核心思路",
    "problem": (
        "经典 STP 全网只有一棵树：被阻塞的冗余链路对所有流量都闲置，"
        "带宽白白浪费。"
    ),
    "idea": (
        "给每个 VLAN 单独跑一棵生成树（Cisco 私有）。对不同 VLAN 配置不同"
        "的交换机优先级，让它们选出不同的根桥、算出不同的树——于是同一条"
        "冗余链路对 VLAN 10 是阻塞的，对 VLAN 20 却在转发，负载被分担到"
        "不同链路上。切换页面顶部的 VLAN 标签或看「叠加对比」即可观察。"
    ),
    "rules": [
        "每个 VLAN 一棵树、一套独立的 BPDU，树与树互不影响",
        "不同 VLAN 通过不同的交换机优先级得到不同的根桥 → 不同的树",
        "同一条链路在不同 VLAN 中角色可以不同（本例的负载分担要点）",
        "代价：N 个 VLAN 要维护 N 棵树，BPDU 与 CPU 开销随 VLAN 数量线性增长",
    ],
    "glossary": [
        ["VLAN", "把一张物理交换网逻辑划分成多个互不相通的广播域"],
        ["干道 Trunk", "同时承载多个 VLAN 流量的链路，生成树按 VLAN 独立计算"],
        ["负载分担", "不同 VLAN 的树不同，流量走不同链路，冗余带宽被利用"],
    ],
}

MSTP = {
    "title": "多生成树协议 MSTP（802.1s）核心思路",
    "problem": (
        "PVST+ 在 VLAN 数量很多时开销爆炸：几百个 VLAN 就要几百棵树、"
        "几百倍的 BPDU。"
    ),
    "idea": (
        "把多个 VLAN 映射到少量生成树实例（MST 实例）：每个实例一棵树，"
        "实例内的所有 VLAN 共享它。树的数量从 N(VLAN) 降到 N(实例)，"
        "同时保留按实例做负载分担的能力。本演示中 4 个 VLAN 只需 2 棵树。"
        "（区域 Region/IST/CST 等跨区域细节不在本教学模型范围内。）"
    ),
    "rules": [
        "VLAN → 实例的映射在区域内全交换机一致配置",
        "每个实例独立选根桥、独立计算树（实例内 VLAN 共享该树）",
        "不同实例可配不同优先级 → 不同树 → 按实例负载分担",
        "实例数远小于 VLAN 数，开销可控",
    ],
    "glossary": [
        ["MST 实例", "一棵生成树的计算单元，多个 VLAN 映射到同一实例"],
        ["MST 区域", "VLAN 映射配置一致的一组交换机（本演示单区域）"],
        ["负载分担", "不同实例的树不同，不同 VLAN 组的流量走不同链路"],
    ],
}

CONCEPTS = {"stp": STP, "rstp": RSTP, "pvst": PVST, "mstp": MSTP}

SCENARIO_NOTES = {
    "triangle": (
        "场景看点（triangle）：三条链路成本相同——观察两件事：根桥由"
        "优先级决定（S3 最低）；到根成本相同出现平局时，靠“发送者桥 ID”"
        "裁决出唯一的根端口与指定端口，最终恰好阻塞 1 条冗余链路。"
    ),
    "square-diagonal": (
        "场景看点（square-diagonal）：两跳 4+4=8 的路径胜过直连 19 成本的"
        "链路——生成树选的是总成本最低的路径，不是最少跳数。"
    ),
    "classic-6": (
        "场景看点（classic-6）：环形网加两条 19 成本冗余弦——观察多条"
        "等价路径如何逐一平局裁决，以及 3 条冗余链路如何被阻塞。"
    ),
    "random": (
        "场景看点（random）：随机生成的连通拓扑——验证上述规则在任意"
        "拓扑上都能得出唯一的生成树。"
    ),
}


def for_protocol(protocol: str, topology_name: str) -> dict:
    """Concept card content for a protocol+scenario document."""
    concept = dict(CONCEPTS[protocol])
    concept["scenario"] = SCENARIO_NOTES.get(
        topology_name, SCENARIO_NOTES["random"])
    return concept
