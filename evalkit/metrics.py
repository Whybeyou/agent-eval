"""判定规则：Pass=10 / 部分=5 / Fail=0 / NA（不计分）。

规则机评负责「可判定的硬事实」（能不能执行、数值对不对、有没有调用工具），
LLM-Judge 负责「语义」（表达、完整度、意图）——两者独立出判定，一致率才说明标准本身没歧义。
"""
import json


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def percentile(vals, q):
    """线性插值分位数；空列表返回 None。"""
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 2)


def kappa(a, b):
    """Cohen's kappa：两套判定（二元 pass/fail）的一致性。

    提醒：任一方几乎全过/全不过时 kappa 数学上不稳定甚至无意义，此时只报一致率。
    返回 (一致率%, kappa) 或 (None, None)。
    """
    n = len(a)
    if n == 0:
        return None, None
    agree = sum(1 for x, y in zip(a, b) if bool(x) == bool(y))
    pa = agree / n
    pa1 = sum(1 for x in a if x) / n
    pb1 = sum(1 for y in b if y) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    k = (pa - pe) / (1 - pe) if pe != 1 else 1.0
    return round(pa * 100, 1), round(k, 3)


def agreement(rule_verdicts, judge_verdicts):
    """只保留两边都有判定的 case 再算一致率与 kappa。"""
    pairs = [(r, j) for r, j in zip(rule_verdicts, judge_verdicts) if j is not None and r is not None]
    if not pairs:
        return {"n": 0, "agreement": None, "kappa": None}
    rate, k = kappa([p[0] for p in pairs], [p[1] for p in pairs])
    return {"n": len(pairs), "agreement": rate, "kappa": k}
