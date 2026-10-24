# 👩‍👧 宝妈指数 (Mom Index)

追踪中文社交平台的散户投资讨论热度，以“擦鞋童理论”的反向指标假设为研究起点。指数衡量规则识别到的讨论特征，预测能力尚未验证。

```
研究问题：散户讨论特征是否能在价格趋势之外，提供额外的信息？
```

## 核心指标

12 个板块独立计算，每个板块有三个指标：

| 指标 | 含义 |
|------|------|
| **宝妈指数** | 综合情绪热度 (0-100) |
| 🟢 **宝妈买入** | 追涨情绪强度 (0-100) |
| 🔴 **宝妈卖出** | 割肉恐慌强度 (0-100) |

### 指数解读

| 区间 | 经验分档 | 含义（未校准） |
|------|------|------|
| 0-20 | 🔵 极度冷清 | 讨论特征较少，不代表市场底部 |
| 20-40 | 🟢 正常区间 | 规则评分处于较低区间 |
| 40-60 | 🟡 开始升温 | 规则评分上升 |
| 60-75 | 🟠 高度警惕 | 规则评分较高，需核对样本 |
| 75-100 | 🔴 极度狂热 | 极端评分，不等同于卖出指令 |

### 指数公式

```
宝妈指数 = 小白占比×0.40 + 小白强度×0.25 + 情绪极端度×0.20 + 小白纯度×0.15
宝妈买入 = 买入小白占比×50 + 小白热度×30 + 买入强度×20
宝妈卖出 = 卖出小白占比×50 + 小白热度×30 + 卖出强度×20
```

## 覆盖板块（12 个）

| 板块 | key | 股吧代码 | ETF |
|------|-----|----------|-----|
| 纳斯达克 | nasdaq | of159941 | 159941 |
| 黄金 | gold | of518880 | 518880 |
| 通信 | telecom | of515880 | 515880 |
| 半导体 | semiconductor | of512480 | 512480 |
| 创新药 | innovative_drug | of159992 | 159992 |
| 有色金属 | nonferrous_metals | of512400 | 512400 |
| 新能源 | new_energy | of516160 | 516160 |
| 电力 | power | of159611 | 159611 |
| 芯片 | chip | of159995 | 159995 |
| 机器人 | robot | of562500 | 562500 |
| 石油石化 | petrochemical | of159731 | 159731 |
| 商业航天 | aerospace | of159206（卫星代理） | 159206 |

## 项目结构

```
mom-index/
├── pyproject.toml               # 包定义（src 布局）
├── nas-deploy-tool.py           # 飞牛NAS离线部署包生成工具
├── docker/
│   └── entrypoint.sh            # 容器入口（定时任务 / HTTP 服务）
├── src/
│   └── mom_index/
│       ├── pipeline.py          # 主流程：采集→分析→指数→存储
│       ├── storage.py           # 原始帖子存档（SQLite）
│       ├── instruments.py       # 带官方来源的板块标的配置
│       ├── replay.py            # 只读存档，隔离历史重算
│       ├── market_data.py       # 带证明的日线行情
│       ├── research.py          # 严格交易日回测与基准
│       ├── backtest.py          # 回测入口（生产/演示分离）
│       ├── backfill_history.py  # 真实历史价格回填（腾讯K线）
│       ├── sync_data.py         # 数据同步脚本（data/ → frontend/data/）
│       ├── collectors/
│       │   ├── anti_detection.py    # 反检测：UA轮换+隐身+延迟
│       │   ├── guba_collector.py    # 东方财富股吧采集（✅ 生产可用）
│       │   ├── price_collector.py   # 腾讯财经 ETF 实时价格
│       │   ├── xhs_collector.py     # 小红书（⚠️ 需充值/登录）
│       │   ├── xhs_playwright.py    # 小红书 Playwright 方案
│       │   └── xueqiu_collector.py  # 雪球（⚠️ 需登录 Cookie，默认关闭）
│       ├── analyzer/
│       │   ├── llm_analyzer.py      # 多维度分类引擎（40+信号词库）
│       │   ├── index_calculator.py  # 指数计算（含买入/卖出子指数）
│       │   └── signal.py            # 每日操作信号清单
│       └── frontend/
│           ├── dashboard.html       # 看板页面（Chart.js 暗色主题）
│           └── data/                # 前端数据（pipeline 自动同步）
└── src/data/                    # 运行数据（旧快照保留，新研究目录不提交）
    ├── dashboard_data.json      # 前端数据源
    ├── history.json             # 历史记录（source=real/mock）
    ├── production/             # 已核验历史与正式回测报告
    ├── reconstructed/          # 只读历史重算版本
    ├── market_history.json     # 带标的与复权证明的行情
    └── raw_posts.db             # 原始帖子存档（SQLite）
```

## 快速开始

```powershell
cd D:\Github\Agent\mom-index

# 运行数据采集 + 分析 + 指数计算（自动同步到 frontend/data/）
$env:PYTHONPATH = "$PWD\src"
python -m mom_index.pipeline

# 启动前端看板（默认 8503 端口）
cd src\mom_index\frontend
python -m http.server 8503

# 浏览器打开
# http://localhost:8503/dashboard.html
```

## 回测

```powershell
# 仅用真实数据（模拟历史默认排除）
python -m mom_index.backtest

# 指定观察周期（5/10/20 个交易日）
python -m mom_index.backtest --horizons 5 10 20

# 查看正式校准边界（目前不做样本内阈值寻优）
python -m mom_index.backtest --calibrate
```

正式回测按下一交易日开盘入场，与ETF持有、价格动量和沪深300同窗比较。正式报告生成在 `src/data/production/backtest_report.md`；`--include-mock` 演示报告单独写入 `src/data/demo/backtest_report.md`。

## 行情、历史重算与严格回测（2026-10-16）

```powershell
$env:PYTHONPATH="src"
python -m mom_index.market_data --days 180       # 获取明确前复权的已完成日线与基准
python -m mom_index.replay                      # 只读SQLite，输出独立重算版本
python -m mom_index.backtest --horizons 5 10 20  # 正式生产记录研究
# 重算命令会打印具体版本目录，请将该目录传入：
python -m mom_index.backtest --reconstructed "src/data/reconstructed/<版本目录>"
```

旧 `python -m mom_index.backfill_history --days 180` 命令兼容转到新行情格式；原 `price_backfill.json` 保留，因缺少标的/复权证明，不再拼接到新价格曲线。

- **标的一致性**：12 板块配置统一在 `src/mom_index/instruments.py`，保留官方来源、核查日期及代理范围。股吧与价格使用同一ETF。纳指价格从513100统一到原采集159941；商业航天从军工512710切换为卫星159206（只覆盖部分商业航天）；石油石化从能源159930切换为石化159731。
- **不改写旧标的**：旧记录仍读取其原运行配置。看板同时显示最近采集标的与当前映射；标的变更后的价格不拼接旧ETF，口径变化处不连接情绪线。切换映射不等于已经采到新数据。
- **重算隔离**：`reconstructed/<版本>/history.json`、`manifest.json` 记录原数据库SHA-256、实际读取行摘要、运行文件摘要、规则指纹、原始行ID、模拟/重复排除数及逐帖分析。只调用本地规则，不联网、不调用LLM、不修改数据库或生产历史。旧无run_id数据按采集日合并，单次采样窗口不可复原，保持未核验；不默认进入正式回测。旧 `snapshot-v2` 只保存了完整源码指纹，无法判断源码变化是否影响评分，因此重算时继续按旧指纹隔离，不自动合并；新 `snapshot-v3` 使用独立语义版本与代码审计指纹。
- **价格证明**：`market_history.json` 以ETF代码而非板块名称为键，附来源、抓取时间、前复权方式、日线摘要、整批摘要及失败列表；完整副本存 `market_snapshots/`。正式回测强制核验摘要。接口仅返回普通 `day` 而没有 `qfqday` 时，保守排除该标的，不猜测其复权口径。当前未收盘日也排除。
- **交易日与可用时间**：以沪深300ETF日线观察到的交易日为日历，信号完成后下一交易日开盘入场，第N个交易日收盘退出。缺任一窗口日线则跳过，不压缩交易日。日历仍依赖供应商，不能证明其本身无缺日。
- **基准比较**：按板块/口径/ETF/周期分别输出同窗ETF持有、情绪规则（<20持有，其余现金）、过去5日价格动量（上涨持有，否则现金）和沪深300。盘中信号不读取当日尚未发生的收盘价。收益是研究毛收益，不含费用、滑点或成交约束；窗口重叠不视为独立样本。动量不足时显示其实际可用数，同窗差值仅使用共有样本。
- **报告与校准**：正式输出在 `production/backtest_report.md` 与 `backtest_samples.json`；重算研究仅写到该版本的 `research/` 子目录。缺数据、缺时间、标的不一致或未来窗口不足时统计原因。正式路径不再使用样本内阈值扫描宣称“反指成立”；`--calibrate` 仅提示需独立样本外校准。`--include-mock` 只保留隔离的旧逻辑演示，结果不得作为真实证据。

本轮实际验证：12个ETF行情身份均返回预期简称；卫星和石化股吧返回身份核验页，未将其当成冷清样本，也未尝试绕过。首次严格行情批次中10个标的（含基准和历史标的）取得180个已完成日线，6个未返回明确前复权字段并被排除。存档重算5组，其中2组有运行证明、3组旧数据未核验；目前正式与重算回测均无完整前瞻窗口，不能判断预测能力。

## 数据真实性与样本质量（2026-10-15）

生产管线不再自动补模拟历史，也不会把演示帖子用于指数计算。**旧记录的 `source=real` 不足以证明纯真实**：历史上曾混入模拟小红书帖子，因此旧文件原样保留，新看板与正式回测默认排除未核验记录，不猜测其真实性。

默认数据根目录是 `src/data/`，可用 `MOM_INDEX_DATA_DIR` 覆盖：

| 路径 | 用途 |
|---|---|
| `history.json` | 原有历史，原样保留，仅统计隔离数量 |
| `production/history.json` | 新口径生产快照，含来源证明，每天保留最新快照 |
| `runs/<run_id>.json` | 每次运行的来源状态、质量、指数和逐帖分析；同日重跑亦可追溯 |
| `raw_posts.db` | 真实原始存档增加 run_id，演示帖子写独立 demo_posts 表；历史存档不删除 |
| `demo/history.json` | 显式生成的演示历史，不发布到生产看板 |

```powershell
$env:PYTHONPATH="src"
python -m mom_index.pipeline           # 生产采集与发布
python -m mom_index.pipeline --demo    # 只生成隔离演示历史，不调用采集
python -m mom_index.sync_data          # 重新发布过滤后的生产看板，不触发采集
python -m unittest discover -s tests -v
```

- **来源证明**：上海时区采集时间、运行编号、各来源完成/失败/部分成功状态、采集页数、ETF 映射、规则与采集源码 SHA-256、LLM 配置指纹、帖子身份摘要。日志不保存 API Key 或 Cookie。
- **口径可比性**：`definition.id` 由人工维护的评分/采样语义版本、采集配置和来源开关生成；改动评分行为时递增 `SCORING_RULE_VERSION`，改动采样行为时递增 `SAMPLING_RULE_VERSION`。`definition.audit_id` 和 `rule_hashes` 保存完整源码指纹，注释或展示代码变化会改变审计指纹，但不会单独切断统计可比性。采集页数、配置或实际来源集合变化时，不计算跨口径 Δ；它表示与上次可比日快照之差，不保证是前一交易日。
- **价格提示门**：只有采集标的与当前ETF一致、报价不晚于采集日、最近6个行情点距采集日不超过3个自然日且窗口不超过10个自然日时，价格趋势才进入信号；缺标的或行情滞后时省略价格结论。
- **质量门**：少于 30 条有效样本、有效样本时间未知比例超过 20%、24 小时内更新的有效样本少于一半、启用来源采集失败/不完整，均暂停冷热判断，指数显示 `—`。采集完成超过 24 小时后，后端信号和前端也暂停判断。
- **时间语义**：股吧列表是“最后更新”，不是发布时间。“首次采集”表示本地此前没见过，不等于当天新帖。没有年份的列表时间按最近过去日期解释；不能可靠解析的时间标记未知，不静默补造。
- **采集方式**：默认 3 页去重后的列表快照，不是严格“当日新帖样本”。卡片显示样本、有效数、近期更新、时间未知、首次采集、已见、重复与模拟排除数。
- **模拟隔离**：即使设置 `XHS_ALLOW_MOCK=1`，生产分析仍会排除模拟帖子；演示数据仅用于开发验证。生产看板拒绝旧版静态 JSON。
- **运行与原帖说明**：看板可展开查看运行编号、耗时、来源及板块级完成/失败状态；典型帖子显示关键词命中解释，并在来源网址属于已知 HTTPS 平台时提供“查看原帖”。
- **回测边界**：正式回测只用带新来源证明且样本质量合格的指数；已实现下一交易日入场、跨口径分组与价格时间校验；日历完整性、成交成本和阈值样本外有效性仍需进一步验证，当前结果不构成预测能力证明。
- **页面刷新**：每 5 分钟重新读取生产 JSON，不会重新采集。请求失败时会清除旧指数、信号、曲线和帖子，显示数据源不可用状态；Chart.js 加载失败时，质量卡片仍可查看。
- **LLM**：无 `MOM_INDEX_LLM_API_KEY` 时只用规则引擎；设置后可按采样率复核。此次真实验证关闭 LLM 与可选付费数据源。

## 数据源

| 数据源 | 状态 | 说明 |
|--------|------|------|
| 东方财富股吧 | 按次校验 | 12 个 ETF 吧，记录 HTTP/解析失败，仍可能受反爬影响 |
| 腾讯财经 (qt.gtimg.cn) | ✅ 稳定 | ETF 实时价格，免费无 key |
| 腾讯K线 (ifzq.gtimg.cn) | ✅ 稳定 | 历史日K，用于价格回填 |
| 小红书 (rnote.dev / Playwright) | ⚠️ 需充值/登录 | 无 key 时自动跳过（不再模拟） |
| 雪球 (xueqiu) | ⚠️ 需登录 Cookie | 搜索接口被 WAF 拦截，预留接入点 |

## 已知局限

- **股吧小白占比低**：5-20% 是正常的，真正的小白信号需要小红书数据
- **关键词规则限制**：非 LLM 语义理解，会漏掉隐含信号、误判部分 spam
- **商业航天覆盖有限**：新映射使用卫星ETF，仅代表部分产业；旧军工ETF历史不改写
- **单日快照**：一次采集只是一个数据点，需要持续运行积累
- **持续采集**：Windows 本机可在任务计划程序中定期运行 `python -m mom_index.pipeline`（工作目录为仓库根目录，并设置 `PYTHONPATH=src`）。项目只提供采集入口，不会自动注册或启用系统计划任务；看板刷新也不会触发采集。
- **雪球/微博/抖音**：均需登录态与反爬绕过，暂未接入真实数据

## 部署到飞牛 NAS

```bash
python nas-deploy-tool.py   # 生成 docker/ + docker-compose.yml 离线部署包
```

容器支持两种模式：

- 设置 `CRON_SCHEDULE`（如 `0 9,15 * * *`）→ supercronic 定时采集
- 不设置 → 启动 HTTP 服务（默认端口 8503），访问 `/dashboard.html`

数据通过 `MOM_INDEX_DATA_DIR` 映射到宿主机卷，`raw_posts.db`、`production/history.json` 与 `runs/` 会持续积累。本轮未生成或验证 NAS 部署包。

## 技术栈

- Python 3.11+（requests 必装，playwright 可选）
- Chart.js 4.x + 原生 HTML/CSS
- SQLite（原始帖子存档，标准库）

## License

MIT — 仅供学习研究，不构成投资建议。
