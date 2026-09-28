# STP Algorithm Visualizer

生成树协议的逐步动画可视化：用纯 Python 模拟 BPDU 交换与端口角色选举，生成
自带播放器的单文件网页。支持经典 STP（IEEE 802.1D）、RSTP（IEEE 802.1w）、
PVST+（每 VLAN 一棵树）与 MSTP（IEEE 802.1s，多 VLAN 映射实例）。

## 快速开始

```bash
python3 generate.py                        # 经典 STP，生成 stp.html
python3 generate.py -p rstp                # RSTP，生成 rstp.html
python3 generate.py -p pvst                # PVST+，生成 pvst.html
python3 generate.py -p mstp                # MSTP，生成 mstp.html
open stp.html                              # 双击打开也可
```

播放器支持：逐步前进/后退、自动播放/暂停、0.5×/1×/2× 速度、键盘（← → 空格
Home End），以及每一步的文字讲解与当轮 BPDU 列表。

## 拓扑选择

```bash
python3 generate.py -t triangle          # 3 台交换机：根桥选举 + 平局裁决
python3 generate.py -t square-diagonal   # 两跳 4+4 路径胜过直连 19 成本链路
python3 generate.py -t classic-6         # 6 台交换机环形网 + 两条冗余弦
python3 generate.py -t random -n 8 --seed 7    # 随机连通拓扑
python3 generate.py -p rstp -t random -n 10    # RSTP + 随机拓扑
python3 generate.py -t random -n 10 --json steps.json   # 同时导出原始步骤 JSON
```

## RSTP 模式演示什么

`-p rstp` 在同一套步骤流水线上追加经典 STP 没有的内容：

- **提案/同意（Proposal/Agreement）级联**：选举轮次与 STP 相同，之后树链路
  逐跳完成提案→同意握手并立即转发（黄色包=提案，青色包=同意），
  对比 STP 每端口 30–50 秒的监听/学习定时器；
- **边缘端口**：页面里的 PC1 从第 0 步就直通转发，永不参与生成树计算，
  拓扑变化时不受影响；
- **故障切换**：自动挑一条有备用路径的树链路断开——受影响交换机本地立即
  检测，把备用端口（Alternate）提升为根端口并重新握手子树，毫秒级恢复；
  对比经典 STP 约 50 秒（max-age + 监听/学习）。

## PVST+ / MSTP 模式演示什么

两种多实例协议跑在同一套流水线上：给不同实例设置不同的交换机优先级，
让每个实例选出不同的根桥、算出不同的树——冗余链路为不同 VLAN/实例转发，
这就是负载分担。

- **PVST+（`-p pvst`）**：每个 VLAN 一棵树。页面顶部出现 VLAN 标签页，
  切换对比两棵树（例如 VLAN 10 阻塞 S1–S2、VLAN 20 阻塞 S2–S3）；
  末尾的**「叠加对比」**标签把所有实例的收敛树画在同一张画布上：
  每实例一种颜色、多实例转发的链路为并行双色线、对所有实例都冗余的
  链路标红 ✕，讲解面板逐链路列出"哪个实例转发/阻塞"并给出负载分担
  结论；
- **MSTP（`-p mstp`，802.1s）**：多个 VLAN 映射到少数实例（MST1 承载
  VLAN 10/20、MST2 承载 VLAN 30/40），每个实例一棵树——4 个 VLAN 只要
  2 棵树，对比 PVST+ 的每 VLAN 一棵。区域（Region/IST/CST）间细节不在
  本教学模型范围内。

## 代码结构

| 文件 | 职责 |
|---|---|
| `stp.py` | 经典 STP 模拟核心（纯逻辑，无 I/O）：轮次化 BPDU 交换、根桥选举、端口角色 |
| `rstp.py` | RSTP 扩展：P/A 级联、边缘端口、故障切换（复用 `stp.simulate`） |
| `mstp.py` | PVST+/MSTP 多实例模拟：按实例覆盖优先级后逐实例复用 `stp.simulate` |
| `topologies.py` | 内置教学样例、随机拓扑生成器、多实例定义 |
| `generate.py` | CLI：`-p stp\|rstp\|pvst\|mstp`，组装数据嵌入 `template.html` |
| `template.html` | 播放器模板（原生 JS + canvas，零依赖；多实例时渲染标签页） |
| `test_*.py` | 单元测试：根选举、最短路一致性、生成树无环、级联顺序、备用提升、多实例树差异、确定性等 |

## 模拟模型（教学简化）

- 每一轮：每台交换机把自己的（根桥 ID、根路径成本、桥 ID）发给所有邻居；
- 收到后按 **最小根桥 ID → 最小总成本 → 最小发送者桥 ID** 选取最优；
- 没有任何交换机更新即收敛；收敛后每条链路的指定桥是离根更近的一侧
  （平局取桥 ID 小者），另一侧端口是根端口（转发）或备用端口（阻塞）；
- RSTP 的差异只在"端口如何进入转发"：握手级联替代定时器（见上节）；
- PVST+/MSTP 是对同一拓扑按实例覆盖优先级后重复上述计算（见上节）。

运行测试：`python3 -m unittest -v test_stp test_rstp test_mstp`
