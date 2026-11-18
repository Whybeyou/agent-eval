"""agent-eval —— 给 LLM Agent 用的轻量评测框架。

设计目标不是「刷分」，而是**定位缺陷并归因**：

    固定集 → 规则机评 + LLM-Judge（双轨、独立判定）→ 加权打分 → 一致率 → Badcase 四类归因

三件套：
  * evalkit.checks   —— 声明式断言注册表（本例内置 8 种，可 register 扩展领域断言）
  * evalkit.scoring  —— 维度加权 + 风险一票否决 + 阈值判定
  * evalkit.report   —— 通过率 / 分类 / 维度均分 / 一致率+kappa / badcase 清单
"""
from . import checks  # noqa: F401
from . import checks_data  # noqa: F401  注册数据类断言（reject_breakdown / metric_close / idempotent ...）
from . import judge, llm, metrics, perf, report, scoring, store  # noqa: F401
from .checks import check, register  # noqa: F401
from .judge import judge_case, parse_json_loose  # noqa: F401
from .llm import llm  # noqa: F401
from .metrics import kappa, pct, percentile  # noqa: F401
from .scoring import run_checks, score_case  # noqa: F401
from .store import append_jsonl, load_jsonl  # noqa: F401

__version__ = "0.1.0"
__all__ = [
    "check", "register", "judge_case", "parse_json_loose", "llm",
    "kappa", "pct", "percentile", "run_checks", "score_case",
    "append_jsonl", "load_jsonl", "checks", "judge", "metrics",
    "perf", "report", "scoring", "store",
]
