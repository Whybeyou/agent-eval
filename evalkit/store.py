"""结果落盘与汇总：JSONL 存原始记录，report 出人看的数字。

JSONL 里要留**证据**（实际输出、每个断言的通过情况、Judge 理由、耗时），
不然 badcase 归因时会变成「凭印象改代码」。
"""
import json
import os

from .metrics import agreement, pct, percentile


def append_jsonl(path, rec):
    """numpy 标量兜底，避免评测器自己因序列化失败丢记录。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def _default(o):
        try:
            return o.item()          # numpy 标量
        except Exception:
            return str(o)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=_default) + "\n")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def summarize(records, name="agent", tr_field="t_total"):
    """通过率 / 分类 / 维度均分 / 一致率 / 耗时。"""
    n = len(records)
    rule_pass = [r for r in records if r.get("rule_pass")]
    judged = [r for r in records if r.get("judge_pass") is not None]

    cats = {}
    for r in records:
        c = cats.setdefault(r.get("category", "未分类"),
                            {"n": 0, "rule_pass": 0, "judge_n": 0, "judge_pass": 0, "scores": []})
        c["n"] += 1
        c["rule_pass"] += 1 if r.get("rule_pass") else 0
        if r.get("judge_pass") is not None:
            c["judge_n"] += 1
            c["judge_pass"] += 1 if r.get("judge_pass") else 0
        if r.get("rule_score") is not None:
            c["scores"].append(r["rule_score"])

    dims = {}
    for r in records:
        for d, s in (r.get("dim_scores") or {}).items():
            if s != "NA":
                dims.setdefault(d, []).append(s)

    scores = [r["rule_score"] for r in records if r.get("rule_score") is not None]
    times = [r[tr_field] for r in records if r.get(tr_field) is not None]
    return {
        "project": name,
        "cases": n,
        "rule_pass": len(rule_pass),
        "rule_pass_rate": pct(len(rule_pass), n),
        "judge_cases": len(judged),
        "judge_pass": sum(1 for r in judged if r.get("judge_pass")),
        "judge_pass_rate": pct(sum(1 for r in judged if r.get("judge_pass")), len(judged)),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "dim_avg": {d: round(sum(v) / len(v), 1) for d, v in dims.items()},
        "by_category": {c: {"n": v["n"], "rule_pass_rate": pct(v["rule_pass"], v["n"]),
                            "judge_pass_rate": pct(v["judge_pass"], v["judge_n"]),
                            "avg_score": round(sum(v["scores"]) / len(v["scores"]), 1) if v["scores"] else None}
                        for c, v in cats.items()},
        "agreement": agreement([r.get("rule_pass") for r in records],
                               [r.get("judge_pass") for r in records]),
        "times": {"p50": percentile(times, 50), "p90": percentile(times, 90),
                  "max": max(times) if times else None},
    }


def badcases(records):
    out = []
    for r in records:
        if not (r.get("rule_pass") is False or r.get("judge_pass") is False):
            continue
        out.append({
            "id": r.get("id"), "category": r.get("category"),
            "rule_score": r.get("rule_score"), "judge_score": r.get("judge_score"),
            "failed_checks": [c["check"] for c in (r.get("checks") or []) if c.get("result") is False],
            "judge_reason": ((r.get("judge") or {}).get("reason") or "")[:200],
        })
    return out


def markdown(summary):
    s = summary
    a = s["agreement"]
    lines = [
        f"### {s['project']}",
        "",
        "| Case | 规则通过率 | Judge 通过率 | 均分 | 一致率 | κ | p50 / p90 |",
        "|---|---|---|---|---|---|---|",
        f"| {s['cases']} | {s['rule_pass_rate']}% ({s['rule_pass']}/{s['cases']}) | "
        f"{s['judge_pass_rate']}% ({s['judge_pass']}/{s['judge_cases']}) | {s['avg_score']} | "
        f"{a['agreement']}% | {a['kappa']} | {s['times']['p50']}s / {s['times']['p90']}s |",
        "",
        "分类：" + " · ".join(f"{c} {v['rule_pass_rate']}%" for c, v in s["by_category"].items()),
        "维度均分（0-10）：" + " · ".join(f"{d} {v}" for d, v in s["dim_avg"].items()),
    ]
    return "\n".join(lines)
