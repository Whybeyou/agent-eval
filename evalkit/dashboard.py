"""跨系统看板：把多个 suite 的结果合成一张表。

这是「体系」和「几个脚本」的区别所在：不同 Agent、不同评测口径，最后必须能放在
同一张表里比较——通过率、风险失败数、人机一致率、SUT 侧耗时（不含评测开销）。

    python -m evalkit.cli report runs/
"""
import glob
import json
import os

from .metrics import agreement, pct, percentile
from .store import load_jsonl


def summarize_file(path):
    recs = load_jsonl(path)
    if not recs:
        return None
    suite = recs[0].get("suite") or os.path.basename(path)
    pass_n = sum(1 for r in recs if r.get("rule_pass"))
    judged = [r for r in recs if r.get("judge_pass") is not None]
    ag = agreement([r.get("rule_pass") for r in recs], [r.get("judge_pass") for r in recs])
    hits = [r for r in recs if r.get("hit1") is not None]
    times = [r.get("t_sut") for r in recs if r.get("t_sut") is not None]
    errs = [r["id"] for r in recs if r.get("error")]
    return {
        "suite": suite, "file": os.path.basename(path), "cases": len(recs),
        "pass": pass_n, "pass_rate": pct(pass_n, len(recs)),
        "judge_n": len(judged), "judge_rate": pct(sum(1 for r in judged if r["judge_pass"]), len(judged)),
        "agreement": ag["agreement"], "kappa": ag["kappa"],
        "risk_fail": sum(1 for r in recs if r.get("risk_fail")),
        "hit1": pct(sum(1 for r in hits if r["hit1"]), len(hits)) if hits else None,
        "hit_n": len(hits),
        "p50": percentile(times, 50), "p90": percentile(times, 90),
        "errors": errs,
        "badcases": [r["id"] for r in recs if not r.get("rule_pass")],
    }


def build(directory="runs"):
    files = sorted(glob.glob(os.path.join(directory, "*.jsonl")))
    rows = [s for s in (summarize_file(f) for f in files) if s]
    return rows


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def markdown(rows, title="Agent 评测看板"):
    if not rows:
        return f"### {title}\n\n（没有结果，先跑 `python -m evalkit.cli run suites/*`）"

    total_cases = sum(r["cases"] for r in rows)
    total_pass = sum(r["pass"] for r in rows)
    judge_n = sum(r["judge_n"] for r in rows)
    judge_ok = sum(round(r["judge_rate"] * r["judge_n"] / 100) for r in rows if r["judge_n"])
    lines = [
        f"### {title}",
        "",
        f"接入 **{len(rows)}** 个被测系统，共 **{total_cases}** 条用例；"
        f"规则机评合计 **{pct(total_pass, total_cases)}%**（{total_pass}/{total_cases}）"
        + (f"，LLM-Judge 判定 {judge_n} 条（通过率 {pct(judge_ok, judge_n)}%）" if judge_n else ""),
        "",
        "| 被测系统 | 用例 | 规则通过率 | Judge 通过率 | 一致率 κ | 风险失败 | Hit@1 | SUT p50 / p90 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        kappa = "—" if r["kappa"] is None else f"{r['kappa']}"
        lines.append(
            f"| {r['suite']} | {r['cases']} | {r['pass_rate']}% ({r['pass']}/{r['cases']}) | "
            f"{_fmt(r['judge_rate'] if r['judge_n'] else None, '%')} | {kappa} | {r['risk_fail']} | "
            f"{_fmt(r['hit1'], '%')} | {_fmt(r['p50'], 's')} / {_fmt(r['p90'], 's')} |")

    lines += ["", "**Badcase 与连接异常**", ""]
    for r in rows:
        ext = f"　⚠️ 连接/执行异常：{', '.join(r['errors'])}" if r["errors"] else ""
        lines.append(f"- `{r['suite']}`：{', '.join(r['badcases']) or '无'}{ext}")
    return "\n".join(lines)


def write(directory="runs", out="reports/dashboard.md"):
    rows = build(directory)
    md = markdown(rows)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    return md, rows
