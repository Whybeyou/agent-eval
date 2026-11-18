# agent-eval

给 LLM Agent 用的**轻量评测框架**：固定集 + 规则机评 & LLM-Judge 双轨 + 加权打分 + Badcase 归因。

目标不是刷分，而是**定位缺陷并归因**——把「模型能力问题」和「Agent 链路问题 / 数据集问题 / 评测标准问题」分开，
不然每次都是拍脑袋改 prompt。

![ci](https://github.com/Whybeyou/agent-eval/actions/workflows/ci.yml/badge.svg)

## 它解决什么

工业界常见的两种失败模式：

1. **只测通用指标**（answer relevancy 之类）→ 判不了「CRS 是不是 EPSG:4490」「行数是不是等于过滤后数量」「有没有真的调工具」这种**领域硬事实**；
2. **只让 LLM 打分** → 它不会数数（8 条和 9 条它说「差不多」），也无法解释某条为什么挂。

所以本框架把判定拆成两条独立的轨：

```
             ┌─ 规则机评（硬断言）：可执行 / 数值 / 行数 / 工具调用 / 引用 / 越权
case ────────┤
             └─ LLM-Judge（语义）：完整度、语气、意图把握
                          ↓
              维度加权 + 风险一票否决 → pass/fail
                          ↓
              一致率（规则 vs Judge）→ 低就说明「标准本身有歧义」，先改 Rubric 再改项目
```

## 快速开始（30 秒，不需要 API key）

```bash
git clone https://github.com/Whybeyou/agent-eval && cd agent-eval
python examples/toy_agent/run_eval.py
```

示例里的「玩具客服 Agent」故意留了两个缺陷，跑完你会看到 `80% (8/10)` 和两条 badcase：

```
- TOY-B01 [边界-长问题]  失败断言=['cover']        ← 长问题只答前半（完整度）
- TOY-N01 [负向-知识外]  失败断言=['no','no_halluc'] ← 知识库没有也硬编（幻觉，风险一票否决）
```

还能跑一个**中文 RAG 客服**示例（BM25 检索 + 6 篇知识库 + 16 条固定集，同样离线）：

```bash
python examples/ecom_rag/run_eval.py
```

```
[EC-M03] rule=  0.0 pass=False   ← 多轮指代：追问「运费谁出」被当成通用运费问题
[EC-B01] rule= 50.0 pass=False   ← 一句话三个子问题，只答了发票那一个
检索命中率：Hit@1 90.0%  Hit@3 100.0%
通过率 87.5% (14/16)
```

这两个 badcase 很典型：**检索没错，是 Agent 的上下文处理和答案组织错了**——只看 Retrieval Hit 会误判成「系统没问题」。

想要 Judge 也参与：

```bash
export DEEPSEEK_API_KEY=...        # 或 EVAL_KEY_ENV 指定别的变量名
EVAL_JUDGE=1 python examples/toy_agent/run_eval.py
```

## 接入自己的 Agent

只要你的 Agent 能返回这个形状：

```python
{"answer": str, "tool_calls": [{"name": "search_knowledge", "query": "..."}], "data": {...}}
```

然后写一份 `cases.json`（声明式断言，加用例不用改代码）：

```json
{
  "id": "P01", "category": "正向", "turns": ["买了衣服尺码不合适能退吗"],
  "task": "退货政策硬事实",
  "golden": {"facts": ["7 天内", "不影响二次销售"]},
  "checks": [
    {"id": "route", "dim": "process", "type": "tool_called", "params": {"expected": true}},
    {"id": "f1",    "dim": "result",  "type": "contains_all", "params": {"all": ["7 天", "二次销售"]}},
    {"id": "cite",  "dim": "result",  "type": "cite_from", "params": {"any": ["退换货政策"]}}
  ]
}
```

跑批只需要三行：

```python
checks, dim_hits = evalkit.run_checks(case, ctx, evalkit.check)
scored           = evalkit.score_case(dim_hits)
evalkit.append_jsonl("results.jsonl", {**rec, **scored})
```

汇总：

```bash
python -m evalkit.report results.jsonl --name "我的 Agent"
```

## 内置断言

| 类型 | 用途 |
|---|---|
| `contains_any` / `contains_all` / `contains_n_of` | 关键词覆盖（any-of / all-of / N 个中几个） |
| `not_contains` | 禁用词（**要带完整谓语**，见坑 #3） |
| `regex` / `not_regex` | 格式校验、隐私泄露检测（手机号） |
| `max_len` / `min_len` | IM 场景长度控制 |
| `tool_called` | 路由决策：该检索才检索、寒暄不检索（`soft` 表示拿不准时不惩罚） |
| `cite_from` | 引用必须来自给定来源且带「来源」标注 |
| `json_field` | 结构化字段比较（缺失返回 NA） |

文本类断言都支持 `"body_only": true`：先剔除「（来源：…）」引用段再匹配。**有引用输出的系统务必打开**，
否则文档名里的字眼会让断言假通过（踩过，见坑 #11）。

领域断言用 `@evalkit.register("crs_family")` 扩展，返回 `True / False / None(NA)`。

## 打分规则

| 一级维度 | 默认权重 | 说明 |
|---|---|---|
| 过程 process | 0.25 | 意图理解、路由决策、工具调用、多轮承接 |
| 结果 result | 0.40 | 事实/数值正确、交付契约、完整性 |
| 表达 expression | 0.15 | 条理、长度、话术 |
| 风险 risk | 0.20 | 越权、编造、破坏性操作 —— **一票否决** |

- 单条：断言 0/10 → 维度均分 → 权重加权 → 0-100，`>= 80` 且风险无 Fail 才算通过。
- 某维度没有断言或全 NA → **不参与计算**（权重归一化），而不是按 0 算。
- 整体：固定集通过率（门槛一般 ≥90%）+ 一致率 + 分类通过率 + p50/p90 耗时。

## 踩过的坑（这些规则都是血泪）

1. **断言语义写反**：`stdout_has` 用 `all()` 实现，本该「任一命中」，结果 4 条正向用例集体假失败。→ 断言上线前先拿 2 条已知正例/反例自测。
2. **NA 被当成 0**：某维度没设断言却按 0 分算，把好结果拉成不及格。→ 权重归一化。
3. **禁用词没带谓语**：`forbid("支持比特币")` 会命中「**不**支持比特币」。→ 写完整断言「可以使用比特币」。
4. **同义表述漏配**：断言「买家承担」漏掉「买家**自己**承担」。→ 用 `contains_all(["买家","承担"])` 而不是单一短语。
5. **数量断言交给 LLM**：8 条 vs 9 条它能判「通过」。→ 数值/计数永远留给规则。
6. **拿字符串扫描当安全断言**：代码里 `print('拒绝写入 C:\\Windows')` 被误判成违规。→ 走 AST（判断「有没有真的调用」），别看字面量。
7. **kappa 在单边全过时无意义**：Judge 全通过时 κ 甚至为负。→ 只报一致率，或者两边都有人工校验过再算 κ。
8. **评测器自己崩**：numpy 标量让 `json.dumps` 直接抛错，整条记录丢失。→ 落盘前 `bool()`/`default=` 兜底。
9. **局部重跑清空历史**：`--only` 重跑时把结果文件删了，基线没了。→ 先按 id 过滤再追加。
10. **安全/标准改动必须回放**：加固后没重跑全量，把「模型改好了」误判成「又违规了」。
11. **引用标签污染断言**：答案带了 `（来源：发票开具::换开与重开）`，断言「换开」被文档名命中 → 假通过。→ 文本断言开 `body_only`。
12. **检索命中率≠答对**：电商 RAG 的 Hit@1 是 90%，但通过率只有 87.5%，两个 badcase 都是「检索对了、答偏了」。→ 命中率与通过率分开报，别用一个数盖住两类问题。

## 归因（执行环节的核心）

每条 badcase 必须落到四类之一，**先怀疑评测，再怀疑项目**：

| 类别 | 判据 | 处置 |
|---|---|---|
| 数据集问题 | 期望值写错、fixture 不真实、样本不具代表性 | 修数据，重跑，不进缺陷单 |
| 评测标准问题 | 断言过窄/过宽、Judge 与人工分歧、权重不合理 | 改 Rubric/断言，人工抽检 20% 校准 |
| 模型能力问题 | 上下文给全了模型仍推理错 | 换模型 / 加约束 / 给示例 |
| Agent 链路问题 | 提示词与执行层契约不一致、工具决策错、上下文丢失、环境缺陷 | 改代码，加回归用例防复发 |

## 目录结构

```
evalkit/
├── checks.py    # 断言注册表（8 种内置 + register 扩展）
├── scoring.py   # 维度加权 + 风险否决 + 阈值
├── judge.py     # LLM-Judge（强制 JSON、独立模型）
├── metrics.py   # pct / percentile / kappa / agreement
├── store.py     # JSONL 落盘、汇总、badcase 清单
├── report.py    # 一键出 Markdown 报告
├── perf.py      # 流式 TTFT/TPOT 探针 + Agent 端到端分位
└── llm.py       # OpenAI 兼容调用（key 只从环境变量读）
examples/toy_agent/   # 示例一：规则型客服（10 条 case，含 2 个刻意缺陷）
examples/ecom_rag/    # 示例二：中文 RAG 客服（BM25 检索 + 16 条 case + Hit@1/@3）
tests/                # 16 条框架自测（断言/打分/kappa/落盘/汇总/引用剔除）
```

## CI

`.github/workflows/ci.yml`：

| job | 内容 |
|---|---|
| `test` | 16 条框架自测 + 两个示例离线跑批 + **口径门禁**（通过率、badcase 集合必须与预期一致，防判定漂移） |
| `llm-judge` | 有 `DEEPSEEK_API_KEY` secret 时跑 `EVAL_JUDGE=1`，出人机一致率；无 secret 自动跳过 |
| `ecom-regression` | 电商示例单独跑，校验 Hit@1/@3 与通过率 |

## 许可

MIT
