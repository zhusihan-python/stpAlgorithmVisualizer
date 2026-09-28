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
Home End），以及每一步的文字讲解与当轮 BPDU 列表。右上角**「📖 原理」**
按钮弹出当前协议的核心算法讲解（要解决的问题 → 核心思路 → 关键规则 →
术语速查）与本场景的看点提示，第 0 步的讲解末尾会提示先读原理卡，降低
上手门槛。

## 拓扑选择

```bash
python3 generate.py -t triangle          # 3 台交换机：根桥选举 + 平局裁决
python3 generate.py -t square-diagonal   # 两跳 4+4 路径胜过直连 19 成本链路
python3 generate.py -t classic-6         # 6 台交换机环形网 + 两条冗余弦
python3 generate.py -t random -n 8 --seed 7    # 随机连通拓扑
python3 generate.py -p rstp -t random -n 10    # RSTP + 随机拓扑
python3 generate.py -t random -n 10 --json steps.json   # 同时导出原始步骤 JSON
```

## 网页拓扑编辑器

```bash
python3 serve.py         # 打开 http://127.0.0.1:8765/editor.html
```

在编辑器里拖动交换机摆放、依次点击两台交换机连边、右侧面板调整
优先级/链路成本（或导入导出拓扑 JSON），选协议后「生成动画」——浏览器
把拓扑 POST 给本地服务，Python 端跑完模拟返回步骤数据，页面下方直接
逐步播放（含 RSTP 全部相位与多实例标签/叠加视图）。模拟逻辑只在
Python，前端零重复实现。

自定义拓扑文件同样可以直接走 CLI（编辑器「导入/导出 JSON」就是此格式）：

```bash
python3 generate.py -f my-topo.json -p rstp -o my.html
```

文件结构：`{"switches": [{"id","priority?","mac?","x?","y?"}], "links":
[{"a","b","cost?"}]}`，其中 `x`/`y` 是 0–1 归一化画布坐标，省略则用
环形布局。

## RSTP 模式演示什么

`-p rstp` 在同一套步骤流水线上追加经典 STP 没有的内容：

- **提案/同意（Proposal/Agreement）级联**：选举轮次与 STP 相同，之后树链路
  逐跳完成提案→同意握手并立即转发（黄色包=提案，青色包=同意），
  对比 STP 每端口 30–50 秒的监听/学习定时器；
- **边缘端口**：页面里的 PC1 从第 0 步就直通转发，永不参与生成树计算，
  拓扑变化时不受影响；
- **故障切换**：自动挑一条有备用路径的树链路断开——受影响交换机本地立即
  检测，把备用端口（Alternate）提升为根端口并重新握手子树，毫秒级恢复；
  对比经典 STP 约 50 秒（max-age + 监听/学习）；
- **新增劣链路（零扰动对照）**：接入一条不提供更优路径的链路（可能就是
  刚才断开的链路修复重连）——提案被拒，新链路停在备用，现有树一条不变；
- **新增优链路（根端口迁移）**：接入一条更优链路——受惠交换机把根端口
  迁移过来、失去角色的链路降级备用、子树重新握手，切换即时完成；
- **普通交换机上线**：新交换机双上联接入，先以自己为根宣告、被邻居的
  更优 BPDU 立即纠正，握手后作为叶子加入——**全网没有一台交换机改变
  根端口**，第二条上联保持备用（上联成环被消除）；
- **根桥迁移（桥 ID 更小的新交换机上线）**：全网最优信息出现，所有
  交换机把根端口转向新根，整网重构只是一轮提案/同意级联——对比经典
  STP 根桥变化动辄数十秒的重新收敛。

各场景自动挑选演示对象并按「启动 → 断链 → 劣链路 → 优链路 → 普通上线 →
根桥迁移」串联播放，不适用的相位自动跳过。

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
| `rstp.py` | RSTP 扩展：P/A 级联、边缘端口、断链/加链/上线/根迁移全故事线（复用 `stp.simulate`） |
| `mstp.py` | PVST+/MSTP 多实例模拟：按实例覆盖优先级后逐实例复用 `stp.simulate` |
| `topologies.py` | 内置教学样例、随机拓扑生成器、多实例定义、自定义拓扑加载（`from_dict`/`from_file`） |
| `generate.py` | CLI：`-p stp\|rstp\|pvst\|mstp`、`-t 样例\|-f 拓扑文件`，组装数据并把 `player.js` 内联进单文件页面 |
| `template.html` | 单文件播放器外壳（构建时注入数据与播放器代码） |
| `player.js` / `editor.html` / `editor.js` / `serve.py` | 网页播放器本体与拓扑编辑器（本地服务 + `/generate` 端点） |
| `test_*.py` | 单元测试：协议不变量、相位正确性、端点集成、打包一致性等 |

## 模拟模型（教学简化）

- 每一轮：每台交换机把自己的（根桥 ID、根路径成本、桥 ID）发给所有邻居；
- 收到后按 **最小根桥 ID → 最小总成本 → 最小发送者桥 ID** 选取最优；
- 没有任何交换机更新即收敛；收敛后每条链路的指定桥是离根更近的一侧
  （平局取桥 ID 小者），另一侧端口是根端口（转发）或备用端口（阻塞）；
- RSTP 的差异只在"端口如何进入转发"：握手级联替代定时器（见上节）；
- PVST+/MSTP 是对同一拓扑按实例覆盖优先级后重复上述计算（见上节）。

运行测试：`python3 -m unittest -v test_stp test_rstp test_mstp`
