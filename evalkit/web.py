"""把 runs/*.jsonl 渲染成一个自包含 HTML 看板（无 CDN、无 JS 框架、无服务端）。

为什么是静态页而不是先上 SPA：
  * 评测结果是**离线产物**，需要能直接发给别人 / 挂 GitHub Pages / 存进归档；
  * 一个文件里带着全部证据（断言明细、回答、耗时），比"再起一个服务"更可靠；
  * 真要在线跑批，再加一层 API 即可（`--serve` 留给后续）。

    python -m evalkit.cli web            # -> reports/dashboard.html
"""
import glob
import html
import json
import os
import time

from .dashboard import summarize_file
from .store import load_jsonl

CSS = """
:root{--bg:#0f1115;--card:#171a21;--bd:#262b36;--fg:#e6e8ee;--mut:#8b93a7;
--ok:#3ecf8e;--warn:#f5a524;--bad:#ff5c5c;--accent:#6ea8fe}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif}
header{padding:28px 32px 18px;border-bottom:1px solid var(--bd)}
h1{margin:0 0 6px;font-size:20px;letter-spacing:.3px}
.sub{color:var(--mut);font-size:13px}
.cards{display:flex;gap:14px;flex-wrap:wrap;padding:22px 32px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 18px;min-width:150px}
.card .k{color:var(--mut);font-size:12px}
.card .v{font-size:24px;font-weight:600;margin-top:4px}
main{padding:0 32px 60px}
table{width:100%;min-width:900px;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.tw{overflow-x:auto;border-radius:10px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--bd);font-size:13px;vertical-align:middle}
th{color:var(--mut);font-weight:500;background:#1b1f27;white-space:nowrap}
td:nth-child(1){min-width:210px}td:nth-child(9){min-width:150px}
tr:last-child td{border-bottom:none}
.bar{position:relative;height:8px;border-radius:5px;background:#232833;min-width:80px}
.bar>i{position:absolute;inset:0 auto 0 0;border-radius:5px;background:var(--ok)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--bd)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.mut{color:var(--mut)}
h2{margin:30px 0 10px;font-size:16px;border-left:3px solid var(--accent);padding-left:10px}
details{background:var(--card);border:1px solid var(--bd);border-radius:8px;margin:8px 0;padding:10px 14px}
summary{cursor:pointer;font-size:13px}
summary .id{font-weight:600;margin-right:8px}
code{background:#11141b;border:1px solid var(--bd);border-radius:4px;padding:1px 5px;font-size:12px}
pre{white-space:pre-wrap;word-break:break-word;background:#11141b;border:1px solid var(--bd);border-radius:6px;padding:10px;font-size:12px;max-height:280px;overflow:auto}
.checks{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.chk{border:1px solid var(--bd);border-radius:6px;padding:2px 8px;font-size:12px}
"""


def _cls(rate):
    if rate is None:
        return "mut"
    return "ok" if rate >= 90 else ("warn" if rate >= 70 else "bad")


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def _esc(s):
    return html.escape(str(s if s is not None else ""))


def _suite_section(path):
    recs = load_jsonl(path)
    if not recs:
        return ""
    s = summarize_file(path)
    if not s:
        return ""
    panel = []
    panel.append("<details open><summary>")
    panel.append(f'<span class="id">{_esc(s["suite"])}</span>')
    panel.append(f'<span class="{_cls(s["pass_rate"])}">{s["pass_rate"]}%</span> ')
    panel.append(f'<span class="mut">（{s["pass"]}/{s["cases"]}）</span>')
    if s["badcases"]:
        panel.append(f'　<span class="bad">badcase：{_esc(", ".join(s["badcases"]))}</span>')
    panel.append("</summary>")

    for r in recs:
        passed = bool(r.get("rule_pass"))
        mark = "ok" if passed else "bad"
        head = (f'<summary><span class="{mark}">{"✔" if passed else "✘"}</span> '
                f'<span class="id">{_esc(r.get("id"))}</span>'
                f'<span class="mut">{_esc(r.get("category", ""))}</span>'
                f'　<span class="pill">rule {_fmt(r.get("rule_score"))}</span>'
                + (f' <span class="pill">judge {_fmt(r.get("judge_score"))}</span>'
                   if r.get("judge_score") is not None else "")
                + f' <span class="pill">{_fmt(r.get("t_sut"))}s</span>'
                + (f' <span class="bad">risk fail</span>' if r.get("risk_fail") else "")
                + "</summary>")
        body = ["<div>"]
        if r.get("turns"):
            body.append(f'<div class="mut">输入：{_esc(" ｜ ".join(r["turns"]))}</div>')
        body.append(f"<pre>{_esc(r.get('answer'))}</pre>")
        if r.get("checks"):
            chips = []
            for c in r["checks"]:
                res = c.get("result")
                cls = "ok" if res is True else ("bad" if res is False else "mut")
                label = "通过" if res is True else ("失败" if res is False else "NA")
                chips.append(f'<span class="chk {cls}">{_esc(c.get("check"))} · {c.get("dim")} · {label}'
                             + (f'　{_esc(c.get("err"))}' if c.get("err") else "") + "</span>")
            body.append('<div class="checks">' + "".join(chips) + "</div>")
        if r.get("judge", {}).get("reason"):
            body.append(f'<div class="mut">Judge：{_esc(r["judge"]["reason"])}</div>')
        if r.get("error"):
            body.append(f'<div class="bad">SUT 异常：{_esc(r["error"])}</div>')
        body.append("</div>")
        panel.append(f"<details>{head}{''.join(body)}</details>")

    panel.append("</details>")
    return "\n".join(panel)


def build_html(runs_dir="runs", out="reports/dashboard.html", title="Agent 评测看板"):
    files = sorted(glob.glob(os.path.join(runs_dir, "*.jsonl")))
    rows = [s for s in (summarize_file(f) for f in files) if s]
    total_cases = sum(r["cases"] for r in rows)
    total_pass = sum(r["pass"] for r in rows)
    overall = round(100.0 * total_pass / total_cases, 1) if total_cases else 0.0
    judge_n = sum(r["judge_n"] for r in rows)
    judge_ok = sum(round(r["judge_rate"] * r["judge_n"] / 100) for r in rows if r["judge_n"])
    bad_total = sum(len(r["badcases"]) for r in rows)

    head = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>{CSS}</style></head><body>
<header><h1>{_esc(title)}</h1>
<div class="sub">生成于 {time.strftime('%Y-%m-%d %H:%M:%S')} · 数据源 <code>{_esc(runs_dir)}/*.jsonl</code>
· 规则机评与 LLM-Judge 独立判定</div></header>
<div class="cards">
  <div class="card"><div class="k">接入系统</div><div class="v">{len(rows)}</div></div>
  <div class="card"><div class="k">用例总数</div><div class="v">{total_cases}</div></div>
  <div class="card"><div class="k">规则通过率</div><div class="v {_cls(overall)}">{overall}%</div></div>
  <div class="card"><div class="k">仍有 badcase</div><div class="v {('ok' if bad_total == 0 else 'warn')}">{bad_total}</div></div>
  <div class="card"><div class="k">Judge 判定</div><div class="v">{judge_n}</div></div>
  <div class="card"><div class="k">Judge 通过率</div><div class="v">{_fmt(round(100.0 * judge_ok / judge_n, 1) if judge_n else None, '%')}</div></div>
</div>
<main>
<div class="tw"><table><thead><tr>
<th>被测系统</th><th>用例</th><th>规则通过率</th><th>Judge</th><th>一致率 κ</th>
<th>风险失败</th><th>Hit@1</th><th>SUT p50 / p90</th><th>badcase</th>
</tr></thead><tbody>"""

    body = []
    for r in sorted(rows, key=lambda x: -x["pass_rate"]):
        body.append(
            f"<tr><td>{_esc(r['suite'])}</td><td>{r['cases']}</td>"
            f"<td><div class='bar'><i style='width:{r['pass_rate']}%;background:"
            f"{'var(--ok)' if r['pass_rate'] >= 90 else ('var(--warn)' if r['pass_rate'] >= 70 else 'var(--bad)')}'></i></div>"
            f"<span class='{_cls(r['pass_rate'])}'>{r['pass_rate']}%</span> <span class='mut'>({r['pass']}/{r['cases']})</span></td>"
            f"<td>{_fmt(r['judge_rate'] if r['judge_n'] else None, '%')}</td>"
            f"<td>{_fmt(r['kappa'])}</td><td>{r['risk_fail']}</td>"
            f"<td>{_fmt(r['hit1'], '%')}</td>"
            f"<td>{_fmt(r['p50'], 's')} / {_fmt(r['p90'], 's')}</td>"
            f"<td class='{'mut' if not r['badcases'] else 'bad'}'>{_esc(', '.join(r['badcases']) or '无')}</td></tr>")

    sections = "\n".join(_suite_section(f) for f in files)
    tail = f"""</tbody></table></div>
<h2>逐条证据</h2>
<p class="sub">点开任意一条可以看到：输入、实际回答、每条断言的结果、Judge 理由与 SUT 耗时。
评测的价值在证据链，不在分数本身。</p>
{sections}
</main></body></html>"""

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(body) + tail)
    return out, {"systems": len(rows), "cases": total_cases, "rate": overall, "badcases": bad_total}


if __name__ == "__main__":
    print(build_html())
