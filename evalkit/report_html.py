"""单系统「评测报告」页（编辑册页风）：对外展示用，和监控舱控制台是两副面孔。

    python -m evalkit.cli report-html --suite gis_agent     # -> reports/report_gis_agent.html

为什么不复用控制台模板：控制台是 Monitor（盯状态、密度、实时），报告是 Decide/Learn
（一页讲清结论、证据和归因）。同一份数据换一种排版语言，比硬塞一个页面更诚实。
"""
import json
import os
import time

from .metrics import percentile
from .store import load_jsonl

CSS = """
:root{--paper:#f7f2e9;--ink:#17130e;--sub:#6b6157;--rule:#d7ccb9;--brick:#a63a1d;--olive:#5d6b3a}
*{box-sizing:border-box;margin:0}
body{background:var(--paper);color:var(--ink);
font:14px/1.75 "Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif}
.page{max-width:1180px;margin:0 auto;padding:36px 44px 70px}
.mast{display:flex;justify-content:space-between;align-items:baseline;
border-bottom:3px double var(--ink);padding-bottom:10px}
.brand{font:700 12px/1 "Courier New",monospace;letter-spacing:.32em;text-transform:uppercase}
.meta{font:11px/1.6 "Courier New",monospace;color:var(--sub);text-align:right;letter-spacing:.05em}
.lead{display:grid;grid-template-columns:1.5fr 1fr;gap:46px;padding:32px 0 26px;border-bottom:1px solid var(--rule)}
h1{font:700 44px/1.14 Georgia,"Songti SC","Times New Roman",serif;letter-spacing:-.015em}
h1 em{font-style:italic;color:var(--brick)}
.dek{margin-top:14px;color:var(--sub);font-size:13.5px;max-width:48ch}
.figs{display:grid;grid-template-columns:1fr 1fr;border-left:1px solid var(--rule)}
.fig{padding:8px 0 10px 18px;border-bottom:1px solid var(--rule)}
.fig:nth-child(odd){border-right:1px solid var(--rule)}
.fig .v{font:700 30px/1 Georgia,serif;letter-spacing:-.02em}
.fig .v.acc{color:var(--brick)}
.fig .k{font:10px/1.5 "Courier New",monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--sub);margin-top:6px}
.grid{display:grid;grid-template-columns:1.6fr 1fr;gap:46px;padding-top:28px}
h2{font:10px/1 "Courier New",monospace;letter-spacing:.22em;text-transform:uppercase;color:var(--sub);
border-bottom:1px solid var(--ink);padding-bottom:8px;margin-bottom:2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{font:10px/1 "Courier New",monospace;letter-spacing:.13em;text-transform:uppercase;color:var(--sub);
text-align:left;padding:9px 6px;border-bottom:1px solid var(--rule);font-weight:400}
td{padding:10px 6px;border-bottom:1px solid var(--rule);vertical-align:top}
td.id{font:11.5px/1.5 "Courier New",monospace;color:var(--sub)}
td.nm{font-family:Georgia,"Songti SC",serif;font-size:14px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.mark{font-family:"Courier New",monospace;font-size:11px}
.mark.ok{color:var(--olive)}.mark.no{color:var(--brick)}
ol{list-style:none;counter-reset:b}
ol li{counter-increment:b;border-bottom:1px solid var(--rule);padding:11px 0 11px 28px;position:relative;font-size:13px}
ol li:before{content:counter(b,decimal-leading-zero);position:absolute;left:0;top:12px;
font:11px/1 "Courier New",monospace;color:var(--brick)}
ol b{display:block;font-family:Georgia,serif;font-size:14px}
ol em{font-style:normal;color:var(--sub);font-size:11.5px;display:block;margin-top:2px}
.note{margin-top:24px;border-top:1px solid var(--ink);padding-top:12px;font-size:12px;color:var(--sub)}
.note b{color:var(--ink)}
.foot{margin-top:36px;border-top:3px double var(--ink);padding-top:10px;
font:10px/1.7 "Courier New",monospace;letter-spacing:.13em;color:var(--sub);text-transform:uppercase}
"""


def build(slug, runs_dir="runs", out=None, runs_dir_label=None):
    recs = load_jsonl(os.path.join(runs_dir, f"{slug}.jsonl"))
    if not recs:
        raise SystemExit(f"{runs_dir}/{slug}.jsonl 不存在或为空")
    suite = recs[0].get("suite") or slug
    n = len(recs)
    passed = [r for r in recs if r.get("rule_pass")]
    judged = [r for r in recs if r.get("judge_pass") is not None]
    judge_ok = [r for r in judged if r["judge_pass"]]
    times = [r["t_sut"] for r in recs if r.get("t_sut") is not None]
    rate = round(100.0 * len(passed) / n, 1)
    jrate = round(100.0 * len(judge_ok) / len(judged), 1) if judged else None
    agree = (
        round(100.0 * sum(1 for r in judged if bool(r["judge_pass"]) == bool(r["rule_pass"])) / len(judged), 1)
        if judged
        else None
    )
    bad = [r for r in recs if not r.get("rule_pass")]

    rows = []
    for r in recs:
        ok = r.get("rule_pass")
        rows.append(
            '<tr><td class="id">%s</td><td class="nm">%s</td><td class="num">%s</td>'
            '<td class="num">%s</td><td class="num">%ss</td>'
            '<td class="num"><span class="mark %s">%s</span></td></tr>' % (
                r.get("id"), r.get("category") or "",
                "%.1f" % r["rule_score"] if r.get("rule_score") is not None else "—",
                "%.1f" % r["judge_score"] if r.get("judge_score") is not None else "—",
                "%.2f" % r["t_sut"] if r.get("t_sut") is not None else "—",
                "ok" if ok else "no", "通过" if ok else "失败"))

    items = []
    for r in bad:
        failed = [c.get("check") for c in (r.get("checks") or []) if c.get("result") is False]
        reason = (r.get("judge") or {}).get("reason") or ""
        items.append("<li><b>%s</b><em>%s　失败断言：%s　%s</em></li>" % (
            r.get("id"), r.get("category") or "", "、".join(failed) or "—", reason[:90]))

    ts = times or [0]
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{suite} · 评测报告</title><style>{CSS}</style></head><body><div class="page">
<div class="mast"><div class="brand">AgentEval · Evaluation Report</div>
<div class="meta">{suite}<br>{time.strftime('%Y-%m-%d %H:%M')}　·　{runs_dir_label or runs_dir}/{slug}.jsonl</div></div>
<div class="lead">
  <div><h1>{suite}<br><em>{rate}%</em> 用例达标。</h1>
  <p class="dek">规则机评管硬事实（可执行性、数值、工具调用、越权），LLM-Judge 管语义；
  两轨独立判定再算一致率。风险维度一票否决：越权与编造不会被高分掩盖。</p></div>
  <div class="figs">
    <div class="fig"><div class="v acc">{rate}%</div><div class="k">规则通过率 {len(passed)}/{n}</div></div>
    <div class="fig"><div class="v">{jrate if jrate is not None else '—'}{'%' if jrate is not None else ''}</div><div class="k">Judge 通过率 {len(judged)} 条被判</div></div>
    <div class="fig"><div class="v">{len(bad)}</div><div class="k">待修 badcase</div></div>
    <div class="fig"><div class="v">{percentile(ts, 50)}s</div><div class="k">SUT p50 / p90 {percentile(ts, 90)}s</div></div>
  </div>
</div>
<div class="grid">
  <div><h2>用例明细</h2>
  <table><thead><tr><th>用例</th><th>分类</th><th class="num">规则分</th>
  <th class="num">Judge</th><th class="num">耗时</th><th class="num">结论</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table></div>
  <div><h2>待修坏例与归因</h2>
  <ol>{''.join(items) or '<li><b>无</b><em>当前没有 badcase —— 保持这份用例集继续回放</em></li>'}</ol>
  <div class="note"><b>归因规则：</b>每条失败落到 数据集 / 评测标准 / 模型能力 / Agent 链路 四类之一；
  先怀疑评测，再怀疑项目。一致率 {agree if agree is not None else '—'}{'%' if agree is not None else ''} —— 偏低说明标准本身有歧义，先改 Rubric。</div>
  </div>
</div>
<div class="foot">AgentEval · 固定集回放 · 证据链（断言 / 回答 / Judge 理由 / 耗时）见 runs/{slug}.jsonl 与 Web 控制台</div>
</div></body></html>"""

    out = out or os.path.join("reports", f"report_{slug}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out, {"suite": suite, "cases": n, "rate": rate, "bad": len(bad), "agreement": agree}
