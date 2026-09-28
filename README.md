# STP Algorithm Visualizer

经典生成树协议（STP, IEEE 802.1D）的逐步动画可视化：用纯 Python 模拟 BPDU
交换与端口角色选举，生成一个自带播放器的单文件网页。

## 快速开始

```bash
python3 generate.py                 # 生成 stp.html（triangle 样例）
open stp.html                       # 双击打开也可
```

播放器支持：逐步前进/后退、自动播放/暂停、0.5×/1×/2× 速度、键盘（← → 空格
Home End），以及每一步的文字讲解与当轮 BPDU 列表。

## 拓扑选择

```bash
python3 generate.py -t triangle          # 3 台交换机：根桥选举 + 平局裁决
python3 generate.py -t square-diagonal   # 两跳 4+4 路径胜过直连 19 成本链路
python3 generate.py -t classic-6         # 6 台交换机环形网 + 两条冗余弦
python3 generate.py -t random -n 8 --seed 7   # 随机连通拓扑
python3 generate.py -t random -n 10 --json steps.json   # 同时导出原始步骤 JSON
```

## 代码结构

| 文件 | 职责 |
|---|---|
| `stp.py` | STP 模拟核心（纯逻辑，无 I/O）：轮次化 BPDU 交换、根桥选举、端口角色 |
| `topologies.py` | 内置教学样例与随机拓扑生成器 |
| `generate.py` | CLI：组装数据、嵌入 `template.html` 生成单文件网页 |
| `template.html` | 播放器模板（原生 JS + canvas，零依赖） |
| `test_stp.py` | 单元测试：根选举、最短路一致性、生成树无环、角色一致性、确定性等 |

## 模拟模型（教学简化）

- 每一轮：每台交换机把自己的（根桥 ID、根路径成本、桥 ID）发给所有邻居；
- 收到后按 **最小根桥 ID → 最小总成本 → 最小发送者桥 ID** 选取最优；
- 没有任何交换机更新即收敛；收敛后每条链路的指定桥是离根更近的一侧
  （平局取桥 ID 小者），另一侧端口是根端口（转发）或备用端口（阻塞）。

运行测试：`python3 -m unittest -v test_stp`
