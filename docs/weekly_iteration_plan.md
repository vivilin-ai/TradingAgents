# 周度真实收益迭代方案（Weekly Outcome-Driven Iteration Plan）

> 目标：让 agent 的最终裁决（Portfolio Manager 五档评级）每周根据市场真实价格结算、评估、校准，
> 使得用户如果按照每次建议执行，长期收益（相对基准的 alpha）持续改善。
>
> 诚实前提：任何系统都无法"保证收益最大化"。本方案能做到的是：
> 1. 把"用户照做的收益"变成一个**可测量的目标函数**（模拟组合净值）；
> 2. 每周用真实价格结算所有历史建议，产出量化记分卡；
> 3. 把量化校准信息回注到 agent 提示词，纠正系统性偏差；
> 4. 对确定性参数层（评级→仓位映射等）做有统计护栏的周度迭代。

---

## 一、现状盘点：已有闭环与缺口

### 已有能力（本仓库现状）

| 能力 | 位置 | 说明 |
|---|---|---|
| 决策落账（Phase A） | `tradingagents/agents/utils/memory.py` `store_decision()` | 每次 `propagate()` 结束把最终裁决以 `pending` 状态追加到 `trading_memory.md` |
| 收益结算 + 反思（Phase B） | `tradingagents/graph/trading_graph.py` `_resolve_pending_entries()` / `_fetch_returns()` | 下次跑**同一支股票**时，用 yfinance 取 5 个交易日 raw return 和相对 SPY 的 alpha，LLM 生成 2–4 句反思回填 |
| 经验回注 | `memory.py` `get_past_context()` → `portfolio_manager.py` | 最近 5 条同票完整记录 + 3 条跨票反思注入 PM 提示词 |
| 定时任务 | `tradingagents/scheduler/` + `cli/tasks.py` | launchd/crontab 定时批量分析，Telegram 通知 |
| 五档评级 | `tradingagents/agents/utils/rating.py` | Buy / Overweight / Hold / Underweight / Sell |
| 持仓感知 | watchlist + `extra_context` | PM 根据用户成本/数量定制建议 |

### 缺口（阻碍"照做即赚钱"的六个问题）

1. **结算被动且不完整**：pending 条目只在"下次跑同一支股票"时才结算。不再分析的票永远
   pending；结算周期不受控（可能隔 1 天也可能隔 1 个月才结算，而 horizon 固定 5 日）。
2. **只有定性反思，没有量化校准**：LLM 每次只看单条决策写几句话。没有任何聚合统计——
   "过去 12 次 Buy 平均 alpha 多少、命中率多少"这类能真正纠偏的信息不存在。
   单样本反思噪声极大，可能学到错误教训（一次踩雷就永久转向保守）。
3. **没有"用户照做"的组合级度量**：评级是离散标签，没有评级→目标仓位的映射，
   没有模拟组合净值。无法回答"照做到底赚没赚、跑没跑赢基准"。
4. **经验只注入 PM**：`past_context` 只进 Portfolio Manager 提示词，
   多空研究员 / Trader / 风险辩论完全学不到历史教训。
5. **单一 horizon**：固定 5 个交易日。周度建议的正确性在 1 周 / 2 周 / 4 周维度上可能完全不同
   （短期噪声 vs 中期趋势），单点结算容易误判。
6. **无交易成本与执行假设**：反思用的是决策日收盘到 N 日后收盘，用户实际是"看到建议后下一个
   开盘执行"，且有滑点/手续费。度量口径与真实体验脱节。

---

## 二、设计总原则

**LLM 出观点，确定性层管仓位与迭代，量化反馈回注提示词做校准。**

- 不要每周去改 agent 提示词的措辞（不可复现、易漂移、无法归因）；
  提示词保持稳定，变的是注入其中的**量化校准块**和**结构化经验**。
- 真正做周度参数迭代的是**确定性层**（评级→仓位映射、horizon、执行规则），
  它可以在历史台账上走样本外验证（walk-forward），有统计护栏。
- 一切评估以 **alpha（相对 SPY）** 为主指标而非绝对收益，避免把牛市 beta 当成能力。
- 所有迭代都设**最小样本量**和**滞回（hysteresis）**，防止对噪声过拟合。

---

## 二点五、优化目标的精确定义：三层指标体系

既然不能承诺"收益最大化"，就必须明确说清优化的到底是什么。目标是一个三层结构，
每层可测量、可归因，改进方向落在下两层，成果体现在最上层。

### 北极星指标（最终目标，唯一）

**模拟组合的滚动 12 周、扣除成本后的信息比率（IR = alpha 均值 / alpha 波动）。**

- 用 alpha 而非绝对收益：剔除 beta，牛市普涨不算能力，只有跑赢 SPY 的部分才是建议的信息价值；
- 做风险调整：防止系统漂向"重仓赌单票"——高收益高回撤的建议用户不敢照做；
- 平稳统计量：可跨周、跨参数候选比较。

北极星指标噪声大（一年仅约 50 个周度观测），不直接指导每周改什么，
它是验收指标而非操作指标。

### 中间层：评级的信息含量

五档评级本质是对未来相对收益的预测，质量有两个可测维度：

1. **区分度（单调性）**：分档后验 alpha 应满足
   Buy > Overweight > Hold > Underweight（反向）> Sell（反向）。
   若 Buy 与 Hold 的后验 alpha 无差别，评级不含信息，仓位映射再优也无用。
   这是记分卡最重要的一张表。
2. **校准度**：表达的信心与实际命中率一致。Buy 是最高信心档，
   命中率应显著高于 55%；若仅 50%，校准块须提示"强信号档收敛"。

### 基础层：系统性偏差的消除

每周迭代真正"改"的对象——不是让 agent 更聪明，而是砍掉它稳定犯的错。
偏差是可检测的复现模式，例如：Overweight 档 21d alpha 持续为负（追高）、
财报周前 Buy 命中率显著低于平时（事件风险不敏感）、单票连续误判（叙事绑架）。
每消除一个被证实的偏差，中间层区分度提高，最终传导至北极星指标。

### 三层的改进杠杆与归因链条

| 层 | 指标 | 改进杠杆 | 承接阶段 |
|---|---|---|---|
| 组合 alpha/IR | 滚动 12 周 IR | 评级→仓位映射、换仓阈值 | P4 |
| 评级信息含量 | 档位单调性、分档命中率 | 校准块回注、经验精选池 | P3 |
| 系统性偏差 | 偏差模式存续/复发率 | 偏差检测与警告注入、证伪经验淘汰 | P1 + P3 |

归因链条：北极星恶化时可定位是"评级没信息"（中间层→查偏差）还是
"信息没转化成仓位"（映射→P4 调参），而非面对黑箱。

### "改进"的操作性定义

滚动 12 周窗口内，同时满足：
1. 评级档位单调性成立，且档间 alpha 差扩大；
2. 已识别系统性偏差的复发率下降；
3. 在 1、2 成立的前提下，模拟组合 IR 不低于 SPY 与 watchlist 等权两条基准。

三条同时满足才判定为改进——仅第 3 条单独变好可能只是运气。

---

## 三、分阶段方案

### P0 — 结构化决策台账（基础设施，1 天）

现有 `trading_memory.md` 是给 LLM 读的 prose 日志，不适合做量化统计。新增一份并行的
结构化台账，两者同时写入：

```
~/.tradingagents/memory/decisions.jsonl     # 每行一条决策
```

每条记录（在 `store_decision()` 同时写入）：

```json
{
  "ticker": "NVDA", "trade_date": "2026-07-13",
  "rating": "Overweight",
  "decision_price": 182.34,          // 决策日收盘价（propagate 时已取到，直接落账）
  "next_open_price": null,           // 结算时补：建议发出后下一交易日开盘价（真实执行价）
  "position_context": {"cost": 125.5, "qty": 100},   // 若有
  "outcomes": {                       // 结算时补，多 horizon
    "5d":  {"raw": null, "alpha": null},
    "10d": {"raw": null, "alpha": null},
    "21d": {"raw": null, "alpha": null}
  },
  "resolved": {"5d": false, "10d": false, "21d": false}
}
```

实现点：
- `tradingagents/eval/ledger.py`：JSONL 读写，幂等（同 ticker+date 不重复）。
- `trading_graph.py::_run_graph()` 里 `store_decision` 之后同步写一条。
- markdown 日志保持不动（LLM 消费端零改动），JSONL 是量化消费端。

### P1 — 周度结算任务与记分卡（核心闭环，2–3 天）

新增独立的评估入口，不再依赖"下次分析同一支股票"：

```bash
tradingagents evaluate [--date 2026-07-13]
```

行为：
1. 扫描 `decisions.jsonl` 全部未结算条目（**跨所有 ticker**，不只是本次分析的票）。
2. 对每个已到期的 horizon（5/10/21 交易日）用 yfinance 结算：
   - 执行价口径：**建议发出后下一交易日开盘价**（对齐用户真实体验），另存决策日收盘口径作对照；
   - raw return、alpha vs SPY；
3. 每条新结算的 5d outcome 触发一次现有 `Reflector.reflect_on_final_decision()`，
   回填 markdown 日志（复用现有 Phase B 逻辑，只是把触发点从"下次同票分析"改为周度任务）。
4. 产出记分卡 `reports/evaluation/<DATE>/scorecard.md`，并 Telegram 推送摘要。

记分卡内容（全部由确定性代码计算，不经 LLM）：

```
## 评级分档表现（滚动 12 周，5d/21d 双 horizon）
| 评级 | 次数 | 方向命中率 | 平均alpha(5d) | 平均alpha(21d) |
| Buy        | 14 | 64% | +1.2% | +2.8% |
| Overweight | 22 | 55% | +0.4% | +0.9% |
| Hold       | 31 |  —  | +0.1% | -0.2% |
| Underweight|  9 | 67% | +1.1%*| +2.0%*|   * 对减持/卖出，alpha 取反向
| Sell       |  4 | 75% | +2.3%*| +3.1%*|

## 分票表现 / 最好最差决策 Top3 / 系统性偏差检测
例：Buy 档 21d alpha 显著为负 → "追高偏差"警告
```

调度接入：`ScheduledTask` 增加 `target: "evaluate"` 类型，推荐配置
`每周六 08:00 batch 分析 → 08:00 前先跑 evaluate`（或独立任务
`tradingagents tasks add weekly_eval --evaluate --day Saturday --time 07:30`）。
Bot 增加 `/scorecard` 命令返回最新记分卡摘要。

### P2 — "建议跟随"模拟组合（目标函数，2–3 天）

这是"如果用户照做能否收益最大化"的直接度量。`tradingagents/eval/portfolio_sim.py`：

- **评级→目标仓位映射**（v1 默认，后续 P4 迭代它）：

  | 评级 | 目标仓位（占该票额度上限） |
  |---|---|
  | Buy | 100% |
  | Overweight | 70% |
  | Hold | 维持不变 |
  | Underweight | 30% |
  | Sell | 0% |

  组合规则：等额度分配给 watchlist 每支票（如 N 支票各 1/N），未用资金按现金（或 SPY，作对照两条线）。
- **执行假设**：建议发出后下一交易日开盘价成交，单边成本 10bps（可配）。
- **每周输出**：模拟组合净值曲线 vs ① SPY 买入持有 ② watchlist 等权买入持有；
  滚动 4/12 周收益、最大回撤、周胜率。写入记分卡 + Telegram。
- 全部从 `decisions.jsonl` 重放计算，**无状态、可全量重算**——改映射参数即可回测，天然支撑 P4。

### P3 — 量化校准回注提示词（让 agent 真正"迭代"，1–2 天）

把 P1 的聚合统计变成注入提示词的**校准块**，弥补单样本反思的噪声问题：

1. `tradingagents/eval/calibration.py` 生成校准块（确定性文本，非 LLM 生成）：

   ```
   [决策校准数据 | 滚动12周]
   你的 Buy 评级：14次，5d alpha 均值 +1.2%，命中率 64%
   你的 Sell 评级：4次，样本不足，暂无结论
   检测到的偏差：Overweight 档 21d alpha 为 -0.8%，存在"温和看多但中期跑输"倾向，
   给出 Overweight 前请确认中期催化剂。
   ```

   护栏：某档样本 < 8 次时标注"样本不足"，不下结论；偏差警告需要
   |alpha| 均值超过阈值（如 0.5%）且连续两周同向才出现。
2. 注入点扩展：校准块和跨票经验不再只给 PM——
   `get_past_context()` 拆成 `pm_context`（完整）与 `researcher_context`（仅跨票教训+校准块），
   后者注入 Bull/Bear Researcher 与 Research Manager 提示词（`agent_states.py` 已有
   `past_context` 通道，加一个字段即可）。
3. **周度元反思**：evaluate 任务里加一次 LLM 调用，输入本周全部已结算 outcome + 上周经验列表，
   输出 ≤5 条"本周经验"（合并去重、淘汰被证伪的旧经验），存
   `~/.tradingagents/memory/lessons.md`（上限 20 条，滚动淘汰）。
   `get_past_context()` 的跨票部分改为优先取自这份精选经验，而非随机最近 3 条。

### P4 — 确定性参数层的周度迭代（有护栏的"收益最大化"，2–3 天）

**迭代对象不是 LLM，而是确定性层参数**，因为只有它能做样本外验证：

- 参数空间（小而正交）：
  - 评级→仓位映射：3 组候选（保守/默认/激进，如 Buy=80/100/120% 杠杆上限内）；
  - 执行 horizon 权重：评估用 5d 还是 21d alpha 作主指标；
  - 换仓阈值：目标仓位变动 < X% 时不动（省成本）。
- 每周 evaluate 时，在 `decisions.jsonl` 全历史上对每组候选参数**重放模拟组合**（P2 引擎），
  按"滚动 12 周 alpha 均值 / 波动"排序。
- **护栏（防过拟合，必须有）**：
  - 全历史决策数 < 30 条时不迭代，用默认参数；
  - 候选参数必须**连续 2 周**优于现役参数且超出阈值（如周 alpha 差 > 0.3%）才切换（滞回）；
  - 每次切换写入记分卡并 Telegram 通知，附前后对比，用户可一键回退；
  - 影子记录：未采用的候选参数净值也持续记录，作下周比较基准。

---

## 四、落地顺序与工作量

| 阶段 | 内容 | 预估 | 依赖 |
|---|---|---|---|
| P0 | decisions.jsonl 台账 | 1 天 | 无 |
| P1 | evaluate 命令 + 多 horizon 结算 + 记分卡 + 调度/Bot 接入 | 2–3 天 | P0 |
| P2 | 模拟组合（评级→仓位、净值 vs 基准） | 2–3 天 | P0 |
| P3 | 校准块回注 + 周度元反思 + 经验精选池 | 1–2 天 | P1 |
| P4 | 参数层 walk-forward 迭代 + 护栏 | 2–3 天 | P2 |

推荐节奏：先上 P0+P1（当周即有真实结算数据积累），P2 紧随（有了目标函数），
P3/P4 在积累 4–6 周、约 30+ 条已结算决策后再启用，避免小样本上瞎迭代。

### 每周运行时序（全部自动，Telegram 通知）

```
周六 07:30  tradingagents evaluate
            ├─ 结算全部到期 pending（5d/10d/21d，下一开盘价口径）
            ├─ 生成反思回填 trading_memory.md
            ├─ 计算记分卡 + 模拟组合净值
            ├─ 周度元反思 → 更新 lessons.md
            ├─ (P4) 参数重放评估，满足护栏则切换映射
            └─ Telegram 推送：净值/记分卡摘要/偏差警告/参数变更
周六 08:00  tradingagents batch（现有 weekly_all 任务）
            └─ 各 agent 提示词中已带上：最新校准块 + 精选经验 + 同票历史
用户         收到批量建议 + 每票目标仓位（由现役映射换算），按建议执行
```

---

## 五、新增/改动文件清单

```
新增
  tradingagents/eval/__init__.py
  tradingagents/eval/ledger.py          # decisions.jsonl 读写
  tradingagents/eval/resolver.py        # 多 horizon 结算（泛化 _fetch_returns，含下一开盘价口径）
  tradingagents/eval/scorecard.py       # 记分卡统计与 markdown 渲染
  tradingagents/eval/portfolio_sim.py   # 建议跟随模拟组合（重放式）
  tradingagents/eval/calibration.py     # 校准块生成（含最小样本护栏）
  cli/evaluate.py                       # tradingagents evaluate 子命令
改动
  tradingagents/graph/trading_graph.py  # store_decision 后写 ledger；researcher_context 注入
  tradingagents/agents/utils/memory.py  # get_past_context 拆分；lessons.md 精选池
  tradingagents/graph/reflection.py     # 周度元反思 prompt
  tradingagents/agents/researchers/*.py # 注入 researcher_context
  tradingagents/scheduler/tasks.py      # target: "evaluate" 任务类型
  tradingagents/bot/commands.py         # /scorecard 命令
  tradingagents/default_config.py       # eval_horizons / rating_weight_map / cost_bps / 护栏阈值
测试
  tests/test_ledger.py  tests/test_resolver.py  tests/test_scorecard.py
  tests/test_portfolio_sim.py（用固定价格序列做确定性断言）
```

### 新增配置项（default_config.py）

```python
"eval_horizons": [5, 10, 21],              # 交易日
"eval_execution": "next_open",             # 结算执行价口径
"eval_cost_bps": 10,                       # 单边交易成本
"rating_weight_map": {"Buy": 1.0, "Overweight": 0.7, "Hold": None,
                      "Underweight": 0.3, "Sell": 0.0},
"calibration_min_samples": 8,              # 每档最小样本量
"iteration_min_decisions": 30,             # P4 启动门槛
"iteration_switch_margin": 0.003,          # 参数切换周 alpha 差阈值
"lessons_max_entries": 20,
```

---

## 六、风险与边界（必须向用户明示）

1. **样本量与噪声**：周度、十几支票的决策流一年只有几百条样本，5d alpha 信噪比低。
   所有结论以滚动 12 周聚合为准，单周表现不驱动任何变更。
2. **过拟合**：P4 只在小参数空间（<10 组候选）+ 滞回 + 最小样本护栏下迭代；
   绝不做"每周自动改提示词措辞"这类不可验证的迭代。
3. **口径诚实**：记分卡同时展示 raw 与 alpha、含成本与不含成本，
   模拟组合永远与 SPY 及 watchlist 等权两条基准同框展示。
4. **数据依赖**：yfinance 拆股/分红用复权价（`auto_adjust=True`），退市票标记为无法结算而非静默丢弃。
5. **本方案不构成投资建议**；系统目标是让建议质量可测量、可校准、可持续改进，
   而非承诺任何收益水平。
```
