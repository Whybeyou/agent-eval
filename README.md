# agent-eval

**一套 Agent 评测平台**：用统一协议接入多个真实系统 → 同一套用例与指标 → 一张跨系统看板。

它不是"给某个项目写几个测试脚本"，而是把评测做成**可复用的一层**：
新接一个系统只写一个 `adapter.py`（或让它暴露一个 `/api/eval/chat`），
用例、打分、一致率、看板、CI 门禁全部复用。

![ci](https://github.com/Whybeyou/agent-eval/actions/workflows/ci.yml/badge.svg)

## 当前接入的 6 个系统（实测）

| 被测系统 | 协议 | 用例 | 规则通过率 | Judge 通过率 | 一致率 κ | Hit@1 | SUT p50 |
|---|---|---|---|---|---|---|---|
| GIS 数据处理 Agent（自然语言→GIS 代码→沙箱执行） | python | 17 | 88.2% (15/17) | 82.4% | 0.767 | — | 4.91s |
| 电商客服 Agent（FastAPI 线上服务，混合检索 + Agentic RAG） | **http** | 8 | 100% (8/8) | 100% | 1.0 | 80% | 3.37s |
| 自主任务驱动 Agent（BabyAGI：执行/规划/排序 + 技能路由 + 记忆） | python | 2 | 100% (2/2) | — | — | — | 34.0s |
| 电商 RAG（本地 BM25 示例，离线可跑） | python | 16 | 87.5% (14/16) | — | — | 90% | — |
| **GIS 空间数据中台**（摄取/质量治理/分层落库/指标服务/血缘） | python | 11 | 100% (11/11) | — | — | — | 0.23s |
| 玩具客服（框架自检基线） | python | 10 | 80% (8/10) | — | — | — | — |

合计 **64 条用例，规则机评 90.6%（58/64）**；有 Judge 的 25 条一致率 88.0%。
每个系统都**故意留了未修的 badcase**——评测的价值在于把它们钉在名单上（见下方"归因"）。

## 30 秒上手（不需要 API key）

```bash
git clone https://github.com/Whybeyou/agent-eval && cd agent-eval
python -m evalkit.cli list                          # 有哪些系统、各自要不要连服务
python -m evalkit.cli run suites/toy_agent suites/ecom_rag   # 离线跑两个自带示例
python -m evalkit.cli report runs/                  # 出跨系统看板
```

```
### Agent 评测看板
接入 **6** 个被测系统，共 **64** 条用例；规则机评合计 **90.6%**（58/64），LLM-Judge 判定 25 条（通过率 88.0%）

| 被测系统 | 用例 | 规则通过率 | Judge 通过率 | 一致率 κ | 风险失败 | Hit@1 | SUT p50 / p90 |
|---|---|---|---|---|---|---|---|
| 电商客服 Agent（线上服务） | 8 | 100.0% (8/8) | 100.0% | 1.0 | 0 | 80.0% | 3.37s / 5.28s |
| GIS 数据处理 Agent | 17 | 88.2% (15/17) | 82.4% | 0.767 | 1 | — | 4.91s / 7.04s |
| 电商 RAG（本地 BM25 示例） | 16 | 87.5% (14/16) | — | — | 0 | 90.0% | — |
| 玩具客服 Agent（基线） | 10 | 80.0% (8/10) | — | — | 1 | — | — |
```

要连真实服务：

```bash
export GIS_AGENT_HOME=/path/to/gis-agent      # python 协议：直连被测项目
export ECOM_AGENT_URL=http://127.0.0.1:8010   # http 协议：线上服务
python -m evalkit.cli run suites/ --judge --env-file .env
```

## 体系结构

```
              ┌───────────────────── 同一套用例 / Rubric / 指标 ─────────────────────┐
              │                                                                     │
 suites/gis_agent/adapter.py ──┐                                     ┌── 规则机评（硬事实）
 suites/babyagi/adapter.py  ──┼──► evalkit.runner ──► 记录 JSONL ──┼── LLM-Judge（语义）
 suites/ecom_agent (HTTP)   ──┤        │                            └── 一致率 / κ
 suites/gis_datahub（数据管道）──┘        │
                                       │
                                  dashboard ──► 跨系统看板（一张表）
                                       │
                                  CI 门禁（新增 badcase 即失败）
```

一条 case 的固定流程：**取输入 → 调 SUT（两种协议之一）→ 归一化 → 断言 + Judge → 加权打分 → 落 JSONL → 汇总看板**。

## 接入一个新系统

写两个文件就够：

```
suites/my_agent/
├── suite.json     # 协议、用例文件、阈值、Rubric
├── cases.json     # 用例（声明式断言）
└── adapter.py     # 只有 python 协议需要
```

`suite.json`：

```json
{
  "name": "我的 Agent", "slug": "my_agent",
  "protocol": "http",  "url_env": "MY_AGENT_URL", "endpoint": "/api/eval/chat",
  "cases": "cases.json", "threshold": 80,
  "rubric": {"dimensions": {"process": {"weight": 0.25}, "result": {"weight": 0.40},
                            "expression": {"weight": 0.15}, "risk": {"weight": 0.20}}}
}
```

**两种协议**（`evalkit/sut.py`）：

| 协议 | 适用 | 约定 |
|---|---|---|
| `python` | 本地脚本 / 同机项目 | `adapter.run(turns, case) -> {"answer", "tool_calls", "data"}` |
| `http` | 线上服务 | `POST /api/eval/chat`，请求 `{"turns": [...]}`，响应同上 |

服务侧只要实现这一个出口，内部怎么走（检索、生成代码、沙箱执行）评测器不管。
`missing_env` 会让缺依赖的 suite 自动跳过，而不是报错中断整批。

## 用例长什么样

```json
{
  "id": "ECA-P01", "category": "正向-知识", "task": "退货运费责任方",
  "turns": ["七天无理由退货的退货运费谁承担？"],
  "golden": {"source": "退换货政策", "facts": ["买家承担"]},
  "checks": [
    {"id": "fact",  "dim": "result",  "type": "contains_all", "params": {"all": ["买家", "承担"]}},
    {"id": "route", "dim": "process", "type": "tool_called",  "params": {"name": "search_knowledge", "expected": true}}
  ]
}
```

内置断言：`contains_any / contains_all / contains_n_of / not_contains / regex / not_regex / max_len /
min_len / tool_called / cite_from / json_field`；领域断言用 `@register("rows_eq")` 扩展
（GIS suite 就是这么接进来的：行数、CRS、面积、字段、AST 越权——全部读产物本身，不看模型自述）。

数据类断言（给数据管道用）在 `evalkit/checks_data.py`：`reject_breakdown / metric_close / metric_keys /
idempotent / http_status / api_shape / lineage_has / no_metric`——判的是数据事实（行数、拒绝分布、指标值、
幂等、血缘、接口契约、越权拒绝），这类系统上 LLM-Judge 基本没用武之地。

文本类断言支持 `"body_only": true`：先剔除「（来源：…）」再匹配，否则文档名会让断言假通过。

## 指标口径

| 口径 | 定义 | 用途 |
|---|---|---|
| 规则通过率 | 加权总分 ≥ 阈值（80）且风险维度无 Fail | 主判据，进 CI 门禁 |
| 人机一致率 / κ | 规则 verdict vs Judge verdict | 低 → 说明**标准本身有歧义**，先改 Rubric |
| 风险一票否决 | 越权/编造/破坏性操作为 Fail 时整条不通过 | 安全底线，不被高分掩盖 |
| Hit@1 / Hit@3 | 期望文档是否进 top-k | 区分「没检索到」与「检索到但答偏」 |
| SUT p50 / p90 | 仅统计被测系统耗时（不含评测开销） | 性能回归 |

某维度没有断言或全 NA → 权重重归一化，**不按 0 分算**（否则好结果会被拉成不及格）。

## 归因：评测的产出不是分数，是定位

每条 badcase 必须落到四类之一，**先怀疑评测，再怀疑项目**：

| 类别 | 判据 | 处置 |
|---|---|---|
| 数据集问题 | 期望值错、fixture 不真实/不存在 | 修数据，不进缺陷单 |
| 评测标准问题 | 断言过窄/过宽、Judge 与人工分歧 | 改 Rubric，人工抽检 |
| 模型能力问题 | 上下文给全仍答错 | 换模型 / 加约束 / 给示例 |
| Agent 链路问题 | 契约不一致、工具实现 bug、状态丢失 | 改代码 + 补回归用例 |

真实例子（都在本仓的 badcase 名单里）：

- **数据集**：GIS-B03 在 CI 上必挂——case 用 `no_crs.shp`，但 fixtures 脚本只生成 `no_crs.geojson`。本地能过是因为有人手工放过一个 shp。→ 让脚本自己产出"删掉 .prj 的 Shapefile"。
- **评测标准**：ECA-P01 第一次判错，答案是「由**买家（您）承担**」，断言写的是 `contains_all(["买家承担"])` → 括号打断了字面匹配。→ 改成语义组合 `["买家","承担"]`。
- **Agent 链路**：BabyAGI 写 `sub/sum.txt` 直接 `FileNotFoundError`——`write_file` 工具没建父目录。→ 修工具，并把这条 case 留作回归。
- **数据管道（新接入的中台）**：空 CSV 触发 pandas `EmptyDataError` 直接崩（应在质量层判 fail）；`api.py` 用了 `str | None` 在 Python 3.9 抛 `TypeError`；`Polygon()` 的 `is_valid=True` 让空几何漏过校验；拒绝原因没进产物，人看日志看不到。→ 四个都修了，并各自留了回归。
- **链路（跨系统）**：框架自身也曾把用例跑错对象——两个 suite 都有 `adapter.py`，`import_module` 命中 `sys.modules` 缓存，用 A 的适配器跑了 B 的用例。→ 改为按文件路径加载 + 唯一模块名，并加了 `test_two_suites_with_same_module_name_are_isolated` 回归测试。

## 其它踩过的坑

1. 断言 `any/all` 写反：`stdout_has` 用 `all()` 实现，本该"任一命中"，4 条正向用例集体假失败。
2. NA 被当 0：某维度没断言却按 0 算，把好结果拉成不及格。→ 权重重归一化。
3. 禁用词没带谓语：`forbid("支持比特币")` 会命中「**不**支持比特币」。→ 写完整断言。
4. 数量断言交给 LLM：8 条 vs 9 条它说"差不多"。→ 计数/数值永远留给规则。
5. 拿字符串扫描当安全断言：`print('拒绝写入 C:\\Windows')` 被误判违规。→ 走 AST 判断"有没有真的调用"。
6. κ 在单边全过时无意义（甚至为负）。→ 只报一致率，或两边都人工校验后再算 κ。
7. 评测器自己崩：numpy 标量让 `json.dumps` 抛错，整条记录丢失。→ 落盘前 `bool()` / `default=` 兜底。
8. SUT 挂了要留记录，不能整批中断。→ 异常写进 `error` 字段并继续下一条。

## 目录结构

```
evalkit/
├── sut.py        # 两种接入协议：python 调用 / HTTP 服务（含模块隔离与归一化）
├── runner.py     # suite 加载、单条执行、断言→打分→落盘、Hit@k
├── cli.py        # list / run / report（--judge / --only / --env-file / --strict）
├── checks.py     # 断言注册表
├── checks_data.py # 数据类断言（拒绝分布/指标/幂等/血缘/接口契约）
├── scoring.py    # 维度加权 + 风险否决 + 阈值
├── judge.py      # LLM-Judge（强制 JSON、与被测模型错开）
├── metrics.py    # pct / percentile / kappa / agreement
├── dashboard.py  # 跨系统看板
├── store.py      # JSONL 落盘与单系统汇总
├── report.py     # 单系统 Markdown 报告
└── perf.py       # 流式 TTFT / TPOT 探针
suites/
├── gis_agent/    # 17 条 + fixtures 生成器 + 30 余个领域断言（python 协议）
├── ecom_agent/   # 8 条，打真实 FastAPI 服务（http 协议）
├── babyagi/      # 2 条，解析 stdout 与产物（python 协议）
├── gis_datahub/  # 11 条，数据管道（每条用独立临时库，避免状态污染）
├── ecom_rag/     # 16 条，纯标准库 BM25 离线示例
└── toy_agent/    # 10 条，框架自检基线
tests/            # 26 条平台自测（断言/数据断言/打分/κ/协议隔离/看板/落盘）
```

## CI

`.github/workflows/ci.yml`：

| job | 内容 |
|---|---|
| `test` | 26 条平台自测 + 两个离线 suite 跑批 + **口径门禁**（通过率区间与 badcase 集合必须与预期一致，防判定漂移） |
| `llm-judge` | 有 `DEEPSEEK_API_KEY` 时跑 `--judge`，一致率低于 60% 直接失败 |
| `ecom-regression` | 电商示例单独跑，校验 Hit@1/@3 |

需要外部依赖的 suite（`gis_agent` 需要 geopandas、`ecom_agent` 需要 8010 服务、`babyagi` 需要项目目录、
`gis_datahub` 需要项目目录 + pandas/geopandas）在本仓 CI 里按 `missing_env` 自动跳过，由各自项目仓的 CI
装好依赖后执行——**同一套用例，两处复用**。

## 许可

MIT
