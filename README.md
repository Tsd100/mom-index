# 👩‍👧 宝妈指数 (Mom Index)

追踪中文社交平台上散户/小白/宝妈的投资讨论热度。**指数越高，散户情绪越极端，市场越危险**——基于"擦鞋童理论"的行为金融学反向指标。

```
当菜市场大妈和宝妈都在讨论股票，就是该离场的时候。
                 — Joseph Kennedy, 1929
```

## 核心指标

12 个板块独立计算，每个板块有三个指标：

| 指标 | 含义 |
|------|------|
| **宝妈指数** | 综合情绪热度 (0-100) |
| 🟢 **宝妈买入** | 追涨情绪强度 (0-100) |
| 🔴 **宝妈卖出** | 割肉恐慌强度 (0-100) |

### 指数解读

| 区间 | 信号 | 建议 |
|------|------|------|
| 0-20 | 🔵 极度冷清 | 小白沉默，可能是底部 |
| 20-40 | 🟢 正常区间 | 维持现有策略 |
| 40-60 | 🟡 开始升温 | 关注，准备减仓 |
| 60-75 | 🟠 高度警惕 | 大幅减仓 |
| 75-100 | 🔴 极度狂热 | 擦鞋童时刻，清仓 |

### 指数公式

```
宝妈指数 = 小白占比×0.40 + 小白强度×0.25 + 情绪极端度×0.20 + 小白纯度×0.15
宝妈买入 = 买入小白占比×50 + 小白热度×30 + 买入强度×20
宝妈卖出 = 卖出小白占比×50 + 小白热度×30 + 卖出强度×20
```

## 覆盖板块（12 个）

| 板块 | key | 股吧代码 | ETF |
|------|-----|----------|-----|
| 纳斯达克 | nasdaq | of159941 | 513100 |
| 黄金 | gold | of518880 | 518880 |
| 通信 | telecom | of515880 | 515880 |
| 半导体 | semiconductor | of512480 | 512480 |
| 创新药 | innovative_drug | of159992 | 159992 |
| 有色金属 | nonferrous_metals | of512400 | 512400 |
| 新能源 | new_energy | of516160 | 516160 |
| 电力 | power | of159611 | 159611 |
| 芯片 | chip | of159995 | 159995 |
| 机器人 | robot | of562500 | 562500 |
| 石油石化 | petrochemical | of159930 | 159930 |
| 商业航天 | aerospace | of512710（军工代理） | 512710 |

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
│       ├── backtest.py          # 回测：验证反向指标假设
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
└── data/                        # 运行数据（.gitignore 排除）
    ├── dashboard_data.json      # 前端数据源
    ├── history.json             # 历史记录（source=real/mock）
    ├── backtest_report.md       # 回测报告（自动生成）
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

# 阈值校准（样本充足时给出建议分界点）
python -m mom_index.backtest --calibrate
```

回测输出各情绪区间之后的 N 日平均收益，并检验"指数越高、未来收益越低"的反向假设（期望负相关）。样本充足时 `--calibrate` 会扫描最优分界点。正式报告生成在 `src/data/production/backtest_report.md`；`--include-mock` 演示报告单独写入 `src/data/demo/backtest_report.md`。

## 历史价格回填

```powershell
python -m mom_index.backfill_history            # 默认 30 天
python -m mom_index.backfill_history --days 60
```

用腾讯 K 线接口拉取各 ETF 真实日K收盘价到 `data/price_backfill.json`，前端价格曲线优先显示真实价格（情绪曲线仍以真实记录为准）。

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
- **口径可比性**：规则、采集页数、配置或实际来源集合变化时，不计算跨口径 Δ；它表示与上次可比日快照之差，不保证是前一交易日。
- **质量门**：少于 30 条有效样本、有效样本时间未知比例超过 20%、24 小时内更新的有效样本少于一半、启用来源采集失败/不完整，均暂停冷热判断，指数显示 `—`。采集完成超过 24 小时后，后端信号和前端也暂停判断。
- **时间语义**：股吧列表是“最后更新”，不是发布时间。“首次采集”表示本地此前没见过，不等于当天新帖。没有年份的列表时间按最近过去日期解释；不能可靠解析的时间标记未知，不静默补造。
- **采集方式**：默认 3 页去重后的列表快照，不是严格“当日新帖样本”。卡片显示样本、有效数、近期更新、时间未知、首次采集、已见、重复与模拟排除数。
- **模拟隔离**：即使设置 `XHS_ALLOW_MOCK=1`，生产分析仍会排除模拟帖子；演示数据仅用于开发验证。生产看板拒绝旧版静态 JSON。
- **回测边界**：正式回测只用带新来源证明且样本质量合格的指数；交易日对齐、跨口径分组、价格时间校验及阈值有效性验证仍是后续工作，当前结果不构成预测能力证明。
- **页面刷新**：每 5 分钟重新读取生产 JSON，不会重新采集。网络导致 Chart.js 加载失败时显示明确提示，卡片仍可用。
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
- **商业航天用军工 ETF 代理**：对应关系需后续用真实商业航天标的验证
- **单日快照**：一次采集只是一个数据点，需要持续运行积累
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
