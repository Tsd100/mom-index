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
│       ├── sync_data.py         # 数据同步脚本（data/ → frontend/data/）
│       ├── collectors/
│       │   ├── anti_detection.py    # 反检测：UA轮换+隐身+延迟
│       │   ├── guba_collector.py    # 东方财富股吧采集（✅ 生产可用）
│       │   ├── price_collector.py   # 腾讯财经 ETF 实时价格
│       │   ├── xhs_collector.py     # 小红书（⚠️ 需充值/登录）
│       │   └── xhs_playwright.py    # 小红书 Playwright 方案
│       ├── analyzer/
│       │   ├── llm_analyzer.py      # 多维度分类引擎（40+信号词库）
│       │   └── index_calculator.py  # 指数计算（含买入/卖出子指数）
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
```

回测输出各情绪区间之后的 N 日平均收益，并检验"指数越高、未来收益越低"的反向假设（期望负相关）。报告生成在 `data/backtest_report.md`。

## 数据说明

- **真实记录**（`source=real`）：管线真实采集生成，回测只认这类记录。
- **模拟记录**（`source=mock`）：真实记录不足 5 天时，自动生成 30 天模拟曲线用于前端预览（固定种子、跨运行稳定，前端以虚线+横幅标注）。攒满 5 天后自动移除模拟数据。
- **原始帖子存档**：每次采集的帖子原样存入 `data/raw_posts.db`（SQLite），将来调整信号词库可重算历史。

## 数据源

| 数据源 | 状态 | 说明 |
|--------|------|------|
| 东方财富股吧 | ✅ 稳定 | 12 个 ETF 吧，无需 cookie，无风控 |
| 腾讯财经 (qt.gtimg.cn) | ✅ 稳定 | ETF 实时价格，免费无 key |
| 小红书 (rnote.dev / Playwright) | ⚠️ 需充值/登录 | 暂无稳定免费方案 |

## 已知局限

- **股吧小白占比低**：5-20% 是正常的，真正的小白信号需要小红书数据
- **关键词规则限制**：非 LLM 语义理解，会漏掉隐含信号、误判部分 spam
- **商业航天用军工 ETF 代理**：对应关系需后续用真实商业航天标的验证
- **单日快照**：一次采集只是一个数据点，需要持续运行积累

## 部署到飞牛 NAS

```bash
python nas-deploy-tool.py   # 生成 docker/ + docker-compose.yml 离线部署包
```

容器支持两种模式：

- 设置 `CRON_SCHEDULE`（如 `0 9,15 * * *`）→ supercronic 定时采集
- 不设置 → 启动 HTTP 服务（默认端口 8503），访问 `/dashboard.html`

数据通过 `MOM_INDEX_DATA_DIR` 映射到宿主机卷，`raw_posts.db` 与 `history.json` 会持续积累。

## 技术栈

- Python 3.11+（requests 必装，playwright 可选）
- Chart.js 4.x + 原生 HTML/CSS
- SQLite（原始帖子存档，标准库）

## License

MIT — 仅供学习研究，不构成投资建议。
