# STP Algorithm Visualizer

生成树协议的逐步动画可视化：用纯 Python 模拟 BPDU 交换与端口角色选举，生成
自带播放器的单文件网页。支持经典 STP（IEEE 802.1D）与 RSTP（IEEE 802.1w）。

## 快速开始

```bash
python3 generate.py                        # 经典 STP，生成 stp.html
python3 generate.py -p rstp                # RSTP，生成 rstp.html
open rstp.html                             # 双击打开也可
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

## 代码结构

| 文件 | 职责 |
|---|---|
| `stp.py` | 经典 STP 模拟核心（纯逻辑，无 I/O）：轮次化 BPDU 交换、根桥选举、端口角色 |
| `rstp.py` | RSTP 扩展：P/A 级联、边缘端口、故障切换（复用 `stp.simulate`） |
| `topologies.py` | 内置教学样例与随机拓扑生成器 |
| `generate.py` | CLI：`-p stp\|rstp` 选择协议，组装数据嵌入 `template.html` |
| `template.html` | 播放器模板（原生 JS + canvas，零依赖） |
| `test_stp.py` / `test_rstp.py` | 单元测试：根选举、最短路一致性、生成树无环、级联顺序、备用提升、确定性等 |

## 模拟模型（教学简化）

- 每一轮：每台交换机把自己的（根桥 ID、根路径成本、桥 ID）发给所有邻居；
- 收到后按 **最小根桥 ID → 最小总成本 → 最小发送者桥 ID** 选取最优；
- 没有任何交换机更新即收敛；收敛后每条链路的指定桥是离根更近的一侧
  （平局取桥 ID 小者），另一侧端口是根端口（转发）或备用端口（阻塞）；
- RSTP 的差异只在"端口如何进入转发"：握手级联替代定时器（见上节）。

运行测试：`python3 -m unittest -v test_stp test_rstp`
